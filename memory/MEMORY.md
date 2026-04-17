# PaperManager — Claude Memory

## Project
Personal research paper management system.
Docs folder: `/Users/M350238/Desktop/PaperManager/docs/`

## Stack
- Backend: Python + FastAPI (hosted on Railway)
- DB: Neo4j Aura (cloud, free tier)
- Files: Google Drive API
- AI summaries/chat: Anthropic Claude API (claude-opus-4-6)
- AI metadata extraction: Ollama + llama3.2:3b (local)
- Metadata APIs: Semantic Scholar (preferred) + Crossref (fallback) — free, no key
- MCP: FastMCP
- Frontend: React + Vite + Tailwind (local dev on :5173)

## Build status — ALL TASKS COMPLETE ✓
- [x] T01-T04: Scaffold, Neo4j setup, FastAPI, schema
- [x] T05-T09: Paper/Person/Tag/Topic/Project CRUD + Notes
- [x] T10: PDF parser (pypdf + Ollama + heuristic chain)
- [x] T11: Google Drive integration (services/drive.py)
- [x] T12: Claude summarization (services/ai.py)
- [x] T13: Full ingest pipeline POST /papers/upload
- [x] T14: Chat with paper POST /papers/{id}/chat
- [x] T15: Search GET /search (fulltext + filters)
- [x] T16-T21: Frontend (Vite + React + Tailwind, all pages)
- [x] T22: MCP server (backend/mcp_server.py + tools/)

## Test status
62 unit tests passing (non-integration).
Run: `conda run --cwd /path/to/backend -n papermanager /path/to/python3 -m pytest -m "not integration"`
Integration tests exist (marked) — require live services.

## Key files
- backend/main.py — FastAPI app, routers
- backend/services/pdf_parser.py — metadata extraction chain
- backend/services/drive.py — Google Drive upload
- backend/services/ai.py — summarize_paper, chat_with_paper
- backend/services/note_parser.py — @Person / #Topic mention parser
- backend/mcp_server.py — MCP server entry point
- backend/tools/ — MCP tool modules (paper, note, tag, person, project, ai)
- frontend/src/ — React app (App.tsx, pages/, components/, api/, types/)
- .mcp.json — project-level MCP config for Claude Code

## Running the system
```bash
# Backend
conda run --cwd backend -n papermanager uvicorn main:app --reload

# Frontend
conda run --cwd frontend -n papermanager npm run dev

# MCP server
conda run --cwd . -n papermanager python backend/mcp_server.py
```

## MCP tools (17 total)
search_papers, get_paper_detail, add_paper_metadata,
get_note, add_note,
tag_paper_with, list_tags, add_topic, list_topics,
list_people, add_person, link_person_to_paper, get_person_papers,
list_projects, create_project, add_to_project, list_project_papers,
chat_with_paper

## Key architecture notes
- .env at project root; config.py resolves via Path(__file__).parent.parent
- Neo4j driver singleton — close_driver() NOT called in lifespan (breaks tests)
- pytest: pythonpath=. in pytest.ini; asyncio_mode=auto
- conda run needs --cwd and full python path (conda run doesn't activate env properly)
- pypdf (not pypdf2) for PDF text extraction
- Frontend needs node in PATH: `conda install nodejs` in papermanager env

## User preferences
- Concise communication
- Discuss design before coding
- Use conda for env management (papermanager env, Python 3.12)
