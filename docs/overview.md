# PaperManager — Project Overview

A personal research paper management system with a graph database backend,
AI-assisted summaries and Q&A, and a local web frontend.

## Goals
- Drop PDFs into the system → stored in Google Drive
- Auto-summarize papers via Claude
- Tag papers with topics, free-form tags, and people
- Write Markdown notes per paper with @Person and #Topic mentions
- Chat with individual papers
- Filter and explore via projects, tags, topics, people
- Visualize the graph of connections over time

## Stack
| Layer | Technology |
|---|---|
| Backend | Python + FastAPI |
| Database | Neo4j Aura (cloud, free tier) |
| File storage | Google Drive API |
| AI (summaries + chat) | Anthropic Claude API |
| AI (metadata extraction) | Ollama + llama3.2:3b (local, offline) |
| Metadata APIs | Semantic Scholar + Crossref (free, no key needed) |
| MCP server | FastMCP (exposes tools to Claude Code) |
| Frontend | React (local dev first, deploy later) |
| Backend hosting | Railway (or Render / Fly.io) |

## Metadata extraction strategy
When a PDF is ingested, metadata is extracted in priority order:
1. **DOI/arXiv ID found** → Semantic Scholar API (free, returns authors, topics, citations) or Crossref fallback
2. **No DOI** → Ollama local LLM (`llama3.2:3b`) reads the first page and returns structured JSON
3. **Ollama unavailable** → simple regex heuristics, user corrects in the UI

The `metadata_source` field on each Paper node records which path was used.

## Key design decisions
- Notes are separate nodes in the graph (not just text fields on Paper)
- Tags are free-form nodes — anything goes (source, status, context)
- Topics are formal research areas, separate from Tags
- People are nodes with specialties linked to Topics
- Papers link to People via INVOLVES {role} for workflow states
- Projects are nodes that can be related to each other
- Papers can belong to multiple projects

## Docs in this folder
- `overview.md` — this file
- `data_model.md` — full Neo4j graph schema
- `api_design.md` — backend API routes (TBD)
- `frontend_design.md` — UI layout and flows (TBD)
- `decisions.md` — architecture decisions log
