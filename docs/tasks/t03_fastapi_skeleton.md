# T03 — FastAPI Skeleton

**Phase:** 1 — Foundation
**Depends on:** T01, T02
**Touches:** `backend/main.py`, `backend/models/schemas.py`

## Goal
A running FastAPI app with a health check endpoint and the Neo4j driver wired in.

## Steps

1. Create `backend/main.py`:
   - FastAPI app instance
   - Lifespan: open Neo4j driver on startup, close on shutdown
   - Mount placeholder routers (can be empty for now)
   - `GET /health` returns `{"status": "ok", "neo4j": "connected"}`

2. Create `backend/models/schemas.py`:
   - Empty for now, will grow as we add routers.
   - Add a `HealthResponse` Pydantic model.

3. Run the app:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

## Done when
- [ ] `uvicorn main:app --reload` starts without errors
- [ ] `GET http://localhost:8000/health` returns 200 `{"status": "ok"}`
- [ ] `GET http://localhost:8000/docs` shows the Swagger UI

## Tests
`backend/tests/test_health.py`
- Use `httpx.AsyncClient` with `app` directly (no live server needed)
- `GET /health` → 200, body contains `status: ok`
