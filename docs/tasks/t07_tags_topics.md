# T07 — Tags and Topics

**Phase:** 2 — Core data
**Depends on:** T05
**Touches:** `backend/db/queries/tags.py`, `backend/db/queries/topics.py`, `backend/routers/tags.py`, `backend/routers/topics.py`

## Goal
Create Tag and Topic nodes. Link them to papers.
Tags are free-form. Topics are formal research areas, also linked to people via SPECIALIZES_IN.

## Key distinction
- `Tag` — personal, informal, anything: "linkedin", "to-read", "from_karin", "urgent"
- `Topic` — research area: "machine learning", "graph neural networks", "NLP"

Both use MERGE so they are created if they don't exist (no duplicates by name).

## Cypher queries

```python
# tags.py
def get_or_create_tag(driver, name: str) -> dict: ...
# MERGE (t:Tag {name: $name}) ON CREATE SET t.id = $id RETURN t

def tag_paper(driver, paper_id: str, tag_name: str): ...
# MERGE (t:Tag {name: $name})
# MATCH (p:Paper {id: $id})
# MERGE (p)-[:TAGGED]->(t)

def untag_paper(driver, paper_id: str, tag_name: str): ...
def list_tags(driver) -> list[dict]: ...   # all tags + paper count
def papers_by_tag(driver, tag_name: str) -> list[dict]: ...

# topics.py  (same pattern)
def get_or_create_topic(driver, name: str) -> dict: ...
def link_paper_topic(driver, paper_id: str, topic_name: str): ...
def list_topics(driver) -> list[dict]: ...
def papers_by_topic(driver, topic_name: str) -> list[dict]: ...
def link_related_topics(driver, topic_a: str, topic_b: str): ...
# MERGE (a)-[:RELATED_TO]-(b)
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/tags` | All tags with paper count |
| `GET` | `/tags/{name}/papers` | Papers with this tag |
| `POST` | `/papers/{id}/tags` | Add tag to paper `{"name": "linkedin"}` |
| `DELETE` | `/papers/{id}/tags/{name}` | Remove tag from paper |
| `GET` | `/topics` | All topics |
| `GET` | `/topics/{name}/papers` | Papers about this topic |
| `POST` | `/papers/{id}/topics` | Add topic to paper |
| `POST` | `/topics/{a}/related/{b}` | Mark two topics as related |

## Done when
- [ ] Tags are created on first use (MERGE, no duplicates)
- [ ] `GET /tags` shows all tags with how many papers each has
- [ ] Can tag and untag a paper
- [ ] Topics work the same way
- [ ] `GET /topics/{name}/papers` returns correct papers

## Tests
`backend/tests/test_tags_topics.py`
- Tag a paper twice with same tag → only 1 relationship
- GET tags → includes tag with count=1
- Untag → tag-paper relationship gone (tag node may remain)
- Tag two papers → GET tag papers returns both
- Related topics → RELATED_TO relationship exists (undirected)
