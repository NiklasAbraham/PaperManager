"""Where new papers come from: arXiv and bioRxiv / medRxiv.

Each fetcher returns ``(candidates, error)``. A source that fails part-way returns what it
got and a short error; it never raises, so one broken source cannot stop the other or the
backend. Requests carry ``PaperManager-feed`` (plus ``PAPER_FEED_CONTACT`` if set) as the
User-Agent. arXiv asks for at most one request every three seconds; that is enforced here.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from urllib.parse import quote

import httpx

from services.feed import config
from services.feed.store import Candidate

log = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
BIORXIV_API = "https://api.biorxiv.org/details"
ARXIV_MIN_GAP = 3.0
PAGE = 100
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

_sleep = time.sleep          # replaced in tests
_clock = time.monotonic
_in_flight = threading.Lock()    # one arXiv request at a time, process-wide
_last_arxiv_request = 0.0


class SourceError(Exception):
    pass


def _ssl_verify():
    from services.metadata_from_url import _ssl_verify as verify
    return verify()


class RateLimited(SourceError):
    """The server kept answering 429 (or asked for a wait longer than we are willing to give)."""


# Waits before the next try: network errors and 5xx are usually brief, a 429 needs real patience.
RETRY_5XX = (5.0, 10.0)
RETRY_429 = (30.0, 60.0, 120.0)
MAX_RETRY_AFTER = 300.0
ARXIV_TIMEOUT = httpx.Timeout(90.0, connect=15.0)    # arXiv's API can take a minute to answer


def _retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header (a number or an HTTP date), None when absent or unreadable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _http_get(url: str, params: dict | None = None, *, timeout: float | httpx.Timeout = 30.0,
              retries: int = 3, backoff: float = 5.0, rate_delays: tuple[float, ...] = RETRY_429) -> httpx.Response:
    """GET with retries. Network errors and 5xx: up to ``retries`` tries, waiting ``backoff`` and
    doubling. 429: waits for the Retry-After header when there is one, otherwise ``rate_delays``
    (30, 60, 120 s), then gives up. Raises ``SourceError`` (``RateLimited`` for 429)."""
    delay = backoff
    failures = rate_hits = 0
    while True:
        try:
            r = httpx.get(url, params=params, headers={"User-Agent": config.user_agent()},
                          timeout=timeout, verify=_ssl_verify(), follow_redirects=True)
            if r.status_code == 429:
                raise RateLimited("HTTP 429", _retry_after(r.headers.get("Retry-After")))
            if r.status_code in (500, 502, 503, 504):
                raise SourceError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except RateLimited as exc:
            asked = exc.args[1] if len(exc.args) > 1 else None
            if rate_hits >= len(rate_delays) or (asked is not None and asked > MAX_RETRY_AFTER):
                raise RateLimited("HTTP 429 (rate limited)") from None
            wait = rate_delays[rate_hits] if asked is None else asked
            rate_hits += 1
            log.warning("Feed request rate limited (%d/%d), waiting %.0f s", rate_hits, len(rate_delays), wait)
            _sleep(wait)
        except (httpx.HTTPError, SourceError) as exc:
            failures += 1
            if failures >= retries:
                raise SourceError(f"{type(exc).__name__}: {exc}") from exc
            log.warning("Feed request failed (attempt %d/%d): %s", failures, retries, exc)
            _sleep(delay)
            delay *= 2


def _arxiv_get(url: str, params: dict | None = None) -> httpx.Response:
    return _http_get(url, params, timeout=ARXIV_TIMEOUT)


def _wait_for_arxiv() -> None:
    """Block until three seconds have passed since the previous arXiv request ended."""
    wait = ARXIV_MIN_GAP - (_clock() - _last_arxiv_request)
    if wait > 0:
        _sleep(wait)


def _mark_arxiv_request() -> None:
    global _last_arxiv_request
    _last_arxiv_request = _clock()


def is_rate_limited(error: str | None) -> bool:
    return bool(error) and "HTTP 429" in error


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ── arXiv ─────────────────────────────────────────────────────────────────────

def parse_arxiv(xml_text: str | bytes) -> list[Candidate]:
    """Candidates of one Atom response page, in feed order. Entries without id or title are skipped."""
    root = ET.fromstring(xml_text)
    out: list[Candidate] = []
    for entry in root.findall("atom:entry", _NS):
        id_el, title_el = entry.find("atom:id", _NS), entry.find("atom:title", _NS)
        if id_el is None or title_el is None or not (id_el.text or "").strip():
            continue
        m = re.search(r"/abs/(.+?)(?:v\d+)?$", id_el.text.strip())
        title = _squash(title_el.text)
        if not m or not title:
            continue
        ext_id = m.group(1)
        pub = (entry.findtext("atom:published", default="", namespaces=_NS) or "").strip()
        doi = None
        for link in entry.findall("atom:link", _NS):
            if link.get("title") == "doi":
                doi = (link.get("href") or "").replace("https://doi.org/", "").replace("http://dx.doi.org/", "") or None
        out.append(Candidate(
            id=f"arxiv:{ext_id}", source="arxiv", ext_id=ext_id, title=title,
            authors=[_squash(a.findtext("atom:name", default="", namespaces=_NS))
                     for a in entry.findall("atom:author", _NS)],
            abstract=_squash(entry.findtext("atom:summary", default="", namespaces=_NS)),
            published=pub, url=f"https://arxiv.org/abs/{ext_id}", doi=doi,
            categories=[c.get("term") for c in entry.findall("atom:category", _NS) if c.get("term")],
        ))
    return out


def fetch_arxiv(categories: list[str], since: datetime, max_results: int | None = None,
                get=None) -> tuple[list[Candidate], str | None]:
    """Papers of the given categories submitted at or after ``since`` (UTC), newest first
    per category, at most ``max_results`` in total (``PAPER_FEED_MAX_PER_REFRESH``)."""
    cap = max_results or config.max_per_refresh()
    get = get or _arxiv_get
    seen: dict[str, Candidate] = {}
    errors: list[str] = []
    for cat in categories:
        start = 0
        while len(seen) < cap:
            try:
                with _in_flight:
                    _wait_for_arxiv()
                    try:
                        r = get(ARXIV_API, {"search_query": f"cat:{cat}", "start": start, "max_results": PAGE,
                                            "sortBy": "submittedDate", "sortOrder": "descending"})
                    finally:
                        _mark_arxiv_request()
                page = parse_arxiv(r.content)
            except (SourceError, ET.ParseError) as exc:
                errors.append(f"arxiv {cat}: {exc}")
                break
            if not page:
                break
            reached_old = False
            for c in page:
                if c.published and _parse_ts(c.published) < since:
                    reached_old = True
                    continue
                seen.setdefault(c.id, c)
            if reached_old or len(page) < PAGE:
                break
            start += PAGE
    return list(seen.values())[:cap], ("; ".join(errors)[:500] or None)


def _parse_ts(value: str) -> datetime:
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── bioRxiv / medRxiv ─────────────────────────────────────────────────────────

def parse_biorxiv(data: dict, server: str) -> list[Candidate]:
    """First versions in one page of the details API. Later versions of old papers are
    skipped: they are not new."""
    host = "www.medrxiv.org" if server == "medrxiv" else "www.biorxiv.org"
    out: list[Candidate] = []
    for item in data.get("collection") or []:
        doi, title = (item.get("doi") or "").strip(), _squash(item.get("title"))
        if not doi or not title or str(item.get("version", "1")) != "1":
            continue
        authors = [a.strip() for a in (item.get("authors") or "").split(";") if a.strip()]
        out.append(Candidate(
            id=f"{server}:{doi}", source=server, ext_id=doi, title=title, authors=authors,
            abstract=_squash(item.get("abstract")), published=f"{item.get('date', '')}T00:00:00+00:00"
            if item.get("date") else "", url=f"https://{host}/content/{quote(doi, safe='/')}v1",
            doi=doi, categories=[item["category"]] if item.get("category") else [],
        ))
    return out


def fetch_biorxiv(server: str, since: date, until: date, max_results: int | None = None,
                  get=None) -> tuple[list[Candidate], str | None]:
    """First versions posted between ``since`` and ``until`` (inclusive) on ``biorxiv`` or ``medrxiv``."""
    if server not in ("biorxiv", "medrxiv"):
        return [], f"unknown server {server}"
    cap = max_results or config.max_per_refresh()
    get = get or _http_get
    seen: dict[str, Candidate] = {}
    cursor = 0
    while len(seen) < cap:
        try:
            r = get(f"{BIORXIV_API}/{server}/{since.isoformat()}/{until.isoformat()}/{cursor}", None)
            data = r.json()
        except (SourceError, ValueError) as exc:
            return list(seen.values())[:cap], f"{server}: {exc}"[:500]
        coll = data.get("collection") or []
        for c in parse_biorxiv(data, server):
            seen.setdefault(c.id, c)
        msg = (data.get("messages") or [{}])[0]
        try:
            total = int(msg.get("total", 0))
        except (TypeError, ValueError):
            total = 0
        cursor += len(coll)
        if not coll or cursor >= total:
            break
        _sleep(0.5)
    return list(seen.values())[:cap], None
