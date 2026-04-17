# T05 — Paper CRUD

**Phase:** 2 — Core data
**Depends on:** T03, T04
**Touches:** `backend/db/queries/papers.py`, `backend/routers/papers.py`, `backend/models/schemas.py`

## Goal
Create, read, and list Paper nodes in Neo4j via the API.
No PDF, no AI yet — just metadata.

## Schemas (schemas.py)

```python
class PaperCreate(BaseModel):
    title: str
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None

class PaperOut(BaseModel):
    id: str
    title: str
    year: int | None
    doi: str | None
    abstract: str | None
    summary: str | None
    drive_file_id: str | None
    created_at: str
```

## Cypher queries (db/queries/papers.py)

```python
def create_paper(driver, data: dict) -> dict: ...
# MERGE (p:Paper {id: $id}) SET p += $props RETURN p

def get_paper(driver, paper_id: str) -> dict | None: ...
# MATCH (p:Paper {id: $id}) RETURN p

def list_papers(driver, skip=0, limit=20) -> list[dict]: ...
# MATCH (p:Paper) RETURN p ORDER BY p.created_at DESC SKIP $skip LIMIT $limit
```

## API endpoints (routers/papers.py)

| Method | Path | Description |
|---|---|---|
| `POST` | `/papers` | Create a paper (metadata only) |
| `GET` | `/papers` | List papers, paginated |
| `GET` | `/papers/{id}` | Get single paper |
| `PATCH` | `/papers/{id}` | Update fields |
| `DELETE` | `/papers/{id}` | Delete paper node |

## Done when
- [ ] `POST /papers` with title + year creates a node in Neo4j
- [ ] `GET /papers/{id}` returns it
- [ ] `GET /papers` returns a list
- [ ] IDs are UUIDs generated server-side

## Tests
`backend/tests/test_papers.py`
- POST → 201, body has `id`
- GET by id → 200, matches posted data
- GET by id with unknown id → 404
- GET list → 200, is a list
- PATCH title → 200, updated title returned
- DELETE → 204, subsequent GET → 404
