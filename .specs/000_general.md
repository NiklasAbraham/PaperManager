# PaperManager — General Overview

## What It Is

PaperManager is a personal academic knowledge base. It lets you ingest research papers (PDF upload, URL/DOI/arXiv, bulk import), organise them with tags/topics/projects, chat with individual papers or your entire library using AI, and explore a knowledge graph of authors, papers, and topics.

It is built for a single primary user with optional teammate/multi-user support. Everything runs locally or behind a private domain.

---

## Core Features

| Feature | Summary |
|---|---|
| PDF upload | Drag-drop PDF → 4-layer metadata extraction → AI summary → figures → references |
| URL / DOI ingest | Paste arXiv, DOI, PubMed, bioRxiv URL → fetch metadata, no PDF stored |
| Bulk import | JSON list of URLs/DOIs/titles → streaming progress |
| Literature search | Query arXiv / PubMed / bioRxiv by keyword, import results |
| Blog reader | Register RSS feeds, import posts, AI-summarise, add to projects |
| Knowledge graph | WebGL force-graph visualisation of papers, authors, topics, tags, projects |
| Knowledge chat | Graph-aware multi-paper Q&A with `@mention` targeting, vector search, Cypher tool |
| Single-paper chat | Q&A over a paper's full text; also figure vision chat |
| Cypher editor | Raw Neo4j query editor with AI assist |
| MCP server | Claude Desktop integration — search, chat, annotate from Claude |
| Export | BibTeX, JSON |
| Auth | JWT-based login, admin-managed users, rate limiting |

---

## Tech Stack

### Backend
- **Python 3.11**, **FastAPI**, **uvicorn**
- **Neo4j Aura** — cloud graph database (free tier: 200k nodes / 400k relationships)
- **Google Drive API** — PDF and figure storage (OAuth desktop flow)
- **Anthropic SDK** — Claude Opus and Haiku for summaries, chat, analysis
- **Ollama** — local LLM (`llama3.2:3b`) for metadata, tags, captions; `nomic-embed-text` for embeddings
- **Docling** — PDF parsing, figure extraction, chapter detection
- **httpx**, **FastMCP**, **Pydantic v2**

### Frontend
- **React 19 + TypeScript**, **Vite**, **Tailwind CSS**
- **react-force-graph** (WebGL) for the knowledge graph
- **react-dropzone** for PDF upload
- **react-pdf** for the inline PDF viewer

### Infrastructure
- Dev: `start.sh` starts uvicorn (port 8000) + Vite (port 5173) + optional Ollama
- Prod: Docker Compose — Neo4j + FastAPI + Nginx/React; Traefik reverse proxy; hosted at `niklas-abraham.de`

---

## Repository Layout

```
PaperManager/
├── backend/             Python FastAPI application
│   ├── main.py          App entry; mounts all routers
│   ├── config.py        Env-var settings (Pydantic)
│   ├── mcp_server.py    MCP server entry point (separate process)
│   ├── db/              Neo4j driver + Cypher query modules
│   ├── routers/         FastAPI HTTP endpoints (~25 routers)
│   ├── services/        Business logic, API clients, AI calls
│   ├── models/          Pydantic request/response schemas
│   ├── tools/           MCP tool definitions (FastMCP)
│   └── prompts/         Plain-text AI prompt templates
├── frontend/            React + Vite SPA
│   └── src/
│       ├── pages/       Route-level views
│       ├── components/  Shared UI components
│       ├── api/         Typed fetch client
│       ├── types/       TypeScript types
│       └── contexts/    Settings + user context
├── docs/                Full documentation (MkDocs)
├── .specs/              This folder — developer context files
├── prompts/             AI prompt templates (backend reads these)
├── docker-compose.yml   Production deployment
├── start.sh             Local dev launcher
└── .env                 Environment variables (gitignored)
```

---

## Quick Start (Local Dev)

```bash
# 1. Clone
git clone <repo> && cd PaperManager

# 2. Python environment
conda create -n papermanager python=3.11 -y
conda activate papermanager
pip install -r backend/requirements.txt

# 3. Frontend
cd frontend && npm install && cd ..

# 4. Environment
cp .env.example .env
# Fill in: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
#          GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_DRIVE_FOLDER_ID,
#          ANTHROPIC_API_KEY, JWT_SECRET_KEY

# 5. Start everything
./start.sh
# Backend: http://localhost:8000
# Frontend: http://localhost:5173
# API docs: http://localhost:8000/docs

# 6. Create the admin user
cd backend && python scripts/create_default_user.py && cd ..

# 7. Login at http://localhost:5173/login
```

`start.sh` writes logs to `/tmp/papermanager-backend.log` and `/tmp/papermanager-frontend.log`.

---

## Environment Variables

```env
# Neo4j
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# Google Drive (OAuth desktop app credentials)
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
GOOGLE_DRIVE_FOLDER_ID=xxxx

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxx

# Anthropic Foundry (optional enterprise gateway)
ANTHROPIC_WORK_API_KEY=xxxx
ANTHROPIC_WORK_BASE_URL=https://your-foundry-gateway.com/...

# App
BACKEND_PORT=8000
FRONTEND_URL=http://localhost:5173
JWT_SECRET_KEY=replace-with-long-random-secret
TRUSTED_HOSTS=localhost,127.0.0.1
TRUST_PROXY_HEADERS=false

# Rate limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_DEFAULT_REQUESTS=120
RATE_LIMIT_DEFAULT_WINDOW_SECONDS=60
RATE_LIMIT_AUTH_REQUESTS=10
RATE_LIMIT_AUTH_WINDOW_SECONDS=60
RATE_LIMIT_EXEMPT_PATHS=/docs,/redoc,/openapi.json
RATE_LIMIT_AUTH_PATHS=/auth/login

# Ollama
OLLAMA_MODEL=llama3.2:3b

# Corporate network (optional)
SSL_VERIFY=true
SSL_CA_BUNDLE=/path/to/corporate-ca.pem
```

**Google Drive first run:** the backend opens a browser OAuth window. Credentials saved to `backend/token.json`.

---

## Authentication

- All pages require a valid JWT bearer token
- Token stored in `localStorage`, validated via `GET /auth/me` on load
- 401 responses redirect to `/login`
- Admin user (`niklas`) can create/update/delete users and merge duplicate user accounts
- Default user created via `python scripts/create_default_user.py`
