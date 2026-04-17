# T10 — PDF Parser + Metadata Extraction

**Phase:** 3 — File handling + AI
**Depends on:** T01
**Touches:** `backend/services/pdf_parser.py`, `backend/services/metadata_lookup.py`

## Goal
Given an uploaded PDF, extract:
- Raw text (for Claude summarization, search, and chat)
- Structured metadata: title, year, authors, DOI, venue, abstract

Metadata extraction uses a **three-layer strategy** — try the best option first, fall back as needed.

---

## Layer 1 — DOI → Semantic Scholar / Crossref API

~80–90% of papers have a DOI or arXiv ID in the PDF text. If found, one free API call
returns perfect structured metadata — no LLM needed.

```python
# services/pdf_parser.py

DOI_RE    = re.compile(r'10\.\d{4,9}/[^\s"<>]+')
ARXIV_RE  = re.compile(r'arXiv:(\d{4}\.\d{4,5})')

def find_doi(text: str) -> str | None:
    # Check for standard DOI or arXiv ID, return first match
```

```python
# services/metadata_lookup.py

def lookup_semantic_scholar(doi: str) -> dict | None:
    """
    GET https://api.semanticscholar.org/graph/v1/paper/{doi}
        ?fields=title,authors,year,venue,abstract,externalIds
    Returns clean dict or None if not found.
    Also returns: topics, citation count — bonus graph data.
    """

def lookup_crossref(doi: str) -> dict | None:
    """
    GET https://api.crossref.org/works/{doi}
    Fallback if Semantic Scholar misses it.
    """
```

Semantic Scholar is preferred — it returns richer data (topics, citation count).
Crossref is the fallback — broader coverage for older/obscure papers.

---

## Layer 2 — Local LLM via Ollama (no DOI, or not indexed)

For drafts, internal reports, conference papers not yet indexed.

**Setup (one-time, on your machine):**
```bash
brew install ollama
ollama pull llama3.2:3b    # ~2 GB, fast on MacBook
```

```python
# services/pdf_parser.py

def extract_metadata_with_llm(first_page_text: str) -> dict:
    """
    Sends first ~3000 chars to local Ollama model.
    Uses format='json' to force structured output.
    """
    import ollama
    prompt = f"""
Extract metadata from this academic paper's first page.
Return ONLY valid JSON with exactly these keys:
title (string), authors (list of strings), year (integer or null),
venue (string or null), abstract (string or null)

Paper text:
{first_page_text[:3000]}
"""
    response = ollama.chat(
        model="llama3.2:3b",
        messages=[{"role": "user", "content": prompt}],
        format="json"
    )
    return json.loads(response["message"]["content"])
```

Ollama runs **entirely locally** — no API key, no internet needed, no cost.

---

## Layer 3 — Heuristic fallback

If Ollama is not installed or returns unparseable output:

```python
def extract_metadata_heuristic(text: str) -> dict:
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    title = lines[0] if lines else "Unknown"
    year_match = re.search(r'\b(19|20)\d{2}\b', text)
    year = int(year_match.group()) if year_match else None
    return {"title": title, "year": year, "authors": [], "venue": None, "abstract": None}
```

---

## Main entry point

```python
def extract_metadata(pdf_bytes: bytes) -> dict:
    text = extract_text(pdf_bytes)
    doi  = find_doi(text)

    # Layer 1: API lookup
    if doi:
        result = lookup_semantic_scholar(doi) or lookup_crossref(doi)
        if result:
            result["raw_text"] = text
            return result

    # Layer 2: local LLM
    try:
        result = extract_metadata_with_llm(text[:3000])
        result["raw_text"] = text
        result.setdefault("doi", None)
        return result
    except Exception:
        pass

    # Layer 3: heuristics
    result = extract_metadata_heuristic(text)
    result["raw_text"] = text
    return result
```

---

## New file: services/metadata_lookup.py

Keeps API logic separate from PDF parsing logic:
```
services/
├── pdf_parser.py        # text extraction + metadata orchestration
└── metadata_lookup.py   # Semantic Scholar + Crossref API clients
```

---

## Requirements additions (vs T01)
```
ollama          # Ollama Python client
httpx           # already there — used for API calls
```

Ollama itself is installed via Homebrew — not a pip package.

---

## Done when
- [ ] `extract_text(bytes)` returns non-empty string for a normal PDF
- [ ] `find_doi(text)` finds standard DOI and arXiv IDs
- [ ] `lookup_semantic_scholar(doi)` returns clean dict for a known paper
- [ ] `extract_metadata_with_llm(text)` returns valid JSON via Ollama
- [ ] `extract_metadata(bytes)` runs the full chain and always returns a dict
- [ ] Scanned PDF (no extractable text) → returns heuristic result, does not crash
- [ ] Ollama not installed → falls through to heuristic gracefully

## Tests
`backend/tests/test_pdf_parser.py`
- Store test fixtures in `backend/tests/fixtures/` (one PDF with DOI, one without)
- `extract_text` → non-empty string
- `find_doi` → correct DOI matched
- `lookup_semantic_scholar` → returns title, authors (mark `@pytest.mark.integration`)
- `extract_metadata_with_llm` → returns dict with `title` key (mark `@pytest.mark.integration`)
- `extract_metadata` on PDF-with-DOI → authors list is non-empty
- `extract_metadata` on empty bytes → returns dict without crashing

## Notes
- `raw_text` is returned as part of the metadata dict and stored on the Paper node for chat (T14)
- Semantic Scholar also returns `topics` — we can auto-create Topic nodes from these (future enhancement)
- arXiv IDs are resolved via: `https://api.semanticscholar.org/graph/v1/paper/arXiv:{id}`
