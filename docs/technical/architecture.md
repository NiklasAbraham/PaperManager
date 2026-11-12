# Architecture

This page describes the overall system design of PaperManager, how the modules interact, and the key architectural principles.

---

## High-Level Overview

```mermaid
graph TB
    subgraph "User Interfaces"
        Browser["Browser\n(React + Vite :5173)"]
        ClaudeDesktop["Claude Desktop\n(MCP Client)"]
    end

    subgraph "Backend — FastAPI :8000"
        Routers["routers/\n(HTTP endpoints)"]
        MCPTools["tools/\n(MCP tool handlers)"]
        Services["services/\n(business logic)"]
        DBQueries["db/queries/\n(Cypher)"]
    end

    subgraph "External Services"
        Neo4j["Neo4j Aura\n(Graph DB)"]
        Drive["Google Drive\n(PDF / Figure storage)"]
        S2["Semantic Scholar\n(Metadata / Citations)"]
        Claude["Anthropic Claude\n(Summaries / Chat / Analysis)"]
        Ollama["Ollama\n(Local LLM)"]
    end

    Browser <-->|"HTTP / SSE"| Routers
    ClaudeDesktop <-->|"MCP stdio"| MCPTools
    MCPTools --> Services
    MCPTools --> DBQueries
    Routers --> Services
    Routers --> DBQueries
    DBQueries <--> Neo4j
    Services --> Drive
    Services --> S2
    Services --> Claude
    Services --> Ollama
```

---

## The Shared Layer Principle

The most important architectural rule in PaperManager:

> **`db/queries/` and `services/` are framework-neutral.** Neither FastAPI nor MCP specifics leak into them. `routers/` and `tools/` are two different entry points over the same logic.

This means every capability is available both via HTTP (for the browser) and via MCP tool calls (for Claude Desktop), without any code duplication.

---

## Module Map

### routers/

| Router | Prefix | Description |
| ------ | ------ | ----------- |
| `papers.py` | `/papers` | Core paper CRUD, upload, URL ingest, chat, notes, references |
| `people.py` | `/people` | Person CRUD + paper links |
| `tags.py` | `/tags` | Tag CRUD + paper tagging |
| `topics.py` | `/topics` | Topic CRUD + rename |
| `projects.py` | `/projects` | Project CRUD + paper membership |
| `search.py` | `/search` | Full-text + filter search |
| `graph.py` | `/graph` | Graph visualisation data + admin Cypher query (`/graph/query`) |
| `stats.py` | `/stats` | Library statistics |
| `cypher.py` | `/cypher` | Schema, AI assist, raw run, node delete (admin only) |
| `export.py` | `/export` | BibTeX export |
| `backfill.py` | `/backfill` | Bulk AI enrichment (topics, summaries, figures) |
| `knowledge_chat.py` | `/knowledge-chat` | Multi-paper chat (SSE streaming) |
| `figures.py` | `/papers/{id}/figures` | Figure extraction + image serving |
| `bulk_import.py` | `/bulk-import` | Bulk import from BibTeX / DOI list (SSE) |
| `literature.py` | `/literature` | Stream recent papers from arXiv / PubMed / bioRxiv |
| `discover.py` | `/discover` | Search external sources + add to library (the page is now part of Find papers) |
| `annotations.py` | `/papers/{id}/annotations` | PDF highlight annotations |
| `chapters.py` | `/papers/{id}/chapters` | Book / lecture chapter management |
| `blogs.py` | `/blogs` | Blog and blog post management |
| `venues.py` | `/venues` | Venue browser |
| `conferences.py` | `/conferences` | Conference explorer: institutions and topics per conference-year |
| `claims.py` | `/papers/{id}/claims` | Claim extraction and search |
| `synthesis.py` | `/synthesis` | Cross-paper synthesis |
| `research_gaps.py` | `/research-gaps` | Research gap analysis |
| `author_tracker.py` | `/people/{id}/track` | Author tracking + auto-import |
| `merge.py` | `/merge` | Duplicate detection + merge |
| `users.py` | `/users` | User identity + per-user conversations |
| `admin.py` | `/admin` | Admin / maintenance endpoints |
| `tokens.py` | `/tokens` | Usage ledger: summary, calls, price table |
| `reports.py` | `/reports` | Long-read reports: create, list, view, export, cancel, delete |
| `suggestions.py` | `/suggestions` | Improvement ideas: list, submit, vote, status |
| `system_health.py` | `/system` | `GET /system/health` (admin only) |

