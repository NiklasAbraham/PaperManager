# PaperManager — Project Overview

A personal research knowledge management system with a graph database backend,
AI-assisted summaries, Q&A, and a local web frontend.

## Goals

- Drop PDFs (papers, books, lecture decks) into the system → stored in Google Drive
- Auto-summarize papers via Claude; extract claims, topics, references, figures
- Tag papers with topics, free-form tags, and people
- Write Markdown notes per paper with @Person and #Topic mentions
- Chat with individual papers or across the entire library (Knowledge Chat)
- Filter and explore via projects, tags, topics, people, venues
- Visualize the knowledge graph of connections
- Discover new papers from arXiv, PubMed, and Semantic Scholar
- Track authors and auto-import their new publications
- Read and annotate technical blog posts alongside papers
- Highlight and annotate PDFs in-browser
- Find research gaps and synthesize insights across papers
- Detect and merge near-duplicate papers

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Database | Neo4j Aura (cloud graph DB) |
| File storage | Google Drive API |
| AI (summaries, chat, synthesis) | Anthropic Claude API (Opus 4.6 / Haiku 4.5) |
| AI (metadata, captions, Cypher) | Ollama + llama3.2:3b (local) |
| Metadata APIs | Semantic Scholar + CrossRef (free, no key) |
| MCP server | FastMCP (exposes tools to Claude Desktop) |
| Frontend | React 19 + TypeScript + Vite + Tailwind CSS |

## Metadata extraction strategy

When a PDF is ingested, metadata is extracted in priority order:

1. **DOI/arXiv ID found** → Semantic Scholar API → CrossRef fallback
2. **Title found, no DOI** → S2 title search
3. **Nothing found** → Ollama local LLM (`llama3.2:3b`) on first 3 000 chars
4. **Ollama unavailable** → regex heuristics (first line = title, year regex)
5. **Abstract missing** → regex → Claude Haiku fallback

The `metadata_source` field on each Paper node records which path was used.

## Key design decisions

- Notes are separate graph nodes (not text fields on Paper) — enables @mention and #topic relationships
- Tags are free-form nodes — anything goes (source, status, context)
- Topics are formal research areas, separate from Tags
- People are nodes with specialties linked to Topics; tracked authors auto-import new papers
- Papers link to People via `INVOLVES {role}` for workflow states
- Projects are nodes that can be related to each other
- Papers can belong to multiple projects
- User identity enables per-user conversations and attribution
- Blogs and BlogPosts are first-class graph nodes alongside Papers
- Chapters allow books and lecture decks to be navigated section by section
- Claims, Annotations, and Figures are extracted and stored as graph nodes
- Vector embeddings on Paper nodes enable semantic similarity search

## Docs in this folder

- `overview.md` — this file
- `decisions.md` — architecture decisions log
- `data_model.md` — legacy schema reference (see `technical/data-model.md` for current)
- `technical/` — current technical reference
- `user-guide/` — user-facing how-to guides
