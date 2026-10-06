"""Reference-list extraction for a paper.

Three sources, combined in ``extract_references``:

A. Semantic Scholar references API (needs a DOI or arXiv ID). Structured and
   complete when the paper is indexed, but rate-limited, and empty or partial
   for very recent preprints and for publishers that elide their reference
   lists.
B. LLM over the reference section, chunked so every entry is seen and each
   call finishes inside its timeout.
C. Deterministic parser over the reference section. Handles numbered lists
   ([1], 1., 1) and unnumbered author-year bibliographies (ICLR, NeurIPS, APA).

The parser also serves as the yardstick: a source whose count falls far below
what the parser sees in the text is treated as incomplete, and the next source
is tried.
"""
import re
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from services.pdf_parser import DOI_RE, ARXIV_RE, YEAR_RE
from config import settings
from services.user_ai_config import get_effective_ai_config

log = logging.getLogger(__name__)

_SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_REF_FIELDS = "title,authors,year,externalIds"
_S2_PAGE_SIZE = 1000          # API maximum per page
_S2_MAX_REFS = 3000           # safety cap for books / reviews
_S2_RETRY_DELAYS = (1.5, 3.0, 6.0, 12.0)

# LLM chunking: small enough that one chunk's JSON comes back well inside the timeout.
_AI_CHUNK_CHARS = 6000
_AI_MAX_SECTION_CHARS = 120_000
_AI_TIMEOUT = 120.0
_AI_WORKERS = 4

# A source is accepted when it reaches this fraction of the parser's count.
_COMPLETE_FRACTION = 0.8

_HEADER_WORDS = r"(?i:references(?:\s+and\s+notes)?|bibliography|works\s+cited|literature\s+cited|cited\s+literature|references\s+cited)"
# Header line: optional markdown hashes, optional section number ("7", "7.", "VII."), the word,
# then optionally a slide counter ("References XI") or a glued bioRxiv line number ("References515").
_SECTION_RE = re.compile(
    rf"(?:^|\n)[ \t]*(?:#+[ \t]*)?(?:(?:\d{{1,2}}|[IVX]{{1,5}})\.?[ \t]+)?\**{_HEADER_WORDS}\**"
    r"(?:[ \t]+[IVXL]{1,6}|[ \t]*\d{1,4})?[ \t]*:?[ \t]*(?=\r?\n)"
)
_BROAD_SECTION_RE = re.compile(
    r"\n\s*(?:#+\s*)?(?:references|bibliography|works\s+cited|literature|further\s+reading)\s*\n",
    re.IGNORECASE,
)
# Headings that end a reference list: appendices, supplementary material, and the
# back-matter blocks that follow the main reference list in Nature-style papers.
_SECTION_END_RE = re.compile(
    r"\n[ \t]*(?:#+[ \t]*)?(?:"
    r"(?:[A-H](?:\.\d+)?\.?[ \t]+)?(?i:appendix|appendices|supplementary\s+(?:material|information|materials|methods)|supplemental\s+material)\b[^\n]{0,80}"
    r"|(?i:methods|online\s+methods|acknowledge?ments?|online\s+content|author\s+contributions|data\s+availability|code\s+availability"
    r"|competing\s+interests|additional\s+information|reporting\s+summary|extended\s+data|neurips\s+paper\s+checklist|checklist)[ \t]*\d{0,4}"
    r"|[A-H](?:\.\d+)?\.?[ \t]+[A-Z][A-Z \-:]{6,80}"          # "F ADDITIONAL TABLES", all-caps lettered heading
    r")[ \t]*(?=\r?\n)"
)
_LETTERED_HEADING_RE = re.compile(r"^[A-H](?:\.\d+)?\.?\s+[A-Z][A-Z \-:]{6,80}$")
# With no header at all, a numbered list in the document tail only counts if it is this long.
_HEADERLESS_MIN_ENTRIES = 10

