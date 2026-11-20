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
| Library search | Ranked search over titles, authors, topics, tags, notes, highlights, claims, full text; type-ahead; optional hybrid mode with embeddings from the vector store, default model bge-small (`.specs/012_search.md`) |
| Literature search | Query arXiv / PubMed / bioRxiv by keyword, import results |
| Blog reader | Register RSS feeds, import posts, AI-summarise, add to projects |
| Knowledge graph | WebGL force-graph visualisation of papers, authors, topics, tags, projects |
| Knowledge chat | Graph-aware multi-paper Q&A with `@mention` targeting, vector search, Cypher tool |
| Single-paper chat | Q&A over a paper's full text; also figure vision chat |
| Cypher editor | Raw Neo4j query editor with AI assist |
| Conference explorer | NeurIPS / ICML / ICLR / CVPR / ACL / ... by institution and by topic; data on disk, own saved vectors (default bge-small on CPU; `CONFERENCE_EMBED_MODEL`) (`.specs/011_conferences.md`) |
| Paper feed | Optional (`PAPER_FEED`, off by default): daily digest of new arXiv / bioRxiv / medRxiv papers, ranked per user by a numpy logistic regression on the library's signals (`.specs/018_paper_feed.md`) |
| Vector store | One store (`backend/services/vectorstore/`) for every embedding index: namespaces `library`, `feed`, `feed_library`, each recording the model that built it so vectors of two models are never mixed; numpy backend by default, optional LanceDB (`.specs/019_vector_store.md`) |
| Switching the embedding model | `EMBED_MODEL` (default `BAAI/bge-small-en-v1.5`); an automatic rebuild on the CPU, or bulk embedding on any GPU machine (`scripts/vectors_export.py`, `embed_bulk.py`, `vectors_import.py`, `vectors_rollback.py`) with adoption on start and a rollback; `scripts/embedder_benchmark.py` compares models on a library (`.specs/019_vector_store.md`, `docs/user-guide/switching-the-embedding-model.md`) |
| Similar papers | Write or paste an abstract (also one for a paper that does not exist yet) and get the nearest papers of the library and the feed with cosine scores; page `/similar`, `POST /search/similar`, MCP tools `find_similar_papers` and `papers_like` (`.specs/020_similar_search.md`) |
| Abstract backfill | Admin tool and CLI that fill missing abstracts of papers that have a DOI from OpenAlex, Semantic Scholar, arXiv and Crossref, with a title check, dry run by default and an undo (`.specs/021_abstract_backfill.md`) |
| MCP server | Claude Desktop integration — search, chat, annotate, find similar papers from Claude (44 tools) |
| Export | BibTeX, JSON |
| Auth | JWT-based login, admin-managed users, rate limiting |

---

## Tech Stack

### Backend
- **Python 3.11**, **FastAPI**, **uvicorn**
- **Neo4j Aura** — cloud graph database (free tier: 200k nodes / 400k relationships)
- **Google Drive API** — PDF and figure storage (OAuth desktop flow)
- **Anthropic SDK** — Claude Opus and Haiku for summaries, chat, analysis
- **Ollama** — local LLM (`llama3.2:3b`) for metadata, tags, captions
- **Embeddings** — `transformers` + `torch` on the CPU, default **BAAI/bge-small-en-v1.5** (384-dim, `EMBED_MODEL`) for library search, the paper feed, similar papers and the conference explorer; vectors live in the vector store (`.specs/019_vector_store.md`). The older per-paper vector on `Paper.embedding` (768-dim, Neo4j index `paper_embeddings`, used by the knowledge chat's semantic tool) comes from the LiteLLM embeddings API (`LITELLM_EMBED_MODEL`, empty = off)
- **Docling** — PDF parsing, figure extraction, chapter detection
- **httpx**, **FastMCP**, **Pydantic v2**

### Frontend
- **React 19 + TypeScript**, **Vite**, **Tailwind CSS**
- **react-force-graph** (WebGL) for the knowledge graph
- **react-dropzone** for PDF upload
- **react-pdf** for the inline PDF viewer

### Infrastructure
- Dev: `start.sh` starts uvicorn (port 8000) + Vite (port 5173) + optional Ollama
- Prod: Docker Compose — Neo4j + FastAPI + Nginx/React; Traefik reverse proxy; hosted at `<your-domain>`

---

## Repository Layout

```
PaperManager/
├── backend/             Python FastAPI application
│   ├── main.py          App entry; mounts all routers
│   ├── config.py        Env-var settings (Pydantic)
│   ├── mcp_server.py    MCP server entry point (separate process)
│   ├── db/              Neo4j driver + Cypher query modules
│   ├── routers/         FastAPI HTTP endpoints (~40 routers)
│   ├── services/        Business logic, API clients, AI calls; feed/ (paper feed),
│   │                    vectorstore/ (embedding indexes), library_search/, conferences/,
│   │                    similar_search.py, abstract_backfill.py
│   ├── models/          Pydantic request/response schemas
│   ├── tools/           MCP tool definitions (FastMCP)
│   ├── scripts/         Operator CLIs: user setup, backfill_abstracts.py, vectors_*.py,
│   │                    embed_bulk.py, embedder_benchmark.py, ...
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
├── docker-compose.example.yml   Production deployment template
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

# Embedding model and vector store (all optional; defaults in .specs/019_vector_store.md)
EMBED_MODEL=BAAI/bge-small-en-v1.5      # EMBED_DIM / EMBED_POOLING / EMBED_QUERY_PREFIX / EMBED_DOC_PREFIX only for a model not in the built-in list
CONFERENCE_EMBED_MODEL=                 # conference explorer's model; empty = follows EMBED_MODEL
VECTOR_STORE=exact                      # or lance (needs the lancedb package)
VECTOR_STORE_DIR=/data/vectors
VECTOR_STORE_KEEP_GENERATIONS=2         # generations kept for a rollback after a model switch, live one included
LITELLM_EMBED_MODEL=                    # legacy Paper.embedding via LiteLLM; empty = off

# Paper feed (optional, off by default; .specs/018_paper_feed.md)
PAPER_FEED=false
PAPER_FEED_DIR=/data/feed
PAPER_FEED_INTERVAL=21600
PAPER_FEED_RETENTION_DAYS=30
PAPER_FEED_MAX_PER_REFRESH=2000
PAPER_FEED_CONTACT=                     # added to the User-Agent sent to arXiv / bioRxiv

# Abstract backfill (.specs/021_abstract_backfill.md)
ABSTRACT_BACKFILL_CONTACT=              # e-mail or URL for the User-Agent / mailto of OpenAlex, Crossref, ...

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
