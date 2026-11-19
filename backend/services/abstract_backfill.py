"""Fill in missing abstracts of library papers from open metadata services.

Many papers enter a library by DOI or title list and never get an abstract, which makes them
embed poorly for semantic search. This module finds the papers that have a DOI but an empty
abstract and asks, in this order and only for what is still missing:

1. OpenAlex        (batch of up to 50 DOIs, abstract rebuilt from its inverted index)
2. Semantic Scholar (batch endpoint, 100 ids anonymous / 500 with an API key)
3. arXiv           (only DOIs ``10.48550/arXiv.<id>``, up to 100 ids per request, 3 s apart)
4. Crossref        (one DOI per request, JATS markup stripped)

An abstract is accepted only if the title the service returns matches the library title, the
text is 80 to 6000 characters long and is not a placeholder. Nothing is ever overwritten: the
write is guarded in Cypher (``abstract IS NULL OR trim(abstract) = ''``), so an abstract that
appears between the selection and the write wins. Dry run is the default and writes nothing.

The only data that leaves the instance are DOIs (and, with ``title_search``, titles of papers
without a DOI), sent to the four services above. Spec: ``.specs/021_abstract_backfill.md``.
"""
from __future__ import annotations

import difflib
import email.utils
import hashlib
import html
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import quote

import httpx

from services.duplicate_scan import normalize_doi

log = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

SOURCES = ("openalex", "semanticscholar", "arxiv", "crossref")
SOURCE_ALIASES = {"semantic_scholar": "semanticscholar", "s2": "semanticscholar"}

REF_TAG = "from-references"
MIN_ABSTRACT_CHARS = 80
MAX_ABSTRACT_CHARS = 6000
TITLE_MATCH_RATIO = 0.88
TITLE_STRICT_RATIO = 0.97          # title search finds papers by title, so the bar is higher
TITLE_PREFIX_COVERAGE = 0.9

OPENALEX_URL = "https://api.openalex.org/works"
OPENALEX_BATCH = 50
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_BATCH_ANON = 100
S2_BATCH_KEY = 500
ARXIV_URL = "https://export.arxiv.org/api/query"
ARXIV_BATCH = 100
CROSSREF_URL = "https://api.crossref.org/works"

# Minimum seconds between two requests to the same host.
INTERVAL_OPENALEX = 0.2
INTERVAL_S2_ANON = 3.0
INTERVAL_S2_KEY = 1.1
INTERVAL_ARXIV = 3.1
INTERVAL_CROSSREF = 0.25

MAX_RETRIES = 3
BACKOFF_BASE = 1.0
MAX_RETRY_AFTER = 120.0            # a longer Retry-After gives the source up for this run
REQUEST_TIMEOUT = 25.0
MAX_ERRORS_LISTED = 50

# ── Cypher (all parameterised) ────────────────────────────────────────────────

_STUB_CLAUSE = "($include_stubs OR NOT EXISTS { (p)-[:TAGGED]->(:Tag {name: $ref_tag}) })"
_EMPTY_ABSTRACT = "(p.abstract IS NULL OR trim(p.abstract) = '')"

CANDIDATES_QUERY = f"""
MATCH (p:Paper)
WHERE {_EMPTY_ABSTRACT}
  AND p.doi IS NOT NULL AND trim(p.doi) <> ''
  AND {_STUB_CLAUSE}
RETURN p.id AS id, p.doi AS doi, p.title AS title
ORDER BY p.id
"""

NO_DOI_QUERY = f"""
MATCH (p:Paper)
WHERE {_EMPTY_ABSTRACT}
  AND (p.doi IS NULL OR trim(p.doi) = '')
  AND {_STUB_CLAUSE}
RETURN p.id AS id, p.title AS title
ORDER BY p.id
"""

WRITE_QUERY = """
MATCH (p:Paper {id: $id})
WHERE p.abstract IS NULL OR trim(p.abstract) = ''
SET p.abstract = $abstract, p.abstract_source = $source, p.abstract_fetched_at = $now
RETURN p.id AS id
"""

UNDO_READ_QUERY = """
MATCH (p:Paper {id: $id})
RETURN p.abstract AS abstract, p.abstract_source AS source
"""

UNDO_WRITE_QUERY = """
MATCH (p:Paper {id: $id})
WHERE p.abstract_source = $source AND p.abstract = $abstract
REMOVE p.abstract, p.abstract_source, p.abstract_fetched_at
RETURN p.id AS id
"""

