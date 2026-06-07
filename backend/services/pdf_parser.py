import re
import json
import logging
from pypdf import PdfReader
from io import BytesIO

log = logging.getLogger(__name__)

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)")
DOI_URL_RE = re.compile(r"doi\.org/(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
ARXIV_RE = re.compile(r"arXiv[:\s](\d{4}\.\d{4,5})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# Year that appears near "published" / "online" — more reliable than first year in text
_PUBLISHED_YEAR_RE = re.compile(r"(?:published[^\n]{0,40}?|online[^\n]{0,20}?)\b((19|20)\d{2})\b", re.IGNORECASE)
# Matches "Abstract" / "ABSTRACT" heading followed by the abstract text
ABSTRACT_RE = re.compile(
    r"(?:^|\n)(?:abstract|summary)\s*[:\n\r]+\s*(.*?)(?=\n\s*(?:\d[\.\s]|introduction|keywords|key\s+words|1\s+intro|\Z))",
    re.IGNORECASE | re.DOTALL,
)


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(pdf_bytes: bytes, max_pages: int | None = None) -> str:
    """Extract text from a PDF.

    max_pages limits how many leading pages are read — used by the upload-queue
    preview, where only the first page or two is needed for metadata and reading
    a full 100+ page document would be needlessly slow (pypdf is CPU-bound).
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages_iter = reader.pages if max_pages is None else reader.pages[:max_pages]
        pages = [page.extract_text() or "" for page in pages_iter]
        return "\n".join(pages).strip()
    except Exception:
        return ""


# ── DOI / arXiv ID detection ─────────────────────────────────────────────────

_SUPPLEMENTAL_RE = re.compile(r"[/-]+(DCSupplemental|supplementary|supp|SI|S\d+).*$", re.IGNORECASE)

def _clean_doi(raw: str) -> str | None:
    """Strip trailing punctuation, supplemental suffixes; reject truncated DOIs."""
    raw = raw.rstrip(".,;)")
    raw = _SUPPLEMENTAL_RE.sub("", raw)
    suffix = raw.split("/", 1)[1] if "/" in raw else ""
    return raw if len(suffix) >= 4 else None


def find_doi(text: str) -> str | None:
    arxiv = ARXIV_RE.search(text)
    if arxiv:
        return f"arXiv:{arxiv.group(1)}"
    # Try URL form first (doi.org/10.xxx) — common in PDF headers
    url_match = DOI_URL_RE.search(text)
    if url_match:
        cleaned = _clean_doi(url_match.group(1))
        if cleaned:
            return cleaned
    # Bare DOI form
    doi = DOI_RE.search(text)
    if doi:
        cleaned = _clean_doi(doi.group(1))
        if cleaned:
            return cleaned
    return None


# ── Layer 2: LLM via LiteLLM ──────────────────────────────────────────────────

def extract_metadata_with_llm(first_page_text: str) -> dict | None:
    try:
        from services.litellm_client import chat_completion

        prompt = f"""Extract metadata from this academic paper's first page.
Return ONLY valid JSON with exactly these keys:
title (string), authors (list of strings), year (integer or null),
venue (string or null), abstract (string or null)

Paper text:
{first_page_text[:3000]}
"""
        raw = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
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
    except Exception as e:
        log.warning("LLM metadata extraction failed: %s", e)
        return None


# ── Abstract extraction from raw text ─────────────────────────────────────────

_ABSTRACT_HEADER_RE = re.compile(
    r"^(?:abstract|summary|description|overview)\s*[:\-–]?\s*",
    re.IGNORECASE,
)


def _clean_abstract(text: str) -> str:
    """Strip any leading 'Abstract' / 'Abstract:' heading from an abstract string."""
    return _ABSTRACT_HEADER_RE.sub("", text.strip()).strip()


def extract_abstract_from_text(text: str) -> str | None:
    m = ABSTRACT_RE.search(text)
    if not m:
        return None
    abstract = _clean_abstract(m.group(1))
    # Collapse excessive whitespace / newlines
    abstract = re.sub(r"\s*\n\s*", " ", abstract).strip()
    return abstract if len(abstract) > 50 else None


def extract_abstract_with_ai(text: str, document_type: str | None = None) -> str | None:
    """Use Claude to flexibly extract the abstract/description from document text.

    The prompt is adapted based on document_type:
    - 'paper' (default): look for the abstract section
    - 'book': look for the back-cover description, preface, or introduction overview
    - 'lecture_deck': look for the overview, objectives, or opening slide summary
    """
    _PROMPTS = {
        "book": (
            "This is text from a book. Extract a concise description of the book — "
            "this may come from a preface, introduction, back-cover blurb, or an 'About this book' section.\n"
            "Return ONLY the description text itself — no label or prefix.\n"
            "If nothing suitable exists, return an empty string.\n\n"
            f"Book text:\n{text[:5000]}"
        ),
        "lecture_deck": (
            "This is text from a lecture slide deck. Extract a short overview or description of what the "
            "slides cover — this may come from an overview slide, learning objectives, or opening summary.\n"
            "Return ONLY the description text itself — no label or prefix.\n"
            "If nothing suitable exists, return an empty string.\n\n"
            f"Slide text:\n{text[:5000]}"
        ),
    }
    prompt = _PROMPTS.get(document_type or "paper") or (
        "Extract the abstract from this academic paper text.\n"
        "Return ONLY the abstract text itself — no label, no prefix like 'Abstract:' or 'Summary:'.\n"
        "If there is no abstract, return an empty string.\n\n"
        f"Paper text:\n{text[:5000]}"
    )
    try:
        from services.litellm_client import chat_completion

        raw = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        result = _clean_abstract(raw)
        return result if len(result) > 50 else None
    except Exception:
        log.debug("AI abstract extraction failed", exc_info=True)
        return None


# ── Layer 3: regex heuristics ─────────────────────────────────────────────────

def extract_metadata_heuristic(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0] if lines else "Unknown"
    pub = _PUBLISHED_YEAR_RE.search(text[:3000])
    year_match = pub or YEAR_RE.search(text[:3000])
    year = int((pub.group(1) if pub else year_match.group())) if year_match else None
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


def extract_metadata(pdf_bytes: bytes, *, allow_llm: bool = True, max_pages: int | None = None) -> dict:
    """Extract metadata from PDF.

    Strategy:
    1. LLM (Gemma via LiteLLM) — primary extractor when allow_llm=True.
    2. Heuristics — fast fallback (always succeeds).

    max_pages limits PDF text extraction to the first N pages. The upload-queue
    preview passes max_pages so it only reads the title page(s) instead of the
    whole document — this keeps the queue fast and avoids serializing large
    CPU-bound pypdf reads when many papers are dropped at once.
    """
    text = extract_text(pdf_bytes, max_pages=max_pages)
    doi = find_doi(text)
    log.info("Extracting metadata | doi=%s | text_len=%d | max_pages=%s", doi, len(text), max_pages)

    # Layer 1: LLM (Gemma via LiteLLM) — primary metadata extractor.
    if allow_llm:
        first_page = text[:3000]
        try:
            result = extract_metadata_with_llm(first_page)
            if result and result.get("title"):
                log.info("Metadata via LLM (layer 1) | title=%.60s", result.get("title"))
                if doi:
                    result["doi"] = doi
                result["raw_text"] = text
                return _fill_missing_abstract(result, text)
            log.warning("LLM returned no usable title — falling back to heuristics")
        except Exception as e:
            log.warning("LLM metadata extraction failed: %s", e)

    # Layer 2: heuristics (fast; also the path used for allow_llm=False preview).
    log.info("Metadata via heuristics (layer 2)")
    result = extract_metadata_heuristic(text)
    if doi:
        result["doi"] = doi
    result["raw_text"] = text
    return result
