# T24 — Related Papers (Semantic Scholar Recommendations)

**Phase:** 7 — Discovery & Intelligence
**Depends on:** T05, T13
**Touches:** `backend/services/metadata_lookup.py`, `backend/routers/papers.py`, `frontend/src/pages/PaperDetail.tsx`

## Goal
A "Related" tab on each paper's detail page that calls Semantic Scholar's recommendations API and shows up to 10 papers the user likely hasn't seen. One-click add to library.

---

## Backend

### New function in `backend/services/metadata_lookup.py`

```python
_S2_REC_BASE = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper"
_S2_PAPER_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_REC_FIELDS = "title,authors,year,abstract,externalIds,venue,citationCount"

def _get_s2_paper_id(doi: str) -> str | None:
    """
    Resolve a DOI or arXiv ID to a Semantic Scholar internal paperId.
    GET /paper/DOI:{doi}?fields=paperId  (or /paper/ARXIV:{id}?fields=paperId)
    Returns paperId string or None on failure.
    """

def get_related_papers(doi: str, limit: int = 10) -> list[dict]:
    """
    1. Resolve doi to S2 paperId via _get_s2_paper_id().
    2. GET {_S2_REC_BASE}/{paperId}?fields={_REC_FIELDS}&limit={limit}
    3. Map each result to the standard metadata dict:
       { title, authors, year, abstract, doi, url, venue, citation_count,
         in_library (default False), library_paper_id (default None) }
    Returns [] if S2 paper not found or recommendations unavailable.
    """
```

### New endpoint in `backend/routers/papers.py`

```
GET /papers/{paper_id}/related?limit=10
```

Logic:
1. Load paper from Neo4j — 404 if not found
2. Get `doi` from paper — return `{"related": [], "reason": "no_doi"}` if missing
3. Call `get_related_papers(doi, limit)`
4. For each result, check Neo4j for existing paper by doi (batch UNWIND query):
   ```cypher
   UNWIND $dois AS d
   MATCH (p:Paper {doi: d})
   RETURN d AS doi, p.id AS id
   ```
5. Set `in_library` and `library_paper_id` on each result
6. Return `{"related": results, "source_paper_id": paper_id}`

---

## Frontend

### New "Related" tab in `frontend/src/pages/PaperDetail.tsx`

Add a `Related` tab entry to the existing tab bar (alongside Overview, Chat, Notes, References, Graph).

**Lazy-load on tab focus** — only fetch when the user first opens the tab to avoid unnecessary API calls.

**Layout:**
```
┌─ Related Papers ──────────────────────────────────────┐
│ Papers Semantic Scholar recommends based on this work │
│                                                       │
│ ┌─ Result card ───────────────────────────────────┐   │
│ │ Title of related paper             [S2] 2023    │   │
│ │ Author A, Author B                              │   │
│ │ Venue · 142 citations                           │   │
│ │ Abstract snippet (2 lines)...                   │   │
│ │                                    [Add] / [→]  │   │
│ └─────────────────────────────────────────────────┘   │
│ ...up to 10 cards...                                  │
│                                                       │
│ [No DOI — recommendations unavailable]  ← if no DOI  │
└───────────────────────────────────────────────────────┘
```

**State:**
- `related: RelatedPaper[]`
- `loading: boolean`
- `hasFetched: boolean` — prevent re-fetching on tab revisit
- `addingIds: Set<string>`

**API helper** (add to `client.ts`):
```ts
export async function getRelatedPapers(paperId: string): Promise<{ related: RelatedPaper[] }>
export async function discoverAdd(url: string): Promise<IngestOut>  // reuse from T23
```

**TypeScript type** (add to `types/index.ts`):
```ts
interface RelatedPaper {
  title: string
  authors: string[]
  year: number | null
  abstract: string | null
  doi: string | null
  url: string
  venue: string | null
  citation_count: number | null
  in_library: boolean
  library_paper_id: string | null
}
```

---

## Done when
- [ ] `GET /papers/{id}/related` returns ≤10 recommendations for a paper with a DOI
- [ ] Papers already in library are marked `in_library: true`
- [ ] Papers without a DOI return `{"related": [], "reason": "no_doi"}`
- [ ] "Related" tab appears in PaperDetail and loads on first open
- [ ] "Add" button successfully adds a related paper and shows "View →"
- [ ] S2 unavailable (no paperId found) shows empty state gracefully