# Numbered-entry markers: [12]  12.  (12)  12 Author
_NUM_MARKER_RE = re.compile(r"^(?:\[(\d{1,4})\]|\((\d{1,4})\)|(\d{1,3})\.(?=\s)|(\d{1,3})(?=\s+[A-Z]))\s*")
_YEAR_ANY_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}[a-z]?(?!\d)")
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+|doi:\s*\S+", re.IGNORECASE)
# An author list usually opens the line: "Smith, J.", "J. Smith", "Smith J", "van der Berg, A.", "Albergo and ..."
_AUTHOR_START_RE = re.compile(
    r"^(?:(?:van|von|de|der|den|di|da|du|le|la|del|dos|ten|ter)\s+)*"
    r"(?:[A-Z][A-Za-z'’`´¨\-]+|[A-Z]\.(?:\s?[A-Z]\.)*)"
    r"(?:,|\s+[A-Z]|\s+and\s|\s+&|\s*$)"
)
_CONTINUATION_WORDS = {
    "in", "and", "proceedings", "advances", "journal", "url", "doi", "arxiv", "preprint",
    "conference", "international", "transactions", "pp", "vol", "volume", "ieee", "acm",
    "nature", "science", "cell", "springer", "the", "on", "of", "for", "available",
    "retrieved", "accessed", "editors", "eds", "press", "university", "openreview",
}
# Sentence boundary: a period after a token of 2+ chars (so "J." initials do not split),
# after a lone digit ("alphafold 3. Nature"), or ?/!.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[^\s.]{2})\.\s+|(?<=\s\d)\.\s+|(?<=[?!])\s+")
# An initial followed by a title: capitalised word then a lowercase word ("H. Catalyzing the",
# "L. A survey of"), but not a further author ("P. Kingma and M. Welling").
_INITIAL_TITLE_BOUNDARY_RE = re.compile(
    r"(?<=\b[A-Z]\.)\s+(?=(?:[A-Z][\w\-’']*|[A-Z])\s+(?:[a-z]|[A-Z][a-z]+\s+[a-z]))(?![A-Z][\w\-’']*\s+(?:and|et|&)\b)"
)
_INITIALS_RE =re.compile(r"^(?:[A-Z]\.?\s*-?\s*)+$")
_TITLE_QUOTED_RE = re.compile(r'["“”„]([^"“”„]{8,300})["“”„]')


# ── Semantic Scholar ───────────────────────────────────────────────────────────

def _s2_paper_id(doi: str) -> str:
    """Normalise a DOI/arXiv string into a form the S2 API accepts in a URL path.

    10.48550/arXiv.2604.05181 → ArXiv:2604.05181 (avoids unencoded '/' in path)
    arXiv:2604.05181          → ArXiv:2604.05181 (capitalise prefix for clarity)
    everything else            → DOI:<doi>
    """
    doi = doi.strip()
    m = re.match(r"10\.48550/arXiv\.(\d{4}\.\d{4,5})", doi, re.I)
    if m:
        return f"ArXiv:{m.group(1)}"
    if doi.lower().startswith("arxiv:"):
        return f"ArXiv:{doi[6:].strip()}"
    if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", doi):
        return f"ArXiv:{doi}"
    if doi.startswith("10."):
        return f"DOI:{doi}"
    return doi


