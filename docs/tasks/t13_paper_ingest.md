# T13 — Full Paper Ingestion Pipeline

**Phase:** 3 — File handling + AI
**Depends on:** T05, T10, T11, T12
**Touches:** `backend/routers/papers.py` (update POST /papers to accept file upload)

## Goal
The complete "drop a PDF" flow:
Upload PDF → extract metadata (DOI lookup → Ollama → heuristic) → upload to Drive → summarize → save to Neo4j → return paper.

## Updated POST /papers endpoint

Accepts `multipart/form-data`:
- `file`: the PDF (required)
- `title`: string override (optional — use if extraction is wrong)
- `project_id`: link to project immediately (optional)

---

## Pipeline (in order)

```
1. pdf_parser.extract_text(file.bytes)
   → raw_text (str)

2. pdf_parser.find_doi(raw_text)
   → doi (str | None)

   ┌── doi found? ──────────────────────────────────────────┐
   │  metadata_lookup.lookup_semantic_scholar(doi)           │
   │    → {title, authors, year, venue, abstract, topics}   │
   │    also returns: citation_count (store on Paper node)   │
   │  if not found: metadata_lookup.lookup_crossref(doi)    │
   └────────────────────────────────────────────────────────┘

   ┌── no doi / not indexed? ───────────────────────────────┐
   │  pdf_parser.extract_metadata_with_llm(raw_text[:3000]) │
   │    → {title, authors, year, venue, abstract}           │
   └────────────────────────────────────────────────────────┘

   ┌── ollama unavailable? ─────────────────────────────────┐
   │  pdf_parser.extract_metadata_heuristic(raw_text)       │
   │    → {title, year} (minimal, user corrects in UI)      │
   └────────────────────────────────────────────────────────┘

3. If title override provided → replace extracted title

4. drive.upload_pdf(file.bytes, filename)
   → drive_file_id (str)

5. ai.summarize_paper(raw_text, title)
   → summary (str)

6. db.papers.create_paper({
       title, year, doi, abstract, summary,
       drive_file_id, raw_text,
       citation_count,           ← from Semantic Scholar if available
       metadata_source           ← "semantic_scholar" | "crossref" | "llm" | "heuristic"
   })
   → paper node

7. For each author name in extracted authors:
   db.people.get_or_create_person(name)
   db.people.link_author(paper_id, person_id)

8. If Semantic Scholar returned topics:
   For each topic:
     db.topics.get_or_create_topic(topic_name)
     db.topics.link_paper_topic(paper_id, topic_id)
   ← free auto-tagging with research topics

9. If project_id provided:
   db.projects.add_paper_to_project(paper_id, project_id)

10. Return PaperOut JSON  (includes metadata_source so UI can show confidence)
```

---

## metadata_source field

Stored on the Paper node. The frontend can show a badge like:
- `semantic_scholar` → green, high confidence
- `crossref` → green, high confidence
- `llm` → yellow, review recommended
- `heuristic` → red, please correct

This lets you quickly spot papers that need manual metadata correction.

---

## Error handling

| What fails | Behaviour |
|---|---|
| Drive upload | Abort, return 503 |
| Semantic Scholar API down | Fall through to Crossref silently |
| Crossref API down | Fall through to Ollama silently |
| Ollama not running | Fall through to heuristic, flag in response |
| Claude summarization fails | Save paper without summary (`summary=null`) |
| PDF has no extractable text | Save paper, skip summary, set `metadata_source="heuristic"` |

---

## Response shape

```json
{
  "id": "abc123",
  "title": "Attention Is All You Need",
  "year": 2017,
  "authors": ["Vaswani", "Shazeer", "..."],
  "venue": "NeurIPS",
  "abstract": "...",
  "summary": "...",
  "drive_file_id": "1BxiM...",
  "drive_url": "https://drive.google.com/file/d/1BxiM.../view",
  "metadata_source": "semantic_scholar",
  "citation_count": 91423,
  "topics_auto_added": ["Transformers", "Natural Language Processing"]
}
```

---

## Done when
- [ ] POST /papers with a PDF that has a DOI → authors + topics auto-populated from Semantic Scholar
- [ ] POST /papers with a draft PDF (no DOI) → Ollama extracts title + authors
- [ ] `metadata_source` field is set correctly on the Paper node
- [ ] Drive file ID stored, summary generated
- [ ] Works end-to-end in under 30 seconds

## Tests
`backend/tests/test_paper_ingest.py` — mark as `@pytest.mark.integration`
- Upload PDF with known DOI → check authors list is non-empty, metadata_source="semantic_scholar"
- Upload PDF without DOI (use a draft) → metadata_source="llm" or "heuristic"
- Upload same PDF twice → two separate paper nodes (no dedup by content for now)
- Drive upload fails (mock) → 503 returned, no Neo4j node created
- Claude fails (mock) → 201 returned, paper saved, summary=null