# ── text cleaning ─────────────────────────────────────────────────────────────

_INLINE_TAGS = re.compile(
    r"</?(?:jats:)?(?:i|b|em|strong|italic|bold|sub|sup|u|tt|monospace|sc|small|span|font|mml:[a-z]+)\b[^>]*>",
    re.I,
)
_HEADING_TAG = re.compile(
    r"<(?:jats:)?title[^>]*>\s*(?:abstract|summary)\s*:?\s*</(?:jats:)?title>", re.I)
_ABSTRACT_PUNCT_PREFIX = re.compile(r"^\s*abstract\s*[:.–—-]\s*", re.I)
_ABSTRACT_LINE_PREFIX = re.compile(r"^\s*abstract\s*\n", re.I)
_ABSTRACT_CAPS_PREFIX = re.compile(r"^\s*ABSTRACT\s+(?=\S)")
# A tag starts with a letter or "/", so "p < 0.05" and "x<3" stay text.
_TAG = re.compile(r"</?[A-Za-z][^<>]*>")

_PLACEHOLDERS = re.compile(
    r"^(?:\[?\s*(?:the\s+)?(?:abstract\s+(?:is\s+)?(?:not\s+available|unavailable)|"
    r"no\s+abstract(?:\s+(?:available|provided|found))?|"
    r"not\s+available|not\s+applicable|n/?a|none|null|nil|tbd|"
    r"this\s+(?:article|paper|item)\s+has\s+no\s+abstract|"
    r"graphical\s+abstract|abstract\s+only|no\s+summary\s+available)\s*\]?)\.?$",
    re.I,
)


def clean_abstract(raw: str | None) -> str:
    """Plain text of an abstract as the services deliver it: entities decoded, JATS and HTML
    tags dropped, heading "Abstract" removed, whitespace collapsed. Empty string if nothing."""
    if not raw or not isinstance(raw, str):
        return ""
    text = _HEADING_TAG.sub(" ", raw)
    text = _INLINE_TAGS.sub("", text)
    text = _ABSTRACT_LINE_PREFIX.sub("", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _ABSTRACT_PUNCT_PREFIX.sub("", text)
    text = _ABSTRACT_CAPS_PREFIX.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_title(title: str | None) -> str:
    t = html.unescape(_TAG.sub(" ", str(title or "")))
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def titles_match(library_title: str | None, returned_title: str | None, *, strict: bool = False) -> bool:
    """True when two titles name the same paper: equal after normalisation, difflib ratio
    (plain or with the words sorted) at least 0.88, word-set overlap at least 0.88, or one a
    prefix of the other covering at least 0.9. The numbers in both titles must be the same.
    ``strict`` (title search) needs 0.97 or equality."""
    a, b = _norm_title(library_title), _norm_title(returned_title)
    if not a or not b:
        return False
    if a == b:
        return True
    if sorted(re.findall(r"\d+", a)) != sorted(re.findall(r"\d+", b)):
        return False                       # "Part 1" and "Part 2", "GPT-3" and "GPT-4" are not one paper
    need = TITLE_STRICT_RATIO if strict else TITLE_MATCH_RATIO
    if difflib.SequenceMatcher(None, a, b).ratio() >= need:
        return True
    if strict:
        return False
    sa, sb = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    if difflib.SequenceMatcher(None, sa, sb).ratio() >= need:
        return True
    ta, tb = set(a.split()), set(b.split())
    if ta and tb and len(ta & tb) / len(ta | tb) >= need:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return long_.startswith(short) and len(short) / len(long_) >= TITLE_PREFIX_COVERAGE


def quality_problem(text: str, library_title: str | None = None) -> str | None:
    """Why a cleaned abstract is not usable (``too_short``, ``too_long``, ``placeholder``,
    ``not_text``, ``title_only``), or None."""
    if not text:
        return "empty"
    if _PLACEHOLDERS.match(text.strip()) or (
            len(text) < 200 and re.match(r"(?:abstract\s+(?:is\s+)?not\s+available|no\s+abstract\s+available)", text, re.I)):
        return "placeholder"
    nt, na = _norm_title(library_title), _norm_title(text)
    if nt and na and (na == nt or (na.startswith(nt) and len(na) - len(nt) < 20)):
        return "title_only"
    if len(text) < MIN_ABSTRACT_CHARS:
        return "too_short"
    if len(text) > MAX_ABSTRACT_CHARS:
        return "too_long"
    visible = re.sub(r"\s+", "", text)
    letters = sum(c.isalpha() for c in visible)
    if not visible or letters / len(visible) < 0.6:
        return "not_text"
    return None


def rebuild_inverted_index(index: dict | None) -> str:
    """OpenAlex stores abstracts as ``{word: [positions]}``; put the words back in order."""
    if not isinstance(index, dict) or not index:
        return ""
    slots: dict[int, str] = {}
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int) and pos >= 0:
                slots.setdefault(pos, str(word))
    return " ".join(slots[i] for i in sorted(slots))


