# T09 — Notes + Mention Parser

**Phase:** 2 — Core data
**Depends on:** T05, T06, T07
**Touches:** `backend/services/note_parser.py`, `backend/db/queries/notes.py`, `backend/routers/notes.py`

## Goal
Save markdown notes per paper. On every save, parse @Name and #Topic mentions
and create MENTIONS relationships in Neo4j automatically.

## note_parser.py

Scans markdown text for:
- `@FirstLast` or `@First_Last` → Person mentions
- `#topic-name` or `#TopicName` → Topic mentions

```python
def parse_mentions(content: str) -> dict:
    # returns {"people": ["Nele", "Jan"], "topics": ["machine learning"]}
```

Rules:
- `@` followed by one or more words (until whitespace or punctuation)
- `#` followed by one or more words/hyphens
- Case-insensitive matching against existing Person names and Topic names in Neo4j
- If no matching node found, still return the raw mention (can create stub nodes)

## Cypher queries (db/queries/notes.py)

```python
def create_note(driver, paper_id: str, content: str) -> dict: ...
# Creates Note node, creates HAS_NOTE relationship

def update_note(driver, note_id: str, content: str) -> dict: ...
# Updates content, updated_at

def get_note(driver, note_id: str) -> dict | None: ...

def get_paper_note(driver, paper_id: str) -> dict | None: ...
# Each paper has at most one note (1:1 for now)

def set_mentions(driver, note_id: str, person_names: list, topic_names: list): ...
# Deletes old MENTIONS, creates new ones
# MATCH (n:Note {id:$id})-[r:MENTIONS]->() DELETE r
# For each person name: MATCH (p:Person) WHERE toLower(p.name) CONTAINS toLower($name) ...
# MERGE (n)-[:MENTIONS]->(p)
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/papers/{id}/note` | Get note for a paper |
| `PUT` | `/papers/{id}/note` | Create or update note (upsert) |

On every PUT:
1. Save `content` to Note node
2. Run `parse_mentions(content)`
3. Resolve names against Neo4j
4. Call `set_mentions()` to update relationships

## Done when
- [ ] PUT note saves markdown content to Neo4j
- [ ] @Jan in a note creates MENTIONS → Person "Jan" relationship
- [ ] #MachineLearning creates MENTIONS → Topic "Machine Learning"
- [ ] Editing a note updates MENTIONS (old ones removed, new ones added)
- [ ] GET returns current note content

## Tests
`backend/tests/test_note_parser.py`
- `parse_mentions("Hello @Jan, see #NLP results")` → `{people: ["Jan"], topics: ["NLP"]}`
- `parse_mentions("no mentions here")` → `{people: [], topics: []}`
- Multiple mentions of same person → deduplicated

`backend/tests/test_notes.py`
- PUT note with @Nele → MENTIONS relationship to Person "Nele"
- PUT note again without @Nele → MENTIONS relationship removed
- GET note → returns content
