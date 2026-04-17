# T04 — Neo4j Constraints + Indexes

**Phase:** 1 — Foundation
**Depends on:** T02
**Touches:** `backend/db/connection.py` or a new `backend/db/schema.py`

## Goal
Run a one-time setup script that creates uniqueness constraints and full-text indexes
in the Neo4j Aura instance. This locks in the data model and speeds up queries.

## Constraints to create (uniqueness)

```cypher
CREATE CONSTRAINT paper_id IF NOT EXISTS
  FOR (p:Paper) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT person_id IF NOT EXISTS
  FOR (p:Person) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT topic_id IF NOT EXISTS
  FOR (t:Topic) REQUIRE t.id IS UNIQUE;

CREATE CONSTRAINT tag_id IF NOT EXISTS
  FOR (t:Tag) REQUIRE t.id IS UNIQUE;

CREATE CONSTRAINT venue_id IF NOT EXISTS
  FOR (v:Venue) REQUIRE v.id IS UNIQUE;

CREATE CONSTRAINT note_id IF NOT EXISTS
  FOR (n:Note) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT project_id IF NOT EXISTS
  FOR (p:Project) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT topic_name IF NOT EXISTS
  FOR (t:Topic) REQUIRE t.name IS UNIQUE;

CREATE CONSTRAINT tag_name IF NOT EXISTS
  FOR (t:Tag) REQUIRE t.name IS UNIQUE;
```

## Indexes to create (full-text search)

```cypher
CREATE FULLTEXT INDEX paper_search IF NOT EXISTS
  FOR (p:Paper) ON EACH [p.title, p.abstract, p.summary];

CREATE FULLTEXT INDEX note_search IF NOT EXISTS
  FOR (n:Note) ON EACH [n.content];
```

## Steps

1. Create `backend/db/schema.py` with a `run_schema_setup(driver)` function
   that executes all the above Cypher statements.

2. Call this function once from a CLI script or from app startup (idempotent — safe to run multiple times thanks to `IF NOT EXISTS`).

## Done when
- [ ] Script runs without errors on a fresh Aura instance
- [ ] Re-running the script does not error (idempotent)
- [ ] Constraints visible in Neo4j Aura console under Schema

## Tests
`backend/tests/test_schema.py`
- Run `run_schema_setup(driver)` twice — no errors
- Query `SHOW CONSTRAINTS` — expected constraint names are present
- Query `SHOW INDEXES` — expected index names are present