# ── DOI handling ──────────────────────────────────────────────────────────────

def doi_for_lookup(raw: str | None) -> str | None:
    """Lower-case bare DOI (``10.x/y``) from any stored spelling, or None if it is not a DOI.
    arXiv identifiers become their DataCite DOI ``10.48550/arxiv.<id>``."""
    n = normalize_doi(raw)
    if not n:
        return None
    if n.startswith("arxiv:"):
        return "10.48550/arxiv." + n.split(":", 1)[1]
    if re.fullmatch(r"10\.\d{4,9}/\S+", n):
        return n
    return None


_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+?)(?:v\d+)?$")


def arxiv_id_of(doi_key: str) -> str | None:
    m = _ARXIV_DOI.match(doi_key)
    return m.group(1) if m else None


# ── data ──────────────────────────────────────────────────────────────────────

@dataclass
class Hit:
    """What a service returned for one identifier."""
    title: str
    abstract: str          # raw, not yet cleaned


@dataclass
class PaperRef:
    id: str
    title: str
    doi: str | None = None
    key: str | None = None      # normalised DOI used for lookups


@dataclass
class _Outcome:
    ref: PaperRef
    accepted: tuple[str, str] | None = None             # (source, abstract)
    mismatches: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    failed_sources: set[str] = field(default_factory=set)
    state: str = "pending"
    error: str | None = None


class SourceError(Exception):
    """A service could not answer (after retries); the next source takes over."""


# ── HTTP layer ────────────────────────────────────────────────────────────────

def contact_from_env() -> str:
    raw = os.environ.get("ABSTRACT_BACKFILL_CONTACT", "")
    return re.sub(r"[\x00-\x1f\x7f]", "", raw).strip()[:200]


def user_agent(contact: str = "") -> str:
    base = "PaperManager-abstract-backfill/1.0"
    return f"{base} ({contact})" if contact else base


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds or HTTP date), or None."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


def _ssl_verify():
    from services.metadata_lookup import _ssl

    return _ssl()


