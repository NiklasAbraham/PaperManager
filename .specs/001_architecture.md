# Architecture

## High-Level Overview

```
┌──────────────────────┐   HTTP / SSE    ┌──────────────────────────────┐
│   React Frontend     │ ◄─────────────► │   FastAPI Backend            │
│   (Vite :5173)       │                 │   (uvicorn :8000)            │
└──────────────────────┘                 └──────┬───────────────────────┘
                                                │
                        ┌───────────────────────┼───────────────────┐
                        │                       │                   │
                 ┌──────▼──────┐      ┌─────────▼──────┐  ┌────────▼────────┐
                 │  Neo4j Aura │      │ Google Drive   │  │ Anthropic /     │
                 │  (graph DB) │      │ (PDF storage)  │  │ Ollama (AI)     │
                 └─────────────┘      └────────────────┘  └─────────────────┘

┌──────────────────────┐   MCP stdio
│   Claude Desktop     │ ◄─────────────► backend/mcp_server.py (same services/db layer)
└──────────────────────┘
```

---

## The Shared Layer Principle

The most important architectural rule:

> **`db/queries/` and `services/` are framework-neutral.** `routers/` and `tools/` are two thin entry-point layers over the same logic.

This means every capability is available both via HTTP (browser) and via MCP tool calls (Claude Desktop) without code duplication.

---

## Module Map

### `routers/` — HTTP Entry Points

| Router | Prefix | Description |
|---|---|---|
| `papers.py` | `/papers` | Core CRUD, upload, URL ingest, chat, notes, references, tags, topics, authors |
| `people.py` | `/people` | Person CRUD + paper links + specialties |
| `tags.py` | `/tags` | Tag CRUD + AI suggestion |
| `topics.py` | `/topics` | Topic CRUD + rename |
| `projects.py` | `/projects` | Project CRUD + paper membership |
| `search.py` | `/search` | Full-text + filtered search |
| `graph.py` | `/graph` | Graph visualisation data + custom Cypher graph |
| `stats.py` | `/stats` | Library statistics |
| `cypher.py` | `/cypher` | Raw Cypher editor + AI assist + node delete |
| `export.py` | `/export` | BibTeX export |
| `backfill.py` | `/backfill` | Bulk AI enrichment (topics, summaries, figures, embeddings) |
| `knowledge_chat.py` | `/knowledge-chat` | Multi-paper chat with SSE streaming |
| `figures.py` | `/papers/{id}/figures` | Figure extraction + image serving + vision chat |
| `bulk_import.py` | `/papers/bulk-import` | Bulk JSON import with SSE progress |
| `literature.py` | `/literature` | Stream recent papers from arXiv / PubMed / bioRxiv |
| `discover.py` | `/discover` | Search external sources + add to library |
| `annotations.py` | `/papers/{id}/annotations` | PDF highlight annotations |
| `chapters.py` | `/papers/{id}/chapters` | Book / lecture chapter detection + chat |
| `blogs.py` | `/blogs` | Blog RSS management + post reader |
| `venues.py` | `/venues` | Venue browser |
| `claims.py` | `/papers/{id}/claims` | Claim extraction and search |
| `synthesis.py` | `/synthesis` | Cross-paper synthesis (Claude Opus) |
| `research_gaps.py` | `/research-gaps` | Research gap analysis (Claude Opus) |
| `author_tracker.py` | `/people/{id}/track` | Author auto-import tracking |
| `merge.py` | `/merge` | Duplicate detection + paper merge |
| `auth.py` | `/auth` | Login, JWT, user management |
| `users.py` | `/users` | User identity + per-user conversation history |
| `admin.py` | `/admin` | Maintenance + admin endpoints |

### `services/` — Business Logic

