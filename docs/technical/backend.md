# Backend

The backend is a **Python 3.11 FastAPI** application. It also runs a separate **MCP server** process that shares the same business logic.

---

## Directory Layout

```text
backend/
├── main.py                  # FastAPI app entry — mounts all routers
├── config.py                # Reads env vars (pydantic Settings)
├── logger.py                # Logging setup
├── mcp_server.py            # MCP server entry point (separate process)
│
├── db/
│   ├── connection.py        # Neo4j driver singleton
│   ├── schema.py            # Schema setup (indexes, constraints)
│   └── queries/
│       ├── papers.py        # All Cypher for Paper nodes
│       ├── people.py        # All Cypher for Person nodes
│       ├── topics.py        # All Cypher for Topic nodes
│       ├── tags.py          # All Cypher for Tag nodes
│       ├── notes.py         # All Cypher for Note nodes + MENTIONS
│       ├── projects.py      # All Cypher for Project nodes
│       ├── references.py    # CITES relationships
│       ├── figures.py       # Figure nodes
│       ├── annotations.py   # PDF Annotation nodes
│       ├── chapters.py      # Chapter nodes
│       ├── blogs.py         # Blog + BlogPost nodes
│       ├── claims.py        # Claim nodes
│       ├── conversations.py # Conversation + Message nodes
│       ├── users.py         # User nodes
│       ├── search.py        # Full-text + filter search queries
│       └── tables.py        # Table extraction nodes
│
├── routers/
│   ├── papers.py            # POST /papers, GET /papers, upload, chat, notes, refs
│   ├── people.py            # CRUD for Person nodes
│   ├── topics.py            # CRUD for Topic nodes
│   ├── tags.py              # CRUD for Tag nodes + tag seeding
│   ├── projects.py          # CRUD for Project nodes
│   ├── search.py            # GET /search
│   ├── graph.py             # GET /graph (graph visualisation data)
│   ├── stats.py             # GET /stats
│   ├── cypher.py            # Cypher editor endpoints
│   ├── export.py            # BibTeX export
│   ├── backfill.py          # Bulk enrichment (topics, summaries, figures)
│   ├── knowledge_chat.py    # Multi-paper chat (SSE)
│   ├── figures.py           # Figure extraction + image serving
│   ├── bulk_import.py       # Bulk import (SSE stream)
│   ├── literature.py        # Stream recent papers from arXiv / PubMed / bioRxiv
│   ├── discover.py          # Search external sources + add to library
│   ├── annotations.py       # PDF highlight annotations
│   ├── chapters.py          # Book / lecture chapter management
│   ├── blogs.py             # Blog and blog post management
│   ├── venues.py            # Venue browser
│   ├── claims.py            # Claim extraction and search
│   ├── synthesis.py         # Cross-paper synthesis
│   ├── research_gaps.py     # Research gap analysis
│   ├── author_tracker.py    # Author tracking + auto-import
│   ├── merge.py             # Duplicate detection + merge
│   ├── users.py             # User identity + per-user conversations
│   └── admin.py             # Admin / maintenance endpoints
│
├── services/
│   ├── ai.py                # Claude: summarise, chat, topics, figures, claims, synthesis
│   ├── drive.py             # Upload PDF/images to Drive, get download URL
│   ├── pdf_parser.py        # Extract raw text; orchestrate metadata extraction
│   ├── metadata_lookup.py   # Semantic Scholar + CrossRef API clients
│   ├── metadata_from_url.py # URL/DOI/arXiv/PubMed resolver
│   ├── figure_extractor.py  # Docling / Ollama / Claude Vision figure extraction
│   ├── note_parser.py       # Parse @Name and #Topic from markdown text
│   ├── references.py        # Reference extraction pipeline
│   ├── bulk_resolver.py     # Per-entry resolver for bulk import
│   ├── literature_search.py # Keyword-based search across arXiv / PubMed / bioRxiv
│   ├── blog_fetcher.py      # Fetch and parse blog posts from RSS feeds / URLs
│   ├── book_chapter_parser.py # Detect chapter boundaries in PDFs (Docling + AI)
│   ├── embeddings.py        # Ollama embeddings for semantic similarity
│   ├── person_enrichment.py # Enrich Person nodes with affiliation / S2 data
│   └── web_search.py        # Web search for research gaps and synthesis
│
├── models/
│   └── schemas.py           # Pydantic request/response models
│
├── tools/                   # MCP tool definitions
│   ├── paper_tools.py
│   ├── note_tools.py
│   ├── tag_tools.py
│   ├── person_tools.py
│   ├── project_tools.py
│   └── ai_tools.py
│
├── tests/
│   └── ...
│
├── prompts/                 # Prompt templates (loaded fresh each call)
│   ├── summary.txt
│   ├── topics.txt
│   ├── chat_system.txt
│   ├── knowledge_chat_system.txt
│   ├── figure_captions.txt
│   ├── author_affiliations.txt
│   ├── claims.txt
│   ├── synthesis.txt
│   ├── research_gaps.txt
│   ├── chapter_summary.txt
│   ├── chapter_chat_system.txt
│   ├── literature_search_keywords.txt
│   └── merge_scan.txt
│
└── requirements.txt
```

