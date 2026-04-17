import re
import json
from pypdf import PdfReader
from io import BytesIO

from services.metadata_lookup import lookup_semantic_scholar, lookup_crossref

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)")
ARXIV_RE = re.compile(r"arXiv[:\s](\d{4}\.\d{4,5})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


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


# ── Layer 3: regex heuristics ─────────────────────────────────────────────────

def extract_metadata_heuristic(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0] if lines else "Unknown"
    year_match = YEAR_RE.search(text)
    year = int(year_match.group()) if year_match else None
    return {
        "title": title,
        "authors": [],
        "year": year,
        "venue": None,
        "abstract": None,
        "doi": None,
        "citation_count": None,
        "topics": [],
        "metadata_source": "heuristic",
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_metadata(pdf_bytes: bytes) -> dict:
    text = extract_text(pdf_bytes)
    doi = find_doi(text)

    # Layer 1: API lookup
    if doi:
        result = lookup_semantic_scholar(doi) or lookup_crossref(doi)
        if result and result.get("title"):
            result["raw_text"] = text
            return result

    # Layer 2: local LLM
    result = extract_metadata_with_llm(text[:3000])
    if result and result.get("title"):
        result["raw_text"] = text
        return result

    # Layer 3: heuristics
    result = extract_metadata_heuristic(text)
    result["raw_text"] = text
    return result
