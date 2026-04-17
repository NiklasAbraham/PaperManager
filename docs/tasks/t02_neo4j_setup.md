# T02 — Neo4j Aura Setup + Connection

**Phase:** 1 — Foundation
**Depends on:** T01
**Touches:** `backend/db/connection.py`, `.env`

## Goal
Create a Neo4j Aura free-tier instance and verify the Python driver can connect to it.

## Steps

1. Go to https://neo4j.com/cloud/aura/ and create a free AuraDB instance.
   - Save the connection URI, username, and password into `.env`.

2. Create `backend/db/connection.py`:
   - A function `get_driver()` that returns a Neo4j `Driver` singleton.
   - A function `close_driver()` for cleanup on app shutdown.
   - Use `neo4j.GraphDatabase.driver(uri, auth=(user, password))`.

3. Add lifespan events to `main.py` (when we create it in T03) that call these.

## Done when
- [ ] Neo4j Aura instance is running
- [ ] `.env` contains `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- [ ] `connection.py` exists and is importable

## Tests
`backend/tests/test_connection.py`
- Call `get_driver().verify_connectivity()` — must not raise
- Run a simple Cypher: `RETURN 1 AS n` — returns `n == 1`

## Notes
- Neo4j Aura free tier allows 1 instance, 200k nodes, 400k relationships.
- The URI format is `neo4j+s://xxxx.databases.neo4j.io`.
- Store credentials only in `.env`, never commit them.
