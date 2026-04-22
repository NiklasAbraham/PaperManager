import re
import json
import logging
import httpx

from services.pdf_parser import DOI_RE, ARXIV_RE, YEAR_RE
from config import settings

log = logging.getLogger(__name__)

_SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_REF_FIELDS = "title,authors,year,externalIds"

# Patterns for splitting reference list entries
_REF_SPLIT_RE = re.compile(
    r"(?:^|\n)\s*(?:\[\d+\]|\d+\.)\s+",  # [1] or 1.
)
_SECTION_RE = re.compile(
    r"\n\s*(?:References|Bibliography|Works\s+Cited|Literature\s+Cited)\s*\n",
    re.IGNORECASE,
)


def _fetch_s2_references(doi: str) -> list[dict] | None:
    """Fetch structured references from Semantic Scholar. Returns None on failure."""
    try:
        r = httpx.get(
            f"{_SS_BASE}/{doi}/references",
            params={"fields": _REF_FIELDS, "limit": 100},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        results = []
        for item in data.get("data", []):
            cited = item.get("citedPaper", {})
            if not cited.get("title"):
                continue
            ext = cited.get("externalIds") or {}
            results.append({
                "title": cited["title"].strip(),
                "authors": [a.get("name", "") for a in (cited.get("authors") or [])],
                "year": cited.get("year"),
                "doi": ext.get("DOI"),
                "arxiv_id": ext.get("ArXiv"),
            })
        return results if results else None
    except Exception:
        return None


def _extract_references_from_text(raw_text: str) -> list[dict]:
    """Regex-based extraction from the References section of raw PDF text."""
    # Find the references section
    match = _SECTION_RE.search(raw_text)
    if not match:
        return []
    ref_section = raw_text[match.end():]

    # Split into individual entries
    entries = _REF_SPLIT_RE.split(ref_section)
    refs = []
    for entry in entries:
        entry = entry.strip()
        if not entry or len(entry) < 10:
            continue

        # Extract DOI
        doi_match = DOI_RE.search(entry)
        doi = doi_match.group(1).rstrip(".,;)") if doi_match else None

        # Extract arXiv ID
        arxiv_match = ARXIV_RE.search(entry)
        arxiv_id = arxiv_match.group(1) if arxiv_match else None

        # Extract year
        year_match = YEAR_RE.search(entry)
        year = int(year_match.group()) if year_match else None

        # Best-effort title: first sentence / up to 120 chars, stop at author list markers
        title = _guess_title(entry)
        if not title:
            continue

        refs.append({
            "title": title,
            "authors": [],
            "year": year,
            "doi": doi,
            "arxiv_id": arxiv_id,
        })

    return refs


def _guess_title(entry: str) -> str | None:
    """Heuristically extract a title from a reference entry string."""
    # Remove leading numbering artifact
    entry = re.sub(r"^\s*\[\d+\]\s*|^\s*\d+\.\s*", "", entry).strip()
    if not entry:
        return None

    # If title appears in quotes
    quoted = re.search(r'"([^"]{10,})"', entry)
    if quoted:
        return quoted.group(1).strip()

    # Otherwise take the first meaningful chunk (up to a period or 120 chars)
    # Truncate at first period followed by a capital (likely end of title sentence)
    period_split = re.split(r"\.\s+(?=[A-Z])", entry, maxsplit=1)
    candidate = period_split[0].strip() if period_split else entry
    candidate = candidate[:120].strip()

    # Must have at least 4 words to be a reasonable title
    if len(candidate.split()) < 4:
        return None
    return candidate


def _extract_references_with_ai(ref_text: str) -> list[dict]:
    """Use Claude to parse references from text when regex fails or returns too few."""
    try:
        import anthropic
        from config import settings
        if not settings.anthropic_api_key:
            return []

        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            base_url="https://api.anthropic.com",
            http_client=httpx.Client(verify=settings.ssl_verify if settings.ssl_verify is not False else False),
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": (
                    "Extract every cited reference from the text below into a JSON array.\n"
                    "Rules:\n"
                    "- Only include real academic references (papers, books, reports, preprints).\n"
                    "- Skip section headers, acknowledgements, footnotes, and non-reference text.\n"
                    "- Each entry must have these keys:\n"
                    "    title (string, required — the paper/book title only, not authors or venue),\n"
                    "    authors (array of strings — last, first or full names),\n"
                    "    year (integer or null),\n"
                    "    doi (string or null — only if explicitly present in the text),\n"
                    "    arxiv_id (string or null — e.g. '2301.07041', only if explicitly present)\n"
                    "- Return ONLY valid JSON array — no markdown fences, no explanation.\n\n"
                    f"Text:\n{ref_text[:14000]}"
                ),
            }],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if the model added them
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        refs = []
        for item in data:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            refs.append({
                "title": str(item.get("title", "")).strip(),
                "authors": [str(a) for a in (item.get("authors") or [])],
                "year": item.get("year"),
                "doi": item.get("doi"),
                "arxiv_id": item.get("arxiv_id"),
            })
        return refs
    except Exception:
        log.debug("AI references extraction failed", exc_info=True)
        return []


def _get_ref_section_text(raw_text: str) -> str | None:
    """Return the text of the references section, or None if not found."""
    match = _SECTION_RE.search(raw_text)
    if match:
        return raw_text[match.end():]
    # Broader fallback: look for any line that reads like a references header
    broad = re.search(
        r"\n\s*(?:references|bibliography|works\s+cited|literature)\s*\n",
        raw_text, re.IGNORECASE
    )
    if broad:
        return raw_text[broad.end():]
    # Last-resort: use the final 30% of the document text
    cutoff = max(0, int(len(raw_text) * 0.7))
    tail = raw_text[cutoff:]
    return tail if tail.strip() else None


def extract_references(raw_text: str, doi: str | None) -> list[dict]:
    """
    Extract cited references for a paper.

    Strategy A: Semantic Scholar references API (requires DOI/arXiv) — highest quality.
    Strategy B: Claude AI on the references section — good quality, handles all styles.
    Strategy C: Regex — last resort when Claude is unavailable or fails.

    Returns list of dicts: {title, authors, year, doi, arxiv_id}
    """
    # Strategy A: Semantic Scholar (best — structured, complete DOI/author data)
    if doi:
        result = _fetch_s2_references(doi)
        if result:
            log.debug("References via S2 | count=%d", len(result))
            return result

    if not raw_text:
        return []

    # Strategy B: Claude AI on the reference section
    ref_section = _get_ref_section_text(raw_text)
    if ref_section:
        ai_refs = _extract_references_with_ai(ref_section)
        if ai_refs:
            log.debug("References via Claude AI | count=%d", len(ai_refs))
            return ai_refs

    # Strategy C: Regex fallback
    regex_refs = _extract_references_from_text(raw_text)
    log.debug("References via regex | count=%d", len(regex_refs))
    return regex_refs
