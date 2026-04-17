import re
import json
import logging
from pypdf import PdfReader
from io import BytesIO

from services.metadata_lookup import lookup_semantic_scholar, lookup_crossref, search_semantic_scholar_by_title

log = logging.getLogger(__name__)

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)")
ARXIV_RE = re.compile(r"arXiv[:\s](\d{4}\.\d{4,5})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# Matches "Abstract" / "ABSTRACT" heading followed by the abstract text
ABSTRACT_RE = re.compile(
    r"(?:^|\n)(?:abstract|summary)\s*[:\n\r]+\s*(.*?)(?=\n\s*(?:\d[\.\s]|introduction|keywords|key\s+words|1\s+intro|\Z))",
    re.IGNORECASE | re.DOTALL,
)


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception:
        return ""


# ── DOI / arXiv ID detection ─────────────────────────────────────────────────

def find_doi(text: str) -> str | None:
    arxiv = ARXIV_RE.search(text)
    if arxiv:
        return f"arXiv:{arxiv.group(1)}"
    doi = DOI_RE.search(text)
    if doi:
        # Strip trailing punctuation that sometimes gets picked up
        return doi.group(1).rstrip(".,;)")
    return None


# ── Layer 2: local LLM via Ollama ─────────────────────────────────────────────

def extract_metadata_with_llm(first_page_text: str) -> dict | None:
    try:
        import ollama
        from config import settings

        prompt = f"""Extract metadata from this academic paper's first page.
Return ONLY valid JSON with exactly these keys:
title (string), authors (list of strings), year (integer or null),
venue (string or null), abstract (string or null)

Paper text:
{first_page_text[:3000]}
"""
        response = ollama.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        raw = response["message"]["content"]
        data = json.loads(raw)
        return {
            "title": str(data.get("title") or "").strip(),
            "authors": [str(a) for a in (data.get("authors") or [])],
            "year": data.get("year"),
            "venue": data.get("venue"),
            "abstract": data.get("abstract"),
            "doi": None,
            "citation_count": None,
            "topics": [],
            "metadata_source": "llm",
        }
    except Exception:
        return None


# ── Abstract extraction from raw text ─────────────────────────────────────────

def extract_abstract_from_text(text: str) -> str | None:
    m = ABSTRACT_RE.search(text)
    if not m:
        return None
    abstract = m.group(1).strip()
    # Collapse excessive whitespace / newlines
    abstract = re.sub(r"\s*\n\s*", " ", abstract).strip()
    return abstract if len(abstract) > 50 else None


def extract_abstract_with_ai(text: str) -> str | None:
    """Use Claude to flexibly extract the abstract from paper text."""
    try:
        import anthropic
        from config import settings
        if not settings.anthropic_api_key:
            return None

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    "Extract the abstract from this academic paper text.\n"
                    "Return ONLY the abstract text itself — no label, no prefix like 'Abstract:' or 'Summary:'.\n"
                    "If there is no abstract, return an empty string.\n\n"
                    f"Paper text:\n{text[:5000]}"
                ),
            }],
        )
        result = response.content[0].text.strip()
        # Strip accidental prefixes the model might still include
        result = re.sub(r"^(?:abstract|summary)\s*[:\-–]\s*", "", result, flags=re.IGNORECASE).strip()
        return result if len(result) > 50 else None
    except Exception:
        log.debug("AI abstract extraction failed", exc_info=True)
        return None


# ── Layer 3: regex heuristics ─────────────────────────────────────────────────

def extract_metadata_heuristic(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0] if lines else "Unknown"
    year_match = YEAR_RE.search(text)
    year = int(year_match.group()) if year_match else None
    abstract = extract_abstract_from_text(text)
    return {
        "title": title,
        "authors": [],
        "year": year,
        "venue": None,
        "abstract": abstract,
        "doi": None,
        "citation_count": None,
        "topics": [],
        "metadata_source": "heuristic",
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def _fill_missing_abstract(result: dict, text: str) -> dict:
    """If the result has no abstract, try regex then Claude AI extraction."""
    if not result.get("abstract"):
        result["abstract"] = extract_abstract_from_text(text)
    if not result.get("abstract"):
        log.debug("Regex abstract extraction failed — trying Claude AI")
        result["abstract"] = extract_abstract_with_ai(text)
    return result


def extract_metadata(pdf_bytes: bytes) -> dict:
    text = extract_text(pdf_bytes)
    doi = find_doi(text)
    log.info("Extracting metadata | doi=%s | text_len=%d", doi, len(text))

    # Layer 1a: API lookup by DOI/arXiv
    if doi:
        result = lookup_semantic_scholar(doi) or lookup_crossref(doi)
        if result and result.get("title"):
            log.info("Metadata via API (layer 1) | source=%s | title=%.60s", result.get("metadata_source"), result.get("title"))
            result["raw_text"] = text
            return _fill_missing_abstract(result, text)

    # Layer 2: local LLM
    first_page = text[:3000]
    result = extract_metadata_with_llm(first_page)
    if result and result.get("title"):
        log.info("Metadata via LLM (layer 2) | title=%.60s", result.get("title"))
        result["raw_text"] = text
        # Layer 1b: try S2 by title from LLM
        s2 = search_semantic_scholar_by_title(result["title"])
        if s2:
            log.info("Upgraded to S2 via title search | title=%.60s", s2.get("title"))
            s2["raw_text"] = text
            return _fill_missing_abstract(s2, text)
        return _fill_missing_abstract(result, text)

    # Layer 3: heuristics
    log.info("Metadata via heuristics (layer 3)")
    result = extract_metadata_heuristic(text)
    result["raw_text"] = text
    return result
