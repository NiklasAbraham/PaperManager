# T23 — Literature Search UI (Discover Page)

**Phase:** 7 — Discovery & Intelligence
**Depends on:** T05, T13, T15
**Touches:** new `backend/routers/discover.py`, new `backend/services/literature_search.py`, new `frontend/src/pages/Discover.tsx`, `frontend/src/App.tsx`

## Goal
A dedicated search page where the user can query arXiv, Semantic Scholar, and PubMed by keyword and add any result to their library in one click — no URL needed.

---

## Backend

### New service: `backend/services/literature_search.py`

Unified result format returned by all sources:
```python
@dataclass
class SearchResult:
    title: str
    authors: list[str]
    year: int | None
    abstract: str | None
    doi: str | None          # used as the add-to-library URL
    url: str                 # canonical link for display
    source: str              # "arxiv" | "semantic_scholar" | "pubmed"
    in_library: bool = False
    library_paper_id: str | None = None
```

Functions:
```python
def search_arxiv(query: str, limit: int = 20) -> list[SearchResult]:
    """
    arXiv Atom API: http://export.arxiv.org/api/query
    params: search_query=all:{query}, max_results=limit, sortBy=submittedDate, sortOrder=descending
    Parse XML (ET), extract entry.id, title, author, summary, published date.
    doi = "arxiv:" + arxiv_id  (stripped from id URL)
    url = "https://arxiv.org/abs/{arxiv_id}"
    """

def search_semantic_scholar(query: str, limit: int = 20) -> list[SearchResult]:
    """
    Reuse _SS_BASE search already in metadata_lookup.py.
    GET /paper/search?query={query}&fields=title,authors,year,abstract,externalIds,venue&limit={limit}
    doi = externalIds.DOI or "arxiv:" + externalIds.ArXiv
    url = "https://www.semanticscholar.org/paper/{paperId}"
    """

def search_pubmed(query: str, limit: int = 20) -> list[SearchResult]:
    """
    Step 1: GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
              ?db=pubmed&term={query}&retmax={limit}&retmode=json
    Step 2: GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi
              ?db=pubmed&id={comma_joined_ids}&retmode=json
    doi = DocSum ArticleIds where IdType=="doi"
    url = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    """

def mark_in_library(results: list[SearchResult], driver) -> list[SearchResult]:
    """
    For each result with a doi, run a Neo4j MATCH to check if a Paper with that
    doi already exists. Sets result.in_library and result.library_paper_id.
    Use a single batched Cypher UNWIND query for efficiency.
    """
```

### New router: `backend/routers/discover.py`

Register in `backend/main.py` as `app.include_router(discover_router)`.

```
GET /discover/search
  query params: q (required), source=all|arxiv|s2|pubmed (default=all), limit=20
  Fans out to relevant search functions concurrently (asyncio.gather or ThreadPoolExecutor).
  Calls mark_in_library on combined results.
  Returns: list[SearchResultOut]  (same fields as SearchResult)
  Error: 422 if q is empty

POST /discover/add
  Body: { "url": str, "project_id": str | null }
  Delegates entirely to the existing ingest_from_url() logic in papers.py.
  Returns: IngestOut (same as POST /papers/from-url)
  Note: reuse the existing endpoint internally — do not duplicate logic.
```

---

## Frontend

### New page: `frontend/src/pages/Discover.tsx`

**Route:** `/discover` — add to `App.tsx` router and NavBar.

**Layout:**
```
┌─ NavBar ──────────────────────────────────────────────┐
│ Discover                                              │
├───────────────────────────────────────────────────────┤
│  [Search field ........................] [Source▼] [🔍]│
│  Sources: ● All  ○ arXiv  ○ Semantic Scholar  ○ PubMed│
├───────────────────────────────────────────────────────┤
│  23 results for "diffusion models"                    │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Title of paper                    [arXiv] 2024  │  │
│  │ Author A, Author B, Author C                    │  │
│  │ Abstract snippet (2 lines, truncated)...        │  │
│  │                          [✓ In library] / [Add] │  │
│  └─────────────────────────────────────────────────┘  │
│  ...more cards...                                     │
└───────────────────────────────────────────────────────┘
```

**State:**
- `query: string`
- `source: "all" | "arxiv" | "s2" | "pubmed"`
- `results: SearchResult[]`
- `loading: boolean`
- `addingIds: Set<string>` — track which papers are being added

**Key behaviours:**
- Search triggered on form submit (not on keystroke)
- "Add" button calls `POST /discover/add` with the result's URL; shows spinner while adding; on success shows "✓ In library" badge and links to the paper detail page
- Results with `in_library: true` show "View →" link instead of "Add"
- Source badge on each card (arXiv / S2 / PubMed) in a colour-coded chip
- Abstract truncated to 3 lines with expand toggle

**API helper** (add to `frontend/src/api/client.ts`):
```ts
export async function discoverSearch(q: string, source: string): Promise<SearchResult[]>
export async function discoverAdd(url: string, projectId?: string): Promise<IngestOut>
```

**TypeScript type** (add to `frontend/src/types/index.ts`):
```ts
interface SearchResult {
  title: string
  authors: string[]
  year: number | null
  abstract: string | null
  doi: string | null
  url: string
  source: "arxiv" | "semantic_scholar" | "pubmed"
  in_library: boolean
  library_paper_id: string | null
}
```

---

## Done when
- [ ] `GET /discover/search?q=transformers` returns results from all 3 sources
- [ ] Results correctly flagged `in_library: true` for papers already in Neo4j
- [ ] `POST /discover/add` successfully adds a paper and returns its id
- [ ] Discover page reachable via NavBar link
- [ ] "Add" button adds paper and immediately shows "View →" link
- [ ] Source filter works (selecting "arXiv only" only shows arXiv results)
- [ ] Empty query returns 422 error handled gracefully in UI
- [ ] No duplicate created if user adds a paper already in library (409 handled gracefully)
