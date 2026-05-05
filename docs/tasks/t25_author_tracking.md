# T25 — Author Tracking

**Phase:** 7 — Discovery & Intelligence
**Depends on:** T06, T13
**Touches:** `backend/db/queries/people.py`, `backend/routers/people.py`, new `backend/routers/author_tracker.py`, `frontend/src/pages/People.tsx`, `frontend/src/pages/PaperDetail.tsx`

## Goal
Mark any author as "tracked". A nightly (or manually triggered) job checks Semantic Scholar for papers by that author not yet in the library and auto-imports them, tagging them `from-author-tracker`.

---

## Backend

### Schema changes — `backend/db/schema.py`

Add on startup (idempotent):
```cypher
CREATE CONSTRAINT person_id_unique IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE
```
No structural constraint changes needed — just use new properties on existing Person nodes.

### Person node new properties
- `tracked: bool` — default `false`
- `s2_author_id: str | None` — Semantic Scholar author ID (populated when available)

### Update `backend/services/metadata_lookup.py`

```python
def _parse_s2_authors(raw: list) -> tuple[list[str], list[dict]]:
    # EXISTING — extend to also return authorId
    # detail_list entries now include: {name, affiliation, s2_author_id}
    # s2_author_id = a.get("authorId")  (already in S2 API response)
```

### Update `backend/db/queries/people.py`

```python
def get_or_create_person_with_affiliation(driver, name: str, affiliation: str | None,
                                          s2_author_id: str | None = None) -> dict:
    """
    Existing function — add optional s2_author_id parameter.
    On MERGE, SET p.s2_author_id = $s2_author_id only if $s2_author_id IS NOT NULL.
    """

def set_person_tracked(driver, person_id: str, tracked: bool) -> dict:
    """MATCH (p:Person {id: $id}) SET p.tracked = $tracked RETURN p"""

def list_tracked_people(driver) -> list[dict]:
    """MATCH (p:Person {tracked: true}) RETURN p"""

def get_person_library_dois(driver, person_id: str) -> set[str]:
    """
    MATCH (p:Person {id: $id})<-[:AUTHORED_BY]-(paper:Paper)
    WHERE paper.doi IS NOT NULL
    RETURN collect(paper.doi) AS dois
    """
```

### New router: `backend/routers/author_tracker.py`

Register in `main.py` as `app.include_router(author_tracker_router)`.

```
PATCH /people/{person_id}/track
  Body: { "tracked": bool }
  Calls set_person_tracked(); returns updated person dict.

GET /people/{person_id}/new-papers
  Checks S2 for papers by this person not already in library.
  Returns list of SearchResult-like dicts (same shape as T23/T24).
  Does NOT auto-import — just previews.

POST /author-tracker/check-all
  Runs the full tracking job for all tracked authors.
  Idempotent — safe to call multiple times.
  Returns { "checked": int, "new_papers_imported": int, "authors": [...] }
```

### Tracking job logic (`check_all`)

```python
S2_AUTHOR_PAPERS = "https://api.semanticscholar.org/graph/v1/author/{authorId}/papers"
FIELDS = "title,year,externalIds,abstract,venue,authors"

def check_tracked_authors(driver) -> dict:
    tracked = list_tracked_people(driver)
    total_imported = 0

    for person in tracked:
        s2_id = person.get("s2_author_id")
        if not s2_id:
            continue  # skip — no S2 link yet

        # Fetch recent papers from S2
        r = httpx.get(S2_AUTHOR_PAPERS.format(authorId=s2_id),
                      params={"fields": FIELDS, "limit": 20}, timeout=15)
        papers = r.json().get("data", [])

        known_dois = get_person_library_dois(driver, person["id"])

        for p in papers:
            ext = p.get("externalIds") or {}
            doi = ext.get("DOI") or ("arxiv:" + ext["ArXiv"] if ext.get("ArXiv") else None)
            if not doi or doi in known_dois:
                continue
            # Ingest via existing pipeline
            try:
                url = _doi_to_url(doi)  # "https://doi.org/{doi}" or "https://arxiv.org/abs/{id}"
                meta = resolve_url(url)
                if not meta or not meta.get("title"):
                    continue
                paper = merge_paper_by_doi(driver, {...})
                tag_paper(driver, paper["id"], "from-author-tracker")
                link_author(driver, paper["id"], person["id"])
                total_imported += 1
            except Exception:
                continue

    return {"checked": len(tracked), "new_papers_imported": total_imported}
```

### Auto-run option (cron trigger)
The `POST /author-tracker/check-all` endpoint can be called by an external cron job or by the frontend Settings page on a schedule. No daemon needed — stateless endpoint.

A simple shell cron on the server:
```
0 7 * * * curl -X POST http://localhost:8000/author-tracker/check-all
```

---

## Frontend

### People page — `frontend/src/pages/People.tsx`

- Add a "Track" toggle (star icon / switch) on each person card/row
- Tracked authors show a star indicator
- "Tracked" filter tab: shows only tracked people
- Show a paper count badge "3 new" if unread tracked-author papers exist (optional, requires a separate query)

### PaperDetail — author list in Overview tab

Add a small "Track" icon button next to each author name in the authors list.

### Settings page (optional enhancement)
- "Run author check now" button → calls `POST /author-tracker/check-all`
- Shows last-run result

### API helpers (add to `client.ts`)
```ts
export async function setPersonTracked(personId: string, tracked: boolean): Promise<Person>
export async function getPersonNewPapers(personId: string): Promise<SearchResult[]>
export async function runAuthorTrackerCheck(): Promise<{ checked: number, new_papers_imported: number }>
```

---

## Done when
- [ ] `PATCH /people/{id}/track` sets `tracked: true/false` on Person node
- [ ] `s2_author_id` is stored on Person nodes created from S2 metadata
- [ ] `GET /people/{id}/new-papers` returns papers not in library
- [ ] `POST /author-tracker/check-all` imports new papers and tags them `from-author-tracker`
- [ ] People page shows Track toggle; tracked authors visually distinct
- [ ] PaperDetail author names have Track button
- [ ] Running check twice doesn't create duplicate papers (idempotent via merge_paper_by_doi)