| File | Responsibility |
|---|---|
| `ai.py` | All Claude API calls — summarise, chat, topics, figures, claims, synthesis, gaps, compaction |
| `drive.py` | Upload/download files to Google Drive; OAuth flow |
| `pdf_parser.py` | Extract raw text with Docling; orchestrate 4-layer metadata extraction |
| `metadata_lookup.py` | Semantic Scholar + CrossRef API clients |
| `metadata_from_url.py` | URL/DOI/arXiv/PubMed/bioRxiv resolver |
| `figure_extractor.py` | Extract figures from PDF pages; generate captions (Docling/Ollama/Claude) |
| `note_parser.py` | Regex `@Name` and `#Topic` extraction from Markdown |
| `references.py` | Three-strategy reference extraction pipeline |
| `bulk_resolver.py` | Per-entry resolver for bulk import |
| `literature_search.py` | Keyword-based search across arXiv / PubMed / bioRxiv |
| `blog_fetcher.py` | Fetch and parse blog posts from RSS feeds / URLs |
| `book_chapter_parser.py` | Detect chapter boundaries in PDFs (Docling + AI) |
| `embeddings.py` | Generate Ollama (nomic-embed-text) embeddings |
| `person_enrichment.py` | Enrich Person nodes with affiliations and S2 author data |
| `web_search.py` | Web search helper for research gaps and synthesis |
| `auth.py` | JWT generation/validation, password hashing, user auth |
| `rate_limit.py` | In-memory sliding-window rate limiter |
| `user_ai_config.py` | Per-user AI model preferences |

### `db/queries/` — Cypher Layer

| File | Nodes managed |
|---|---|
| `papers.py` | Paper |
| `people.py` | Person |
| `topics.py` | Topic |
| `tags.py` | Tag |
| `notes.py` | Note + MENTIONS |
| `projects.py` | Project |
| `references.py` | CITES relationships |
| `figures.py` | Figure |
| `annotations.py` | Annotation |
| `chapters.py` | Chapter |
| `blogs.py` | Blog + BlogPost |
| `claims.py` | Claim |
| `conversations.py` | Conversation + Message |
| `users.py` | User |
| `search.py` | Full-text + filter search |
| `tables.py` | Table |

### `tools/` — MCP Tool Definitions

Thin FastMCP wrappers that delegate to `db/queries/` and `services/`. Defined in:
- `paper_tools.py` — search, get, chat, notes, tags, topics, people, status, rating, bookmark
- `note_tools.py` — read/write notes
- `tag_tools.py` — list tags, tag paper
- `person_tools.py` — list/create people, link to paper
- `project_tools.py` — list/create projects, add papers
- `ai_tools.py` — AI-powered MCP actions

---

## Paper Ingestion Flow

```
Browser: POST /papers/upload (PDF bytes)
  │
  ├─ PDFParser: extract_text() with Docling
  ├─ MetadataExtraction: 4-layer pipeline (see 003_ingestion.md)
  ├─ Drive: upload_pdf() → drive_file_id
  ├─ AI: summarize_paper() → summary
  ├─ AI: extract_claims() → Claim nodes
  ├─ DB: create_paper() → Paper node in Neo4j
  ├─ DB: link_authors(), link_topics()
  └─ Browser: PaperOut JSON
```

---

## Key Design Decisions

1. **Neo4j over SQL** — papers, people, topics, tags are a natural graph; enables path queries, co-authorship, topic clustering
2. **Tags as nodes** — `(Paper)-[:TAGGED]->(Tag)` for efficient "all papers with tag X" queries
3. **Topic ≠ Tag** — Topics are formal research areas linked to Person specialties; Tags are free-form personal labels
4. **Notes as graph nodes** — Notes carry `@mention` and `#topic` relationships; a text field on Paper would lose this
5. **INVOLVES with role property** — one relationship type with a `role` property keeps workflow states flexible (new roles don't require schema changes)
6. **Shared service layer** — MCP tools and HTTP routers call the same `db/` and `services/` code
7. **Prompts as files** — All AI prompt templates live in `prompts/` and are loaded fresh on each call; edit without restarting
8. **Vector embeddings on Paper nodes** — Ollama `nomic-embed-text` (768-dim) stored on `Paper.embedding`; `paper_embeddings` vector index enables semantic similarity search
9. **Metadata source tracking** — `metadata_source` field records which extraction layer was used per paper
10. **PDF upload is browser-only** — intentionally not exposed as an MCP tool (file upload via browser only)
