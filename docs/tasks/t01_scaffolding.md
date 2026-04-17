# T01 — Project Scaffolding

**Phase:** 1 — Foundation
**Depends on:** nothing
**Touches:** root, `backend/`, `frontend/` (skeleton only)

## Goal
Create the folder structure, Python virtual environment, and install base dependencies.
The backend should be importable. The frontend should have a package.json ready.

## Steps

1. Create folder tree:
   ```
   backend/
     db/queries/
     routers/
     services/
     models/
     tools/
     tests/
       fixtures/      ← store test PDFs here
   frontend/src/
     api/
     types/
     components/
     pages/
   notes/
   ```

2. Create `backend/requirements.txt`:
   ```
   fastapi
   uvicorn[standard]
   neo4j
   python-dotenv
   pydantic
   pydantic-settings
   python-multipart
   pypdf2
   anthropic
   google-api-python-client
   google-auth-httplib2
   google-auth-oauthlib
   mcp[cli]
   ollama
   httpx
   pytest
   pytest-asyncio
   ```

   Also install Ollama itself (one-time, not a pip package):
   ```bash
   brew install ollama
   ollama pull llama3.2:3b
   ```

3. Create Python venv and install:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Create `.env.example` at root with all required keys (no values).

5. Create `backend/config.py` that reads `.env` via pydantic-settings.

6. Create `frontend/package.json` with React + Vite + Tailwind (no code yet).

## Done when
- [ ] `backend/` folder exists with all subfolders and `__init__.py` files
- [ ] `pip install -r requirements.txt` runs without errors
- [ ] `backend/config.py` can be imported without errors (even with missing env vars — just loads defaults or None)
- [ ] `.env.example` exists at root

## Tests
`backend/tests/test_config.py`
- Import `config.py` — no crash
- Check that expected settings fields exist (neo4j_uri, anthropic_api_key, etc.)
