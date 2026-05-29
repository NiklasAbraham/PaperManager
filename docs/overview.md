# PaperManager — Project Overview

A personal research knowledge management system with a graph database backend, AI-assisted summaries, Q&A, and a local web frontend.

---

## Goals

- Drop PDFs (papers, books, lecture decks) into the system → stored in Google Drive
- Auto-summarise papers via Claude; extract claims, topics, references, figures
- Tag papers with topics, free-form tags, and people
- Write Markdown notes per paper with `@Person` and `#Topic` mentions
- Chat with individual papers or across the entire library (Knowledge Chat)
- Filter and explore via projects, tags, topics, people, venues
- Visualise the knowledge graph of connections
- Discover new papers from arXiv, PubMed, and Semantic Scholar
- Track authors and auto-import their new publications
- Read and annotate technical blog posts alongside papers
- Highlight and annotate PDFs in-browser
- Find research gaps and synthesise insights across papers
- Detect and merge near-duplicate papers
- Use Claude Desktop to interact with the library via MCP tools

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Database | Neo4j Aura (cloud graph DB) |
| File storage | Google Drive API |
| AI (summaries, chat, synthesis) | Anthropic Claude API (Opus 4.6 / Haiku 4.5) |
| AI (metadata, captions, Cypher) | Ollama + llama3.2:3b (local) |
| AI (embeddings) | Ollama + nomic-embed-text (local, 768-dim) |
| Metadata APIs | Semantic Scholar + CrossRef (free, no key needed) |
| MCP server | FastMCP (exposes tools to Claude Desktop) |
| Frontend | React 19 + TypeScript + Vite + Tailwind CSS |

---

## Metadata Extraction Strategy

When a PDF is ingested, metadata is extracted in priority order:

1. **DOI/arXiv ID found** → Semantic Scholar API → CrossRef fallback
2. **Title found, no DOI** → S2 title search
3. **Nothing found** → Ollama local LLM (`llama3.2:3b`) on first 3 000 chars
4. **Ollama unavailable** → regex heuristics (first line = title, year regex)
5. **Abstract missing** → regex → Claude Haiku fallback

The `metadata_source` field on each Paper node records which path was used.

---

## Key Design Decisions

- Notes are separate graph nodes (not text fields on Paper) — enables `@mention` and `#topic` relationships
- Tags are free-form nodes — anything goes (source, status, context)
- Topics are formal research areas, separate from Tags; linked to Person specialties
- People are nodes with specialties; tracked authors auto-import new papers via Semantic Scholar
- Papers link to People via `INVOLVES {role}` for workflow states (shared_by, working_on, collaborating, etc.)
- Projects are nodes that can be related to each other; papers can belong to multiple projects
- User identity enables per-user conversations and attribution
- Blogs and BlogPosts are first-class graph nodes alongside Papers
- Chapters allow books and lecture decks to be navigated section by section
- Claims, Annotations, Figures, and Tables are extracted and stored as graph nodes
- Vector embeddings (768-dim, nomic-embed-text) on Paper nodes enable semantic similarity search
- All prompt templates live in `prompts/` as plain text — edit without restarting
- MCP tools and HTTP routers share the same `db/queries/` and `services/` layer

---

## Docs in this folder

- `overview.md` — this file
- `decisions.md` — architecture decisions log
- `technical/` — full technical reference (architecture, data model, AI pipelines, API, backend, frontend)
- `user-guide/` — user-facing how-to guides
- `tasks/` — historical task spec files from initial development

For developer/contributor context, see [`.specs/`](../.specs/).