class Http:
    """Sequential HTTP with a minimum interval per host, retries with exponential backoff and
    Retry-After on 429/503. One request in flight at a time. ``sleep`` and ``clock`` can be
    replaced in tests."""

    def __init__(self, client: httpx.Client | None = None, *, contact: str = "",
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 max_retries: int = MAX_RETRIES, backoff: float = BACKOFF_BASE,
                 max_retry_after: float = MAX_RETRY_AFTER):
        self.contact = contact
        self.sleep, self.clock = sleep, clock
        self.max_retries, self.backoff, self.max_retry_after = max_retries, backoff, max_retry_after
        self._own = client is None
        self.client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT, verify=_ssl_verify(), follow_redirects=True)
        self._last: dict[str, float] = {}
        self.requests = 0

    def close(self) -> None:
        if self._own:
            self.client.close()

    def _wait_turn(self, host: str, interval: float) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)

    def request(self, method: str, url: str, *, interval: float, params: dict | None = None,
                json: dict | None = None, headers: dict | None = None) -> httpx.Response:
        host = httpx.URL(url).host
        hdrs = {"User-Agent": user_agent(self.contact), "Accept": "application/json, application/atom+xml"}
        hdrs.update(headers or {})
        last_problem = "no attempt"
        for attempt in range(self.max_retries + 1):
            self._wait_turn(host, interval)
            delay = self.backoff * (2 ** attempt)
            try:
                self.requests += 1
                r = self.client.request(method, url, params=params, json=json, headers=hdrs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self._last[host] = self.clock()
                last_problem = f"{type(exc).__name__}"
                log.info("abstract backfill: %s %s failed (%s), attempt %d", method, host, last_problem, attempt + 1)
                if attempt < self.max_retries:
                    self.sleep(delay)
                continue
            self._last[host] = self.clock()
            if r.status_code in (429, 500, 502, 503, 504):
                last_problem = f"HTTP {r.status_code}"
                advised = parse_retry_after(r.headers.get("Retry-After"))
                if advised is not None:
                    if advised > self.max_retry_after:
                        raise SourceError(f"{host}: HTTP {r.status_code}, Retry-After {advised:.0f}s is too long")
                    delay = advised
                log.info("abstract backfill: %s answered %d, waiting %.1fs", host, r.status_code, delay)
                if attempt < self.max_retries:
                    self.sleep(delay)
                continue
            return r
        raise SourceError(f"{host}: {last_problem} after {self.max_retries + 1} attempts")


def _json(r: httpx.Response, host: str):
    if r.status_code != 200:
        raise SourceError(f"{host}: HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as exc:
        raise SourceError(f"{host}: invalid JSON") from exc


# ── sources: parsers (pure) ───────────────────────────────────────────────────

def parse_openalex(payload: dict) -> dict[str, Hit]:
    """``/works`` result -> {doi key: Hit}."""
    out: dict[str, Hit] = {}
    for work in (payload or {}).get("results") or []:
        if not isinstance(work, dict):
            continue
        key = doi_for_lookup(work.get("doi"))
        if not key:
            continue
        out[key] = Hit(title=work.get("title") or work.get("display_name") or "",
                       abstract=rebuild_inverted_index(work.get("abstract_inverted_index")))
    return out


def parse_openalex_works(payload: dict) -> list[Hit]:
    """All works of a title search as hits (several per query, no DOI needed)."""
    return [Hit(title=w.get("title") or w.get("display_name") or "",
                abstract=rebuild_inverted_index(w.get("abstract_inverted_index")))
            for w in (payload or {}).get("results") or [] if isinstance(w, dict)]


def parse_s2_batch(keys: list[str], payload: list | None) -> dict[str, Hit]:
    """Batch answer (same order as the request, ``null`` for unknown ids) -> {doi key: Hit}."""
    out: dict[str, Hit] = {}
    if not isinstance(payload, list):
        return out
    for key, item in zip(keys, payload):
        if isinstance(item, dict):
            out[key] = Hit(title=item.get("title") or "", abstract=item.get("abstract") or "")
    return out


_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_ABS = re.compile(r"arxiv\.org/abs/(.+?)(?:v\d+)?$", re.I)


def parse_arxiv_feed(xml_text: str) -> dict[str, Hit]:
    """Atom feed -> {DataCite DOI key: Hit}. An ``Error`` entry (bad id) is skipped."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError("export.arxiv.org: invalid XML") from exc
    out: dict[str, Hit] = {}
    for entry in root.findall(f"{_ATOM}entry"):
        ident = (entry.findtext(f"{_ATOM}id") or "").strip()
        m = _ARXIV_ABS.search(ident)
        title = re.sub(r"\s+", " ", entry.findtext(f"{_ATOM}title") or "").strip()
        if not m or title.lower() == "error":
            continue
        out["10.48550/arxiv." + m.group(1).lower()] = Hit(
            title=title, abstract=entry.findtext(f"{_ATOM}summary") or "")
    return out


def parse_crossref(payload: dict) -> Hit | None:
    msg = (payload or {}).get("message") if isinstance(payload, dict) else None
    if not isinstance(msg, dict):
        return None
    titles = msg.get("title") or []
    from services.metadata_lookup import _strip_jats

    # Crossref abstracts are JATS XML (``<jats:p>``, ``<jats:title>Abstract</jats:title>``).
    raw = _INLINE_TAGS.sub("", _HEADING_TAG.sub(" ", msg.get("abstract") or ""))
    return Hit(title=titles[0] if titles else "", abstract=_strip_jats(raw) or "")


# ── sources: network ──────────────────────────────────────────────────────────

class _Source:
    name = ""
    batch_size = 1
    max_consecutive_failures = 3

    def __init__(self, http: Http):
        self.http = http

    def accepts(self, key: str) -> bool:
        return True

    def fetch(self, keys: list[str]) -> dict[str, Hit]:  # pragma: no cover - interface
        raise NotImplementedError


class OpenAlex(_Source):
    name = "openalex"
    batch_size = OPENALEX_BATCH

    def _mailto(self) -> dict:
        return {"mailto": self.http.contact} if "@" in self.http.contact else {}

    def accepts(self, key: str) -> bool:
        return "," not in key and "|" not in key      # separators of the filter syntax

    def fetch(self, keys: list[str]) -> dict[str, Hit]:
        params = {
            "filter": "doi:" + "|".join(f"https://doi.org/{k}" for k in keys),
            "per-page": str(OPENALEX_BATCH),
            "select": "id,doi,title,abstract_inverted_index,publication_year",
            **self._mailto(),
        }
        r = self.http.request("GET", OPENALEX_URL, interval=INTERVAL_OPENALEX, params=params)
        return parse_openalex(_json(r, "api.openalex.org"))

    def search_title(self, title: str) -> list[Hit]:
        safe = re.sub(r"[,|:]+", " ", title).strip()
        params = {
            "filter": f"title.search:{safe}",
            "per-page": "5",
            "select": "id,doi,title,abstract_inverted_index,publication_year",
            **self._mailto(),
        }
        r = self.http.request("GET", OPENALEX_URL, interval=INTERVAL_OPENALEX, params=params)
        return parse_openalex_works(_json(r, "api.openalex.org"))


class SemanticScholar(_Source):
    name = "semanticscholar"

    def __init__(self, http: Http, api_key: str = ""):
        super().__init__(http)
        self.api_key = api_key.strip()
        self.batch_size = S2_BATCH_KEY if self.api_key else S2_BATCH_ANON
        self.interval = INTERVAL_S2_KEY if self.api_key else INTERVAL_S2_ANON

    def fetch(self, keys: list[str]) -> dict[str, Hit]:
        headers = {"x-api-key": self.api_key} if self.api_key else None
        r = self.http.request(
            "POST", S2_URL, interval=self.interval,
            params={"fields": "title,abstract,externalIds"},
            json={"ids": [f"DOI:{k}" for k in keys]}, headers=headers)
        return parse_s2_batch(keys, _json(r, "api.semanticscholar.org"))


class Arxiv(_Source):
    name = "arxiv"
    batch_size = ARXIV_BATCH

    def accepts(self, key: str) -> bool:
        return arxiv_id_of(key) is not None

    def fetch(self, keys: list[str]) -> dict[str, Hit]:
        ids = [arxiv_id_of(k) for k in keys]
        r = self.http.request(
            "GET", ARXIV_URL, interval=INTERVAL_ARXIV,
            params={"id_list": ",".join(i for i in ids if i), "max_results": str(len(ids))})
        if r.status_code != 200:
            raise SourceError(f"export.arxiv.org: HTTP {r.status_code}")
        return parse_arxiv_feed(r.text)


class Crossref(_Source):
    name = "crossref"
    batch_size = 1
    max_consecutive_failures = 5

    def fetch(self, keys: list[str]) -> dict[str, Hit]:
        key = keys[0]
        params = {"mailto": self.http.contact} if "@" in self.http.contact else None
        r = self.http.request("GET", f"{CROSSREF_URL}/{quote(key, safe='/()')}",
                              interval=INTERVAL_CROSSREF, params=params)
        if r.status_code == 404:
            return {}
        hit = parse_crossref(_json(r, "api.crossref.org"))
        return {key: hit} if hit else {}


def normalise_sources(sources: Iterable[str] | None) -> list[str]:
    """Requested sources in the fixed order; ValueError for an unknown name."""
    if not sources:
        return list(SOURCES)
    wanted = set()
    for s in sources:
        name = SOURCE_ALIASES.get(str(s).strip().lower(), str(s).strip().lower())
        if name not in SOURCES:
            raise ValueError(f"unknown source {s!r}; choose from {', '.join(SOURCES)}")
        wanted.add(name)
    return [s for s in SOURCES if s in wanted]


def _build_sources(names: list[str], http: Http, s2_key: str) -> list[_Source]:
    factory = {"openalex": lambda: OpenAlex(http), "semanticscholar": lambda: SemanticScholar(http, s2_key),
               "arxiv": lambda: Arxiv(http), "crossref": lambda: Crossref(http)}
    return [factory[n]() for n in names]


# ── database ──────────────────────────────────────────────────────────────────

def select_candidates(driver, *, include_stubs: bool = False, limit: int | None = None,
                      with_no_doi_rows: bool = False) -> dict:
    """Papers without an abstract. Returns ``{"candidates": [PaperRef], "candidates_total": n,
    "invalid_doi": n, "no_doi": n, "no_doi_refs": [PaperRef]}``. Candidates have a usable DOI
    (``key`` set) and are in stable id order; ``limit`` cuts the list after that."""
    params = {"include_stubs": bool(include_stubs), "ref_tag": REF_TAG}
    with driver.session() as session:
        rows = [dict(r) for r in session.run(CANDIDATES_QUERY, **params)]
        no_doi_rows = [dict(r) for r in session.run(NO_DOI_QUERY, **params)]
    refs, invalid = [], 0
    for row in rows:
        key = doi_for_lookup(row.get("doi"))
        if key is None:
            invalid += 1
            continue
        refs.append(PaperRef(id=row["id"], title=row.get("title") or "", doi=row.get("doi"), key=key))
    total = len(refs)
    if limit is not None and limit >= 0:
        refs = refs[:limit]
    no_doi_refs = [PaperRef(id=r["id"], title=r.get("title") or "") for r in no_doi_rows] if with_no_doi_rows else []
    return {"candidates": refs, "candidates_total": total, "invalid_doi": invalid,
            "no_doi": len(no_doi_rows), "no_doi_refs": no_doi_refs}


def write_abstract(driver, paper_id: str, abstract: str, source: str, now: str) -> bool:
    """Set the abstract only if the paper still has none. True if a row changed.

    ``updated_at`` is deliberately left alone: the library's "recently updated" sort reads it,
    and a backfill of hundreds of papers would push them all to the top."""
    with driver.session() as session:
        rows = list(session.run(WRITE_QUERY, id=paper_id, abstract=abstract, source=source, now=now))
    return len(rows) > 0


# ── the run ───────────────────────────────────────────────────────────────────

def _evaluate(outcome: _Outcome, source: str, hit: Hit, *, strict: bool = False) -> None:
    """Apply the safety checks to one hit; record why it was refused or accept it."""
    if outcome.accepted:
        return
    text = clean_abstract(hit.abstract)
    if not text:
        return                                   # this service has no abstract: not a refusal
    if not titles_match(outcome.ref.title, hit.title, strict=strict):
        outcome.mismatches.append({"source": source, "library_title": outcome.ref.title,
                                   "returned_title": hit.title})
        return
    problem = quality_problem(text, outcome.ref.title)
    if problem:
        outcome.rejections.append({"source": source, "reason": problem})
        return
    outcome.accepted = (source, text)


def _final_state(o: _Outcome, dry_run: bool) -> str:
    if o.state in ("applied", "skipped_has_abstract", "error"):
        return o.state
    if o.accepted:
        return "would_apply" if dry_run else o.state
    if o.mismatches:
        return "title_mismatch"
    if o.rejections:
        return "rejected_quality"
    return "no_abstract_found"


def run_backfill(driver, *, dry_run: bool = True, limit: int | None = None,
                 include_stubs: bool = False, sources: Iterable[str] | None = None,
                 title_search: bool = False, http: Http | None = None,
                 contact: str | None = None, s2_api_key: str | None = None,
                 now: Callable[[], datetime] | None = None) -> dict:
    """Find papers without an abstract and fill them from open services. Returns the report.

    ``dry_run`` (default) reads and queries the services but writes nothing. Never raises for a
    failing service: the error is recorded and the next source takes over. ``ValueError`` only
    for an unknown source name."""
    names = normalise_sources(sources)
    if contact is None:
        contact = contact_from_env()
    if s2_api_key is None:
        from config import settings

        s2_api_key = settings.semantic_scholar_api_key or ""
    clock_now = now or (lambda: datetime.now(timezone.utc))
    started = clock_now()
    own_http = http is None
    http = http or Http(contact=contact)
    if not own_http and not http.contact:
        http.contact = contact

    report: dict = {
        "dry_run": bool(dry_run), "started_at": started.isoformat(),
        "options": {"limit": limit, "include_stubs": bool(include_stubs), "sources": names,
                    "title_search": bool(title_search)},
        "counts": {}, "per_source": {n: {"requests": 0, "found": 0, "accepted": 0, "errors": 0,
                                         "disabled": False} for n in names},
        "errors": [], "papers": [],
    }
    errors: list[dict] = report["errors"]
    per_source = report["per_source"]
    outcomes: dict[str, _Outcome] = {}
    by_key: dict[str, list[PaperRef]] = {}
    error_total = 0

    def note_error(source: str, message: str) -> None:
        nonlocal error_total
        error_total += 1
        per_source[source]["errors"] += 1
        log.warning("abstract backfill: %s: %s", source, message)
        if len(errors) < MAX_ERRORS_LISTED:
            errors.append({"source": source, "message": message[:300]})

    def mark_failed(source: str, keys: list[str]) -> None:
        for k in keys:
            for p in by_key[k]:
                outcomes[p.id].failed_sources.add(source)

    def persist(o: _Outcome, source: str, text: str) -> None:
        if dry_run:
            return
        try:
            if write_abstract(driver, o.ref.id, text, source, clock_now().isoformat()):
                o.state = "applied"
            else:
                o.state = "skipped_has_abstract"      # an abstract appeared since the selection
        except Exception as exc:  # noqa: BLE001 - one failed write must not stop the batch
            o.state, o.error = "error", f"{type(exc).__name__}: {exc}"[:300]
            note_error(source, f"write failed for {o.ref.id}: {o.error}")

    try:
        sel = select_candidates(driver, include_stubs=include_stubs, limit=limit,
                                with_no_doi_rows=title_search)
    except Exception as exc:  # noqa: BLE001
        report["counts"] = {"errors": 1}
        report["errors"].append({"source": "database", "message": f"{type(exc).__name__}: {exc}"[:300]})
        report["finished_at"] = clock_now().isoformat()
        if own_http:
            http.close()
        return report

    refs: list[PaperRef] = sel["candidates"]
    for ref in refs:
        outcomes[ref.id] = _Outcome(ref)
        by_key.setdefault(ref.key, []).append(ref)

    srcs = _build_sources(names, http, s2_api_key)
    try:
        for src in srcs:
            stats = per_source[src.name]
            pending = [k for k, papers in by_key.items()
                       if any(not outcomes[p.id].accepted for p in papers) and src.accepts(k)]
            if not pending:
                continue
            batches = [pending[i:i + src.batch_size] for i in range(0, len(pending), src.batch_size)]
            consecutive = 0
            for bi, batch in enumerate(batches):
                if consecutive >= src.max_consecutive_failures:
                    stats["disabled"] = True
                    log.warning("abstract backfill: %s switched off after %d failures", src.name, consecutive)
                    break
                try:
                    stats["requests"] += 1
                    hits = src.fetch(batch)
                    consecutive = 0
                except Exception as exc:  # noqa: BLE001 - SourceError, or a parser bug: never stop the run
                    consecutive += 1
                    note_error(src.name, str(exc) if isinstance(exc, SourceError)
                               else f"{type(exc).__name__}: {exc}")
                    mark_failed(src.name, batch)
                    continue
                for k in batch:
                    hit = hits.get(k)
                    if hit is None:
                        continue
                    stats["found"] += 1
                    for p in by_key[k]:
                        o = outcomes[p.id]
                        if o.accepted:
                            continue
                        _evaluate(o, src.name, hit)
                        if o.accepted:
                            stats["accepted"] += 1
                            persist(o, *o.accepted)
            else:
                continue
            for batch in batches[bi:]:                 # skipped by the break above
                mark_failed(src.name, batch)

        if title_search and "openalex" in names:
            _title_search_pass(srcs, sel, limit, len(refs), outcomes, report, note_error, persist)
    finally:
        if own_http:
            http.close()

    _finish(report, outcomes, sel, dry_run, error_total, clock_now)
    return report


def _title_search_pass(srcs, sel, limit, used, outcomes, report, note_error, persist) -> None:
    """Papers without a DOI: ask OpenAlex by title, accept only a near-identical title."""
    oa = next((s for s in srcs if isinstance(s, OpenAlex)), None)
    if oa is None:
        return
    room = None if limit is None else max(0, limit - used)
    stats = report["per_source"]["openalex"]
    consecutive = 0
    for ref in sel["no_doi_refs"][:room]:
        o = outcomes[ref.id] = _Outcome(ref)
        if len(_norm_title(ref.title)) < 15:
            continue                                   # too short to identify a paper
        if consecutive >= 5:
            stats["disabled"] = True
            break
        try:
            stats["requests"] += 1
            hits = oa.search_title(ref.title)
            consecutive = 0
        except SourceError as exc:
            consecutive += 1
            note_error("openalex", str(exc))
            o.failed_sources.add("openalex")
            continue
        usable = [h for h in hits if clean_abstract(h.abstract) and titles_match(ref.title, h.title, strict=True)]
        if len({clean_abstract(h.abstract) for h in usable}) != 1:
            if usable:                                 # several different abstracts: ambiguous
                o.rejections.append({"source": "openalex", "reason": "ambiguous_title"})
            continue
        stats["found"] += 1
        _evaluate(o, "openalex", usable[0], strict=True)
        if o.accepted:
            stats["accepted"] += 1
            persist(o, *o.accepted)


def _finish(report: dict, outcomes: dict[str, _Outcome], sel: dict, dry_run: bool,
            error_total: int, clock_now) -> None:
    states: dict[str, int] = {}
    accepted_by_source: dict[str, int] = {}
    papers = []
    for pid, o in outcomes.items():
        state = _final_state(o, dry_run)
        o.state = state
        states[state] = states.get(state, 0) + 1
        entry: dict = {"id": pid, "outcome": state}
        if o.accepted:
            src, text = o.accepted
            entry.update(source=src, abstract_length=len(text),
                         abstract_sha1=hashlib.sha1(text.encode("utf-8")).hexdigest())
            if state in ("applied", "would_apply"):
                accepted_by_source[src] = accepted_by_source.get(src, 0) + 1
        if o.mismatches:
            entry["title_mismatch"] = o.mismatches
        if o.rejections:
            entry["rejected"] = o.rejections
        if o.failed_sources:
            entry["failed_sources"] = sorted(o.failed_sources)
        if o.error:
            entry["error"] = o.error
        papers.append(entry)
    key = "would_apply" if dry_run else "applied"
    incomplete = sum(1 for o in outcomes.values() if o.state == "no_abstract_found" and o.failed_sources)
    report["counts"] = {
        "candidates": len(sel["candidates"]), "candidates_total": sel["candidates_total"],
        key: states.get(key, 0), "no_abstract_found": states.get("no_abstract_found", 0),
        "title_mismatch": states.get("title_mismatch", 0),
        "rejected_quality": states.get("rejected_quality", 0),
        "skipped_has_abstract": states.get("skipped_has_abstract", 0),
        "no_doi": sel["no_doi"], "invalid_doi": sel["invalid_doi"],
        "incomplete_lookup": incomplete, "errors": error_total,
    }
    report["accepted_by_source"] = accepted_by_source
    report["papers"] = papers
    report["finished_at"] = clock_now().isoformat()


def summarize_for_api(report: dict, max_samples: int = 50) -> dict:
    """The report without per-paper detail or titles: counts, per-source stats, error messages
    and at most ``max_samples`` paper ids, taken in turn from each outcome."""
    by_outcome: dict[str, list[str]] = {}
    for p in report.get("papers", []):
        by_outcome.setdefault(p["outcome"], []).append(p["id"])
    names = sorted(by_outcome)
    queues = [list(by_outcome[n]) for n in names]
    samples: list[dict] = []
    while len(samples) < max_samples and any(queues):
        for name, q in zip(names, queues):
            if q and len(samples) < max_samples:
                samples.append({"id": q.pop(0), "outcome": name})
    return {k: report[k] for k in ("dry_run", "started_at", "finished_at", "options", "counts",
                                   "per_source", "accepted_by_source", "errors") if k in report} | {
        "sample_ids": samples}


# ── undo ──────────────────────────────────────────────────────────────────────

def undo_report(driver, report: dict, *, dry_run: bool = True) -> dict:
    """Remove the abstracts a previous apply report lists, and only those: the paper's
    ``abstract_source`` must equal the report's source and its abstract must still be the text
    that was written (compared by SHA-1), so an abstract a user wrote or edited since stays.
    ``dry_run`` counts what would be cleared."""
    out = {"dry_run": bool(dry_run), "listed": 0, "cleared": 0, "would_clear": 0,
           "skipped_source_mismatch": 0, "skipped_text_changed": 0, "not_found": 0, "errors": 0}
    for entry in report.get("papers", []):
        if entry.get("outcome") != "applied" or not entry.get("source"):
            continue
        out["listed"] += 1
        try:
            with driver.session() as session:
                row = session.run(UNDO_READ_QUERY, id=entry["id"]).single()
            if row is None:
                out["not_found"] += 1
                continue
            if row["source"] != entry["source"]:
                out["skipped_source_mismatch"] += 1
                continue
            current = row["abstract"] or ""
            if entry.get("abstract_sha1") and hashlib.sha1(current.encode("utf-8")).hexdigest() != entry["abstract_sha1"]:
                out["skipped_text_changed"] += 1
                continue
            if dry_run:
                out["would_clear"] += 1
                continue
            with driver.session() as session:
                changed = list(session.run(UNDO_WRITE_QUERY, id=entry["id"], source=entry["source"], abstract=current))
            if changed:
                out["cleared"] += 1
            else:
                out["skipped_text_changed"] += 1
        except Exception as exc:  # noqa: BLE001
            out["errors"] += 1
            log.warning("abstract backfill undo: %s: %s", entry.get("id"), exc)
    return out