def _s2_get(url: str, params: dict) -> httpx.Response | None:
    """GET with retries on 429 / 5xx / network errors. Returns None when all attempts fail."""
    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    for attempt, delay in enumerate((0.0, *_S2_RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            r = httpx.get(url, params=params, headers=headers, timeout=20)
        except httpx.HTTPError as exc:
            log.debug("S2 request error (attempt %d): %s", attempt + 1, exc)
            continue
        if r.status_code == 200:
            return r
        if r.status_code == 429 or r.status_code >= 500:
            retry_after = r.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                time.sleep(min(int(retry_after), 30))
            log.debug("S2 %d (attempt %d) | %s", r.status_code, attempt + 1, url)
            continue
        log.debug("S2 %d, not retrying | %s", r.status_code, url)
        return None
    log.warning("S2 references unavailable after %d attempts | %s", len(_S2_RETRY_DELAYS) + 1, url)
    return None


def _fetch_s2_references(doi: str) -> list[dict] | None:
    """Fetch structured references from Semantic Scholar, all pages. Returns None on failure."""
    try:
        url = f"{_SS_BASE}/{_s2_paper_id(doi)}/references"
        results: list[dict] = []
        offset = 0
        while offset < _S2_MAX_REFS:
            r = _s2_get(url, {"fields": _REF_FIELDS, "limit": _S2_PAGE_SIZE, "offset": offset})
            if r is None:
                break
            data = r.json()
            for item in data.get("data") or []:
                cited = item.get("citedPaper") or {}
                title = (cited.get("title") or "").strip()
                if not title:
                    continue
                ext = cited.get("externalIds") or {}
                results.append({
                    "title": title,
                    "authors": [a.get("name", "") for a in (cited.get("authors") or []) if a.get("name")],
                    "year": cited.get("year"),
                    "doi": ext.get("DOI"),
                    "arxiv_id": ext.get("ArXiv"),
                })
            nxt = data.get("next")
            if not nxt:
                break
            offset = nxt
        return results or None
    except Exception:
        log.debug("S2 references failed", exc_info=True)
        return None


# ── Reference section ─────────────────────────────────────────────────────────

def _trim_section_end(section: str) -> str:
    """Cut the reference section at the first appendix / supplementary heading."""
    # Skip the first few hundred chars so a heading right after "References" can't empty it.
    m = _SECTION_END_RE.search(section, pos=min(200, len(section)))
    return section[:m.start()] if m else section


def _get_ref_sections(raw_text: str) -> list[str]:
    """Every reference section in the document, in order.

    Nature papers carry a main list and a Methods list; preprints often add an
    appendix list; books have one per chapter. Each section runs from its header to
    the next header or the first back-matter / appendix heading, whichever is first.
    """
    headers = list(_SECTION_RE.finditer(raw_text)) or list(_BROAD_SECTION_RE.finditer(raw_text))
    sections = []
    for i, m in enumerate(headers):
        stop = headers[i + 1].start() if i + 1 < len(headers) else len(raw_text)
        sec = _trim_section_end(raw_text[m.end():stop])
        if sec.strip():
            sections.append(sec)
    return sections


def _get_ref_section_text(raw_text: str) -> str | None:
    """Return the text of all reference sections joined, or None if there is no text.

    Without any header, falls back to the final 20% of the document.
    """
    sections = _get_ref_sections(raw_text)
    if sections:
        return "\n\n".join(sections)
    cutoff = max(0, int(len(raw_text) * 0.8))
    tail = raw_text[cutoff:]
    return tail if tail.strip() else None


# ── Deterministic parser ──────────────────────────────────────────────────────

def _clean_lines(section: str) -> list[str]:
    """Strip page numbers, running headers and bullets; keep one string per line."""
    lines = [re.sub(r"^[-*•]\s+", "", ln.strip()) for ln in section.splitlines()]
    # Letter-spaced justified lines: "1 2 . W u ,Z ." → "12. W u ,Z ."
    lines = [re.sub(r"^(\d) (\d)(?: (\d))? ?\.(?=\s)", lambda m: "".join(g or "" for g in m.groups()) + ".", s)
             for s in lines]
    counts: dict[str, int] = {}
    for s in lines:
        if len(s) > 15:
            counts[s] = counts.get(s, 0) + 1
    out = []
    for s in lines:
        if not s or re.fullmatch(r"\d{1,4}", s):            # blank / page number
            continue
        if _LETTERED_HEADING_RE.match(s):
            continue
        if counts.get(s, 0) >= 3:                           # running page header
            continue
        out.append(s)
    return out


def _join(entry_lines: list[str]) -> str:
    """Join wrapped lines, undoing end-of-line hyphenation."""
    text = ""
    for ln in entry_lines:
        if text.endswith("-") and ln[:1].islower():
            text = text[:-1] + ln
        elif text:
            text += " " + ln
        else:
            text = ln
    return re.sub(r"\s+", " ", text).strip()


def _marker_number(line: str) -> int | None:
    m = _NUM_MARKER_RE.match(line)
    if not m:
        return None
    return int(next(g for g in m.groups() if g is not None))


def _split_numbered(lines: list[str], anchored: bool = True) -> list[str] | None:
    """Split on the longest run of sequential numeric markers (1, 2, 3, ...).

    Lines with out-of-sequence numbers ("2021.", page numbers, appendix lists)
    stay continuation lines. ``anchored`` requires the run to open within the
    first lines, so a numbered list later in the text cannot take over an
    author-year bibliography. None if the list is not numbered.
    """
    candidates = [(i, n) for i, ln in enumerate(lines) if (n := _marker_number(ln)) is not None]
    best: list[int] = []
    used: set[int] = set()
    for start, (i0, n0) in enumerate(candidates):
        # Anchored: the run opens in the first lines and may start at any number (a
        # Methods list continues from the main list). Unanchored: it must start at 1-2.
        if (anchored and i0 > 3) or (not anchored and n0 > 2) or i0 in used:
            continue
        chain, expected, last = [i0], n0 + 1, i0
        for i, n in candidates[start + 1:]:
            if i - last > 25:          # entries don't run this long: the list has ended
                break
            if n == expected:
                chain.append(i)
                expected, last = n + 1, i
        used.update(chain)
        if len(chain) > len(best):
            best = chain
    if len(best) < 3:
        return None
    entries = []
    for k, i in enumerate(best):
        stop = best[k + 1] if k + 1 < len(best) else min(len(lines), i + 6)
        entries.append(_join([_NUM_MARKER_RE.sub("", lines[i], count=1)] + lines[i + 1:stop]))
    return entries


def _split_labelled(lines: list[str]) -> list[str] | None:
    """Split on alphanumeric labels: "[ACDE12] ...", "[Adhikari et al., 2021] ..."."""
    starts = [i for i, ln in enumerate(lines) if ln.startswith("[") and re.match(r"^\[[^\]]*[A-Za-z]", ln)]
    if len(starts) < 3 or starts[0] > 3:
        return None
    entries = []
    for k, i in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else min(len(lines), i + 6)
        text = _join(lines[i:stop])
        text = re.sub(r"^\[[^\]]{1,120}\]\s*", "", text)   # label may wrap over two lines
        entries.append(text)
    return entries


def _looks_like_entry_start(line: str) -> bool:
    first = re.split(r"[\s,.]", line, maxsplit=1)[0]
    if first.lower() in _CONTINUATION_WORDS or re.match(r"In[A-Z]", first):   # "InProceedings" (lost space)
        return False
    return bool(_AUTHOR_START_RE.match(line))


def _split_author_year(lines: list[str]) -> list[str]:
    """Split an unnumbered bibliography: a new entry starts on an author-like line
    once the current entry is complete."""
    entries: list[list[str]] = []
    has_year = False              # does the current entry carry a year yet?
    for ln in lines:
        ln = re.sub(r"^\d{1,4}\s+(?=[A-Z][a-z])", "", ln)   # page number glued to the next line
        if entries and has_year and _ends_entry(entries[-1][-1]) and _looks_like_entry_start(ln):
            entries.append([ln])
            has_year = bool(_YEAR_ANY_RE.search(ln))
            continue
        if entries:
            entries[-1].append(ln)
        else:
            entries.append([ln])
        has_year = has_year or bool(_YEAR_ANY_RE.search(ln))
    return [_join(e) for e in entries]


def _ends_entry(line: str) -> bool:
    tail = line.rstrip()
    if tail.endswith((".", ")", "]")) or re.search(r"(?:19|20)\d{2}[a-z]?$", tail):
        return True
    # hyperref back-references after the entry: "...2017. 6, 25, 50" or a line "29, 50"
    stripped = re.sub(r"[\s,\d]+$", "", tail)
    return stripped == "" or stripped.endswith((".", ")", "]"))


def _split_entries(section: str) -> list[str]:
    lines = _clean_lines(section)
    if not lines:
        return []
    numbered = _split_numbered(lines)
    if numbered is not None:
        return numbered
    labelled = _split_labelled(lines)
    if labelled is not None:
        return labelled
    return _split_author_year(lines)


_NAME_PARTICLES = {"and", "et", "al", "al.", "van", "von", "de", "der", "den", "di", "da", "du", "le", "la", "del", "dos"}


def _is_author_segment(seg: str) -> bool:
    """Name lists are capitalised word by word; titles mostly are not."""
    s = seg.strip()
    words = [w for w in re.findall(r"[^\s,&]+", s) if w.lower() not in _NAME_PARTICLES]
    if not words:
        return False
    capitalised = sum(1 for w in words if w[:1].isupper()) / len(words)
    if re.search(r"\bet al\b|&|\band\b|,", s):
        return capitalised >= 0.6
    return len(words) <= 4 and capitalised == 1.0


def _parse_authors(seg: str) -> list[str]:
    seg = re.sub(r"\(\s*(?:19|20)\d{2}[a-z]?\s*\)", "", seg)
    seg = re.sub(r",?\s*\bet al\b\.?", "", seg)
    parts = [p.strip(" .") for p in re.split(r",\s*(?:and\s+|&\s*)?|\s+and\s+|\s*&\s*", seg) if p.strip(" .")]
    authors: list[str] = []
    for p in parts:
        if authors and _INITIALS_RE.match(p + "."):
            authors[-1] = f"{authors[-1]}, {p}"   # "Jumper", "J" → "Jumper, J"
        else:
            authors.append(p)
    return [a for a in authors if re.search(r"[A-Za-z]{2}", a)][:50]


def _clean_title(title: str) -> str:
    title = re.sub(r"^\(?\s*(?:19|20)\d{2}[a-z]?\s*\)?[.,:]?\s*", "", title)      # leading "(2020)."
    title = re.sub(r",?\s*\(?(?:19|20)\d{2}[a-z]?\)?\.?$", "", title)             # trailing ", 2018"
    title = re.sub(r"\s*(?:\[[^\]]*\]|URL\b.*|arXiv preprint.*)$", "", title, flags=re.I)
    return title.strip(" .,;:")


def _guess_title_and_authors(entry: str) -> tuple[str | None, list[str]]:
    entry = _NUM_MARKER_RE.sub("", entry, count=1).strip()
    if not entry:
        return None, []

    quoted = _TITLE_QUOTED_RE.search(entry)
    if quoted:
        title = quoted.group(1).strip(" ,.")
        return title, _parse_authors(entry[:quoted.start()])

    body = _URL_RE.sub(" ", entry)
    # PDF text often drops the space after a period: "synthesis.Molecular cancer".
    body = re.sub(r"([a-z)\]]{2})\.([A-Z][a-z])", r"\1. \2", body)
    segs = [s.strip() for s in _SENTENCE_SPLIT_RE.split(body) if s and s.strip()]
    if not segs:
        return None, []
    authors: list[str] = []
    idx = 0
    # "Arnold, F. H. Catalyzing the future": the author list ends on an initial, so the
    # sentence split above keeps authors and title together. Cut at the initial.
    b = _INITIAL_TITLE_BOUNDARY_RE.search(segs[0])
    if b and _is_author_segment(segs[0][:b.start()]):
        segs = [segs[0][:b.start()], segs[0][b.end():]] + segs[1:]
    if len(segs) > 1 and _is_author_segment(segs[0]):
        authors = _parse_authors(segs[0])
        idx = 1
        # APA: "Smith, J. (2020). Title." — the year may be its own segment
        if idx < len(segs) - 1 and re.fullmatch(r"\(?(?:19|20)\d{2}[a-z]?\)?", segs[idx]):
            idx += 1
    title = _clean_title(segs[idx])
    if len(title) < 8 or not re.search(r"[A-Za-z]{3}", title):
        return None, authors
    if re.match(r"(?:in|url|http|doi|pp|vol)\b", title, re.I):
        return None, authors
    return title[:300], authors


def _parse_entry(entry: str) -> dict | None:
    if len(entry) < 15:
        return None
    title, authors = _guess_title_and_authors(entry)
    if not title:
        return None
    doi_match = DOI_RE.search(entry)
    doi = doi_match.group(1).rstrip(".,;)]") if doi_match else None
    arxiv_match = ARXIV_RE.search(entry) or _ARXIV_URL_RE.search(entry)
    arxiv_id = arxiv_match.group(1) if arxiv_match else None
    if not arxiv_id and doi:
        m = re.match(r"10\.48550/arXiv\.(\d{4}\.\d{4,5})", doi, re.I)
        arxiv_id = m.group(1) if m else None
    years = [int(y[:4]) for y in _YEAR_ANY_RE.findall(_URL_RE.sub(" ", entry))]
    years = [y for y in years if y <= time.gmtime().tm_year + 1]
    return {
        "title": title,
        "authors": authors,
        "year": years[-1] if years else None,
        "doi": doi,
        "arxiv_id": arxiv_id,
    }


def _extract_references_from_text(raw_text: str) -> list[dict]:
    """Deterministic extraction from the reference sections of raw PDF text."""
    sections = _get_ref_sections(raw_text)
    if sections:
        return _dedupe([r for sec in sections for r in _parse_section(sec)])
    # No header: accept only a long, strictly sequential numbered list in the tail.
    tail = raw_text[int(len(raw_text) * 0.4):]
    entries = _split_numbered(_clean_lines(tail), anchored=False)
    if not entries or len(entries) < _HEADERLESS_MIN_ENTRIES:
        return []
    return _dedupe([r for r in (_parse_entry(e) for e in entries) if r])


def _parse_section(section: str) -> list[dict]:
    refs = [r for r in (_parse_entry(e) for e in _split_entries(section)) if r]
    return _dedupe(refs)


# ── LLM extraction ────────────────────────────────────────────────────────────

_REF_AI_PROMPT = (
    "Extract every cited reference from the text below.\n"
    "Rules:\n"
    "- Only include real academic references (papers, books, reports, preprints, software).\n"
    "- Skip section headers, page headers/footers, acknowledgements and non-reference text.\n"
    "- The text may start or end in the middle of an entry; include a cut-off entry only if its title is complete.\n"
    "- Each entry must have these keys:\n"
    "    title (string, required — the paper/book title only, not authors or venue),\n"
    "    authors (array of strings — full names as written),\n"
    "    year (integer or null),\n"
    "    doi (string or null — only if explicitly present in the text),\n"
    "    arxiv_id (string or null — e.g. '2301.07041', only if explicitly present)\n"
    'Return ONLY a JSON object of the form {{"references": [...]}} — no markdown fences, no explanation.\n\n'
    "Text:\n{ref_text}"
)


def _parse_ref_json(raw: str) -> list[dict]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        # Truncated or chatty output: take the outermost array if there is one.
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    if not isinstance(data, list):
        return []
    refs = []
    for item in data:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        year = item.get("year")
        try:
            year = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        authors = item.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        refs.append({
            "title": str(item.get("title", "")).strip(),
            "authors": [str(a) for a in authors],
            "year": year,
            "doi": item.get("doi") or None,
            "arxiv_id": item.get("arxiv_id") or None,
        })
    return refs


def _chunk_section(section: str) -> list[str]:
    """Split the section into ~_AI_CHUNK_CHARS pieces on entry boundaries."""
    section = section[:_AI_MAX_SECTION_CHARS]
    entries = _split_entries(section)
    if len(entries) < 3:
        # No usable entry structure: fall back to line boundaries.
        entries = [ln for ln in section.splitlines() if ln.strip()]
    chunks: list[str] = []
    buf = ""
    for e in entries:
        if buf and len(buf) + len(e) + 1 > _AI_CHUNK_CHARS:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n{e}" if buf else e
    if buf:
        chunks.append(buf)
    return chunks


def _claude_extract(text: str, *, prefer_work: bool = True) -> list[dict]:
    """Claude Work → Claude personal on one chunk."""
    ai_cfg = get_effective_ai_config()
    work_key = (ai_cfg.get("anthropic_work_api_key") or "").strip()
    work_base = (ai_cfg.get("anthropic_work_base_url") or "").strip()
    personal_key = (ai_cfg.get("anthropic_api_key") or "").strip()
    prompt = _REF_AI_PROMPT.format(ref_text=text)

    import anthropic

    attempts = []
    if work_key and prefer_work:
        kwargs: dict = {"api_key": work_key, "http_client": httpx.Client(verify=False), "timeout": _AI_TIMEOUT}
        if work_base:
            kwargs["base_url"] = work_base
        attempts.append(("Claude Work", kwargs, "claude-sonnet-4-6"))
    if personal_key:
        attempts.append(("Claude personal", {
            "api_key": personal_key,
            "base_url": "https://api.anthropic.com",
            "http_client": httpx.Client(verify=settings.ssl_verify if settings.ssl_verify is not False else False),
            "timeout": _AI_TIMEOUT,
        }, "claude-haiku-4-5-20251001"))

    for name, kwargs, model in attempts:
        try:
            client = anthropic.Anthropic(**kwargs)
            resp = client.messages.create(
                model=model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
            refs = _parse_ref_json(resp.content[0].text)
            if refs:
                log.debug("References chunk via %s | count=%d", name, len(refs))
                return refs
        except Exception as exc:
            log.debug("%s references failed: %s", name, exc)
    return []


def _litellm_extract(text: str) -> list[dict]:
    from services.litellm_client import chat_completion

    raw = chat_completion(
        messages=[{"role": "user", "content": _REF_AI_PROMPT.format(ref_text=text)}],
        json_mode=True,
        max_tokens=8192,
        timeout=_AI_TIMEOUT,
        max_retries=0,          # a timed-out chunk goes to Claude rather than waiting again
    )
    return _parse_ref_json(raw)


def _extract_chunk(text: str, use_claude: bool) -> list[dict]:
    try:
        refs = _litellm_extract(text)
        if refs:
            return refs
    except Exception as exc:
        log.debug("LiteLLM references chunk failed: %s", exc)
    return _claude_extract(text) if use_claude else []


def _run_chunks(section: str, use_claude: bool) -> list[dict]:
    chunks = _chunk_section(section)
    if not chunks:
        return []
    with ThreadPoolExecutor(max_workers=min(_AI_WORKERS, len(chunks))) as pool:
        parts = list(pool.map(lambda c: _extract_chunk(c, use_claude), chunks))
    refs = [r for part in parts for r in part]
    log.info("AI references | chunks=%d | refs=%d | empty_chunks=%d",
             len(chunks), len(refs), sum(1 for p in parts if not p))
    return _dedupe(refs)


def _extract_references_with_ai(ref_text: str) -> list[dict]:
    """LLM extraction over the whole reference section, chunked.

    LiteLLM first; Claude (Work → personal) only for chunks LiteLLM could not do.
    """
    try:
        return _run_chunks(ref_text, use_claude=True)
    except Exception:
        log.debug("AI references extraction failed", exc_info=True)
        return []


def extract_references_ai_full(raw_text: str) -> list[dict]:
    """Forced AI path (on-demand button): chunked LLM extraction, no S2."""
    section = _get_ref_section_text(raw_text) or raw_text
    return _extract_references_with_ai(section)


# ── Combination ───────────────────────────────────────────────────────────────

def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())[:120]


def _dedupe(refs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for r in refs:
        key = _norm_title(r.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _complete_enough(refs: list[dict] | None, expected: int) -> bool:
    return bool(refs) and len(refs) >= max(2, _COMPLETE_FRACTION * expected)


def extract_references(raw_text: str, doi: str | None) -> list[dict]:
    """
    Extract cited references for a paper.

    Strategy A: Semantic Scholar (requires DOI/arXiv) — accepted when it is at
                least as complete as what the parser sees in the text.
    Strategy B: LLM over the reference section, chunked.
    Strategy C: Deterministic parser — fallback, and the completeness yardstick.

    Returns list of dicts: {title, authors, year, doi, arxiv_id}
    """
    s2_refs = _fetch_s2_references(doi) if doi else None

    if not raw_text:
        return s2_refs or []

    section = _get_ref_section_text(raw_text)
    parsed = _extract_references_from_text(raw_text)
    expected = len(parsed)

    if _complete_enough(s2_refs, expected):
        log.debug("References via S2 | count=%d | parser=%d", len(s2_refs), expected)
        return s2_refs

    ai_refs: list[dict] = []
    if section and len(section.strip()) > 200:
        ai_refs = _extract_references_with_ai(section) or []
        if _complete_enough(ai_refs, expected):
            log.debug("References via AI | count=%d | parser=%d", len(ai_refs), expected)
            return ai_refs

    # Nothing reached the parser's count: take the most complete source, preferring
    # structured sources on ties.
    candidates = [(s2_refs or [], 2), (ai_refs, 1), (parsed, 0)]
    best = max(candidates, key=lambda c: (len(c[0]), c[1]))[0]
    log.debug("References fallback | s2=%d | ai=%d | parser=%d",
              len(s2_refs or []), len(ai_refs), expected)
    return best