### services/

| File | Responsibility |
| ---- | -------------- |
| `ai.py` | All Claude API calls — summarise, chat, topics, figures, claims, synthesis, gaps |
| `drive.py` | Upload/download files to Google Drive |
| `pdf_parser.py` | Extract raw text; orchestrate 4-layer metadata extraction pipeline |
| `metadata_lookup.py` | Semantic Scholar + CrossRef API clients |
| `metadata_from_url.py` | URL/DOI/arXiv/PubMed/bioRxiv resolver |
| `figure_extractor.py` | Extract figures from PDF pages; generate captions |
| `note_parser.py` | `@Name` and `#Topic` extraction from Markdown |
| `references.py` | Three-strategy reference extraction pipeline |
| `bulk_resolver.py` | Per-entry resolver for bulk import |
| `literature_search.py` | Keyword-based search across arXiv / PubMed / bioRxiv |
| `blog_fetcher.py` | Fetch and parse blog posts from RSS feeds / URLs |
| `book_chapter_parser.py` | Detect chapter boundaries in PDFs (Docling + AI) |
| `embeddings.py` | Generate Ollama embeddings for semantic similarity |
| `person_enrichment.py` | Enrich Person nodes with affiliation / S2 data |
| `web_search.py` | Web search helper for research gap and synthesis endpoints |
| `usage/` | Token ledger: SDK hooks (`hook.py`), SQLite store (`ledger.py`), price table (`pricing.py`) |
| `reports/` | Report pipeline: retrieval, LLM calls, pipeline, HTML / Markdown rendering, job runner |
| `suggestions.py` | Chat suggestion tag filter, dedupe and recording |
| `system_health.py`, `heartbeat.py` | Health checks with per-check caches; heartbeats from background threads |
| `library_search/` | Ranked library search (`query.py`, `engine.py`, `ranking.py`) and its result cache (`cache.py`) |
| `cypher_result.py` | Turns a Cypher result into table rows plus graph nodes and links (`POST /graph/query`) |
| `conferences/` | Conference explorer: catalog, source fetchers, institution normalisation, area taxonomy, bge-small embedder, on-disk store and build worker |

### db/queries/

| File | Nodes managed |
| ---- | ------------- |
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
| `tables.py` | Table extraction |
| `reports.py` | Report + `CITES_PAPER` |
| `suggestions.py` | Suggestion |

---

## Paper Ingestion Flow

```mermaid
sequenceDiagram
    participant Browser
    participant Router as routers/papers.py
    participant PDFParser as services/pdf_parser.py
    participant MetaLookup as services/metadata_lookup.py
    participant Drive as services/drive.py
    participant AI as services/ai.py
    participant DB as db/queries/papers.py
    participant Neo4j

    Browser->>Router: POST /papers/upload (PDF bytes)
    Router->>PDFParser: extract_text(pdf_bytes)
    PDFParser-->>Router: raw_text
    Router->>PDFParser: find_doi(raw_text)
    alt DOI found
        Router->>MetaLookup: lookup_semantic_scholar(doi)
        alt S2 fails
            Router->>MetaLookup: lookup_crossref(doi)
        end
    else No DOI
        Router->>PDFParser: extract_metadata_with_llm(raw_text[:3000])
        alt Ollama unavailable
            Router->>PDFParser: extract_metadata_heuristic(raw_text)
        end
    end
    Router->>Drive: upload_pdf(pdf_bytes)
    Drive-->>Router: drive_file_id
    Router->>AI: summarize_paper(abstract, raw_text)
    AI-->>Router: summary
    Router->>AI: extract_claims(raw_text)
    AI-->>Router: claims
    Router->>DB: create_paper(metadata + summary + drive_file_id)
    DB->>Neo4j: MERGE (p:Paper {...})
    Router->>DB: link_authors(paper_id, authors)
    Router->>DB: link_topics(paper_id, topics)
    Router-->>Browser: PaperOut JSON
```

