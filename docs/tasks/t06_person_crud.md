# T06 — Person CRUD + Specialties

**Phase:** 2 — Core data
**Depends on:** T05
**Touches:** `backend/db/queries/people.py`, `backend/routers/people.py`, `backend/models/schemas.py`

## Goal
Create and manage Person nodes. Link people to papers via AUTHORED_BY and INVOLVES.
Link people to topics via SPECIALIZES_IN.

## Schemas

```python
class PersonCreate(BaseModel):
    name: str
    affiliation: str | None = None
    email: str | None = None

class PersonOut(BaseModel):
    id: str
    name: str
    affiliation: str | None
    email: str | None

class InvolvesLink(BaseModel):
    person_id: str
    role: str   # "feedback_needed" | "working_on" | "shared_by" | ...
```

## Cypher queries (db/queries/people.py)

```python
def create_person(driver, data: dict) -> dict: ...
def get_person(driver, person_id: str) -> dict | None: ...
def list_people(driver) -> list[dict]: ...

def link_author(driver, paper_id: str, person_id: str): ...
# MATCH (paper:Paper {id:$pid}), (person:Person {id:$peid})
# MERGE (paper)-[:AUTHORED_BY]->(person)

def link_involves(driver, paper_id: str, person_id: str, role: str): ...
# MERGE (paper)-[:INVOLVES {role: $role}]->(person)

def link_specializes(driver, person_id: str, topic_id: str): ...
# MERGE (person)-[:SPECIALIZES_IN]->(topic)

def get_papers_by_person(driver, person_id: str) -> list[dict]: ...
# Returns papers AUTHORED_BY or INVOLVES this person
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/people` | Create person |
| `GET` | `/people` | List all people |
| `GET` | `/people/{id}` | Get person + their papers |
| `POST` | `/papers/{id}/authors` | Link a person as author |
| `POST` | `/papers/{id}/involves` | Link a person with a role |
| `POST` | `/people/{id}/specialties` | Link person to a topic |

## Done when
- [ ] Can create a Person node
- [ ] Can link a Person as author of a Paper → AUTHORED_BY relationship exists in Neo4j
- [ ] Can link a Person to a Paper with a role → INVOLVES {role} exists
- [ ] Can link a Person to a Topic → SPECIALIZES_IN exists
- [ ] GET /people/{id} returns their linked papers

## Tests
`backend/tests/test_people.py`
- Create person → 201
- Link as author → relationship exists (verify with Cypher)
- Link with role "feedback_needed" → INVOLVES relationship has correct role
- Get person's papers → list includes the linked paper
- Link to topic → SPECIALIZES_IN exists