---

## main.py — App Entry Point

`main.py` creates the FastAPI application, sets up CORS, registers all routers, and defines a startup lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    get_driver().verify_connectivity()   # verify Neo4j
    run_schema_setup(get_driver())       # create indexes + constraints
    seed_default_tags(get_driver())      # seed default tags
    seed_people_tags(get_driver())       # seed people-related tags
    yield
```

The app is started by `start.sh` via `uvicorn backend.main:app`.

---

## db/schema.py — Constraints and Indexes

Runs on startup. Creates:

- **Uniqueness constraints** on: `Paper.id`, `Person.id`, `Topic.id`, `Topic.name`, `Tag.id`, `Tag.name`, `Note.id`, `Project.id`, `Figure.id`, `Annotation.id`, `Blog.id`, `BlogPost.id`, `User.id`, `User.name`, `Claim.id`, `Table.id`, `Conversation.id`, `Message.id`, `Venue.id`
- **Fulltext indexes**: `paper_search` (title, abstract, summary), `note_search` (content), `message_search` (content), `claim_search` (text)
- **Vector index**: `paper_embeddings` on `Paper.embedding` (768-dim cosine, nomic-embed-text)

---

## services/ — Business Logic

| File | Responsibility |
| ---- | -------------- |
| `ai.py` | All Claude API calls — summarise, chat, topic suggestion, figure captions, claim extraction, cross-paper synthesis, research gap analysis |
| `drive.py` | Upload files to Google Drive; generate download URLs; handle OAuth flow |
| `pdf_parser.py` | Extract raw text with Docling; orchestrate the 4-layer metadata extraction pipeline |
| `metadata_lookup.py` | HTTP clients for Semantic Scholar and CrossRef |
| `metadata_from_url.py` | Parse and resolve URLs (arXiv, DOI, PubMed, bioRxiv, medRxiv) |
| `figure_extractor.py` | Extract figures from PDF pages; generate captions via Docling/Ollama/Claude |
| `note_parser.py` | Regex-based `@Name` and `#Topic` extraction from Markdown text |
| `references.py` | Three-strategy reference extraction (S2 API → regex → Claude Haiku) |
| `bulk_resolver.py` | Per-entry resolution logic for the bulk import endpoint |
| `literature_search.py` | Keyword-based search across arXiv, PubMed, and bioRxiv |
| `blog_fetcher.py` | Fetch and parse blog posts from RSS feeds and URLs |
| `book_chapter_parser.py` | Detect chapter boundaries in PDFs using Docling structure and AI |
| `embeddings.py` | Generate Ollama (nomic-embed-text) embeddings stored on Paper nodes |
| `person_enrichment.py` | Enrich Person nodes with affiliations and Semantic Scholar author data |
| `web_search.py` | Web search helper used by research gaps and synthesis endpoints |

---

## models/schemas.py — Pydantic Models

Defines all request and response models used by FastAPI endpoints and MCP tools. Key models include `PaperOut`, `PersonOut`, `NoteOut`, `ProjectOut`, `TagOut`, `TopicOut`, `AnnotationOut`, `ChapterOut`, `BlogOut`, `BlogPostOut`, `ClaimOut`, and various `*Create` / `*Update` input models.

---

## tools/ — MCP Tool Handlers

Each file in `tools/` registers MCP tools using **FastMCP**. Tools are thin wrappers — validation happens in FastMCP, logic lives in `db/queries/`.

---

## prompts/ — Prompt Templates

All AI prompt templates are plain text files loaded fresh on each API call — edit without restarting the backend.

| File | Used in | Purpose |
| ---- | ------- | ------- |
| `summary.txt` | `ai.py` | Paper summarisation |
| `topics.txt` | `ai.py` | Topic suggestion |
| `chat_system.txt` | `ai.py` | Single-paper Q&A system prompt |
| `knowledge_chat_system.txt` | `knowledge_chat.py` | Multi-paper synthesis system prompt |
| `figure_captions.txt` | `figure_extractor.py` | Figure caption generation |
| `author_affiliations.txt` | `pdf_parser.py` | Author affiliation extraction |
| `claims.txt` | `ai.py` | Claim extraction from paper text |
| `synthesis.txt` | `ai.py` | Cross-paper synthesis |
| `research_gaps.txt` | `ai.py` | Research gap analysis |
| `chapter_summary.txt` | `ai.py` | Book chapter summarisation |
| `chapter_chat_system.txt` | `ai.py` | Chapter-level Q&A system prompt |
| `literature_search_keywords.txt` | `literature_search.py` | Keyword generation for literature search |
| `merge_scan.txt` | `merge.py` | Duplicate paper detection |
