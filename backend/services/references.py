import re
import json
import logging
import httpx

from services.pdf_parser import DOI_RE, ARXIV_RE, YEAR_RE
from config import settings
from services.user_ai_config import get_effective_ai_config

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


def _s2_paper_id(doi: str) -> str:
    """Normalise a DOI/arXiv string into a form the S2 API accepts in a URL path.

    10.48550/arXiv.2604.05181 → ArXiv:2604.05181 (avoids unencoded '/' in path)
    arXiv:2604.05181          → ArXiv:2604.05181 (capitalise prefix for clarity)
    everything else            → returned as-is
    """
    m = re.match(r"10\.48550/arXiv\.(\d{4}\.\d{4,5})", doi, re.I)
    if m:
        return f"ArXiv:{m.group(1)}"
    if doi.lower().startswith("arxiv:"):
        return f"ArXiv:{doi[6:]}"
    return doi


def _fetch_s2_references(doi: str) -> list[dict] | None:
    """Fetch structured references from Semantic Scholar. Returns None on failure."""
    try:
        paper_id = _s2_paper_id(doi)
        r = httpx.get(
            f"{_SS_BASE}/{paper_id}/references",
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


_REF_AI_PROMPT = (
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
    "Text:\n{ref_text}"
)


def _parse_ref_json(raw: str) -> list[dict]:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw.strip())
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


def extract_references_ai_full(raw_text: str) -> list[dict]:
    """Extract references using LiteLLM/Gemma → Claude Work → Claude personal (no S2)."""
    ref_section = _get_ref_section_text(raw_text)
    ref_text = (ref_section or raw_text)[:80000]
    prompt = _REF_AI_PROMPT.format(ref_text=ref_text)
    ai_cfg = get_effective_ai_config()
    work_key = (ai_cfg.get("anthropic_work_api_key") or "").strip()
    work_base = (ai_cfg.get("anthropic_work_base_url") or "").strip()
    personal_key = (ai_cfg.get("anthropic_api_key") or "").strip()

    # LiteLLM / Gemma (default — shorter context)
    try:
        from services.litellm_client import chat_completion

        short_prompt = _REF_AI_PROMPT.format(ref_text=ref_text[:12000])
        raw = chat_completion(
            messages=[{"role": "user", "content": short_prompt}],
            json_mode=True,
        )
        refs = _parse_ref_json(raw)
        if refs:
            log.debug("References via LiteLLM | count=%d", len(refs))
            return refs
    except Exception as exc:
        log.debug("LiteLLM references failed: %s", exc)

    # Claude Work
    if work_key:
        try:
            import anthropic
            kwargs: dict = {
                "api_key": work_key,
                "http_client": httpx.Client(verify=False),
            }
            if work_base:
                kwargs["base_url"] = work_base
            client = anthropic.Anthropic(**kwargs)
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
            refs = _parse_ref_json(resp.content[0].text)
            if refs:
                log.debug("References via Claude Work | count=%d", len(refs))
                return refs
        except Exception as exc:
            log.debug("Claude Work references failed: %s", exc)

    # Claude personal
    if personal_key:
        try:
            import anthropic
            client = anthropic.Anthropic(
                api_key=personal_key,
                base_url="https://api.anthropic.com",
                http_client=httpx.Client(verify=settings.ssl_verify if settings.ssl_verify is not False else False),
            )
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
            refs = _parse_ref_json(resp.content[0].text)
            if refs:
                log.debug("References via Claude personal | count=%d", len(refs))
                return refs
        except Exception as exc:
            log.debug("Claude personal references failed: %s", exc)

    return []


def _extract_references_with_ai(ref_text: str) -> list[dict]:
    """Use Claude to parse references from text when regex fails or returns too few."""
    try:
        from services.litellm_client import chat_completion

        raw = chat_completion(
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
                    f"Text:\n{ref_text[:12000]}"
                ),
            }],
            json_mode=True,
        )
        raw = raw.strip()
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
    """Return the text of the references section, or None if not found.

    Uses the LAST match so that books with per-chapter references sections
    return the final bibliography rather than an early chapter's reference list.
    """
    # Find all matches and use the last one (handles books with per-chapter refs)
    matches = list(_SECTION_RE.finditer(raw_text))
    if matches:
        return raw_text[matches[-1].end():]
    # Broader fallback: look for any line that reads like a references header
    broad_matches = list(re.finditer(
        r"\n\s*(?:references|bibliography|works\s+cited|literature|further\s+reading)\s*\n",
        raw_text, re.IGNORECASE
    ))
    if broad_matches:
        return raw_text[broad_matches[-1].end():]
    # Last-resort: use the final 20% of the document text
    cutoff = max(0, int(len(raw_text) * 0.8))
    tail = raw_text[cutoff:]
    return tail if tail.strip() else None


def extract_references(raw_text: str, doi: str | None) -> list[dict]:
    """
    Extract cited references for a paper.

    Strategy A: Semantic Scholar references API (requires DOI/arXiv) — highest quality.
    Strategy B: Claude AI on the references section — good quality, handles all styles.
    Strategy C: Regex — last resort when Claude is unavailable or fails.

    After extraction, applies a sanity check: if the result is suspiciously
    low (0-1 references for a paper that likely has more), retries with AI.

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
        if ai_refs and len(ai_refs) >= 2:
            log.debug("References via Claude AI | count=%d", len(ai_refs))
            return ai_refs

    # Strategy C: Regex fallback
    regex_refs = _extract_references_from_text(raw_text)
    log.debug("References via regex | count=%d", len(regex_refs))

    # Sanity check: a paper with a References section but only 0-1 results
    # is suspicious — the PDF-to-text conversion likely mangled the text.
    # Retry with full-text AI extraction as a fallback.
    if len(regex_refs) <= 1 and ref_section and len(ref_section.strip()) > 200:
        log.info(
            "Reference sanity check: only %d refs from regex but ref section has %d chars "
            "— retrying with full AI extraction",
            len(regex_refs), len(ref_section),
        )
        ai_retry = _extract_references_with_ai(ref_section)
        if ai_retry and len(ai_retry) > len(regex_refs):
            log.debug("References via AI retry | count=%d (was %d)", len(ai_retry), len(regex_refs))
            return ai_retry

    return regex_refs
