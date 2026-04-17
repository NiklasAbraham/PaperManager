# T08 — Projects

**Phase:** 2 — Core data
**Depends on:** T05
**Touches:** `backend/db/queries/projects.py`, `backend/routers/projects.py`

## Goal
Create Project nodes. Add papers to projects. Link projects to each other.
A paper can belong to multiple projects.

## Cypher queries (db/queries/projects.py)

```python
def create_project(driver, data: dict) -> dict: ...
def get_project(driver, project_id: str) -> dict | None: ...
def list_projects(driver) -> list[dict]: ...
def update_project(driver, project_id: str, data: dict) -> dict: ...
def delete_project(driver, project_id: str): ...

def add_paper_to_project(driver, paper_id: str, project_id: str): ...
# MATCH (p:Paper {id:$pid}), (proj:Project {id:$projid})
# MERGE (p)-[:IN_PROJECT]->(proj)

def remove_paper_from_project(driver, paper_id: str, project_id: str): ...

def get_project_papers(driver, project_id: str) -> list[dict]: ...
# MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project {id:$id}) RETURN p

def link_projects(driver, project_a_id: str, project_b_id: str): ...
# MERGE (a)-[:RELATED_TO]-(b)
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/projects` | Create project |
| `GET` | `/projects` | List all projects |
| `GET` | `/projects/{id}` | Get project + its papers |
| `PATCH` | `/projects/{id}` | Update name/description/status |
| `DELETE` | `/projects/{id}` | Delete project (not papers) |
| `POST` | `/projects/{id}/papers` | Add paper to project `{"paper_id": "..."}` |
| `DELETE` | `/projects/{id}/papers/{paper_id}` | Remove paper from project |
| `POST` | `/projects/{a}/related/{b}` | Link two projects |

## Done when
- [ ] Can create a project and add papers to it
- [ ] `GET /projects/{id}` returns project + paper list
- [ ] A paper can appear in multiple projects
- [ ] Two projects can be linked via RELATED_TO

## Tests
`backend/tests/test_projects.py`
- Create project → 201
- Add paper → IN_PROJECT relationship in Neo4j
- Add same paper twice → still only 1 relationship (MERGE)
- Get project papers → returns correct paper
- Add paper to two projects → paper appears in both
- Delete project → papers still exist, just unlinked
- Link two projects → RELATED_TO exists