See [ingestion-workflow.md](ingestion-workflow.md) for the full staged workflow including the parse/confirm/upload/onboarding flow.

---

## Usage Ledger

Every call to a language model is recorded once, in a SQLite file (`USAGE_DB_PATH`, default
`backend/data/usage.sqlite`), and read by the Tokens page and the Health page. SQLite and not Neo4j:
the ledger is append-only, grows by a row per call (thousands a day during a bulk import), is only read
as aggregates, and keeps working when the graph is down.

```mermaid
graph LR
    Call["Any call site<br/>services/, routers/"] --> SDK["anthropic / openai SDK<br/>(wrapped once)"]
    SDK --> Hook["services/usage/hook.py<br/>feature, user, paper, cost"]
    CC["Claude Code CLI<br/>(subprocess)"] -->|"explicit record"| Hook
    Hook --> Ledger[("usage.sqlite<br/>table llm_calls")]
    Ledger --> Tokens["/tokens/*"]
    Ledger --> Health["/system/health"]
```

- **No call site has to remember it.** `usage.install()` runs once when `main.py` is imported and wraps, at
  class level, `Messages.create` / `Messages.stream` (also the beta variants) of `anthropic` and
  `Completions.create` and `Embeddings.create` of `openai`. That covers the personal key, the work
  gateway, the LiteLLM proxy and every future client. The MCP server calls `install_lazy()` so its start-up
  stays free of both SDKs. Claude Code runs the CLI in a subprocess and records its result explicitly.
- **Attribution.** An explicit `usage_context(feature=, user=, paper_id=)` wins. Otherwise the feature is
  derived from the innermost backend frame on the call stack through a rules table (`hook.FEATURE_RULES`),
  the user from the request (copied into worker threads), the paper from a `paper_id` local.
  Background work (sweepers, ingest workers) has no user.
- **Cost.** One price table (USD per million tokens, longest model-prefix match; extra rows via
  `USAGE_PRICES_FILE`). LiteLLM costs 0, Claude Code reports its own list-price equivalent, an unknown model
  is stored with no price and flagged. Streams are recorded at the end; without reported usage the tokens
  are estimated and marked.
- **Safety.** Recording never raises into the call path; `USAGE_LEDGER_ENABLED=false` turns it off.

Row layout and API: `.specs/013_tokens.md`.

---

## Key Design Decisions

See the full [Decisions Log](../decisions.md) for rationale. The key principles:

1. **Neo4j over SQL** — papers, people, topics, and tags are naturally a graph
2. **Tags as nodes** — `(Paper)-[:TAGGED]->(Tag)` allows efficient "all papers with tag X" queries
3. **Topic ≠ Tag** — Topics are formal research areas; Tags are free-form personal labels
4. **Notes as graph nodes** — Notes have their own `@mention` and `#topic` relationships
5. **Shared service layer** — MCP tools and HTTP routers call the same `db/` and `services/` code
6. **Prompts as files** — All prompt templates live in `prompts/` and are loaded fresh on each call
7. **Vector embeddings** — Paper nodes store Ollama embeddings for semantic similarity search
8. **User identity** — `User` nodes enable per-user conversation history and attribution
9. **Ledger outside the graph** — LLM usage is bookkeeping, not library content, so it lives in SQLite
