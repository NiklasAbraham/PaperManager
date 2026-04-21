# Backend

The backend is a **Python 3.11 FastAPI** application. It also runs a separate **MCP server** process that shares the same business logic.

---

## Directory Layout

```
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
│       └── projects.py      # All Cypher for Project nodes
│
├── routers/
│   ├── papers.py            # POST /papers, GET /papers, etc.
│   ├── people.py            # CRUD for Person nodes
│   ├── topics.py            # CRUD for Topic nodes
│   ├── tags.py              # CRUD for Tag nodes + tag seeding
│   ├── projects.py          # CRUD for Project nodes
│   ├── search.py            # GET /search
│   ├── graph.py             # GET /graph (graph visualisation data)
│   ├── stats.py             # GET /stats
│   ├── cypher.py            # Cypher editor endpoints
│   ├── export.py            # BibTeX export
│   ├── backfill.py          # Bulk enrichment
│   ├── knowledge_chat.py    # Multi-paper chat (SSE)
│   ├── figures.py           # Figure extraction + image serving
│   └── bulk_import.py       # Bulk import (SSE stream)
│
├── services/
│   ├── ai.py                # Claude: summarise, chat, topics, figures
│   ├── drive.py             # Upload PDF/images to Drive, get download URL
│   ├── pdf_parser.py        # Extract raw text; orchestrate metadata extraction
│   ├── metadata_lookup.py   # Semantic Scholar + CrossRef API clients
│   ├── metadata_from_url.py # URL/DOI/arXiv/PubMed resolver
│   ├── figure_extractor.py  # Docling / Ollama / Claude Vision figure extraction
│   ├── note_parser.py       # Parse @Name and #Topic from markdown text
│   ├── references.py        # Reference extraction pipeline
│   └── bulk_resolver.py     # Per-entry resolver for bulk import
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
│   ├── test_papers.py
│   ├── test_notes.py
│   ├── test_note_parser.py
│   ├── test_drive.py
│   ├── test_ai.py
│   └── test_mcp_tools.py
│
├── prompts/                 # Prompt templates (loaded fresh each call)
│   ├── summary.txt
│   ├── topics.txt
│   ├── chat_system.txt
│   ├── knowledge_chat_system.txt
│   ├── figure_captions.txt
│   └── author_affiliations.txt
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
    seed_default_tags(get_driver())      # seed 157 default tags
    yield
```

The app is started by `start.sh` via `uvicorn backend.main:app`.

---

## config.py — Settings

Uses **Pydantic Settings** to read environment variables with type validation:

```python
class Settings(BaseSettings):
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    google_client_id: str
    google_client_secret: str
    google_drive_folder_id: str
    anthropic_api_key: str
    # ... etc.
    model_config = SettingsConfigDict(env_file=".env")
```

`settings` is a module-level singleton imported throughout the app.

---

## db/ — Database Layer

### connection.py

Manages a Neo4j driver singleton:

```python
def get_driver() -> Driver:
    # returns module-level cached driver instance
```

### schema.py

Runs on startup to create Neo4j indexes and uniqueness constraints. Idempotent — safe to run multiple times.

### queries/

Each file contains functions that:

1. Accept plain Python arguments
2. Build a Cypher query string
3. Run it via `driver.session().run()`
4. Return plain dicts or lists

**No FastAPI or MCP types leak into this layer.**

Example pattern:

```python
def create_paper(driver: Driver, paper_data: dict) -> dict:
    with driver.session() as session:
        result = session.run(
            """
            MERGE (p:Paper {doi: $doi})
            SET p += $props
            RETURN p
            """,
            doi=paper_data["doi"],
            props=paper_data,
        )
        return result.single()["p"]
```

---

## routers/ — HTTP Endpoints

Each router file:

1. Creates a FastAPI `APIRouter` with a prefix and tags
2. Defines endpoint functions that call into `db/queries/` and `services/`
3. Validates input/output with **Pydantic schemas** from `models/schemas.py`

Example:

```python
router = APIRouter(prefix="/papers", tags=["papers"])

@router.post("/upload", response_model=PaperOut)
async def upload_paper(file: UploadFile, ...):
    pdf_bytes = await file.read()
    raw_text = pdf_parser.extract_text(pdf_bytes)
    metadata = await pdf_parser.extract_metadata(raw_text)
    drive_id = drive.upload_pdf(pdf_bytes)
    summary = await ai.summarize_paper(metadata["abstract"])
    paper = db_papers.create_paper(driver, {...})
    return paper
```

---

## services/ — Business Logic

| File | Responsibility |
|------|---------------|
| `ai.py` | All Claude API calls — summarise, chat, topic suggestion, figure captions, reference extraction |
| `drive.py` | Upload files to Google Drive; generate download URLs; handle OAuth flow |
| `pdf_parser.py` | Extract raw text with Docling; orchestrate the 4-layer metadata extraction pipeline |
| `metadata_lookup.py` | HTTP clients for Semantic Scholar and CrossRef |
| `metadata_from_url.py` | Parse and resolve URLs (arXiv, DOI, PubMed, bioRxiv, medRxiv) |
| `figure_extractor.py` | Extract figures from PDF pages; generate captions via Docling/Ollama/Claude |
| `note_parser.py` | Regex-based `@Name` and `#Topic` extraction from Markdown text |
| `references.py` | Three-strategy reference extraction (S2 API → regex → Claude Haiku) |
| `bulk_resolver.py` | Per-entry resolution logic for the bulk import endpoint |

---

## models/schemas.py — Pydantic Models

Defines all request and response models. These are used:

- As FastAPI endpoint parameters / return types (automatic validation + OpenAPI docs)
- As type hints in MCP tool functions

Key models include `PaperOut`, `PersonOut`, `NoteOut`, `ProjectOut`, `TagOut`, `TopicOut`, `HealthResponse`, and various `*Create` / `*Update` input models.

---

## tools/ — MCP Tool Handlers

Each file in `tools/` registers MCP tools using **FastMCP**:

```python
from fastmcp import FastMCP
mcp = FastMCP("PaperManager")

@mcp.tool()
async def search_papers(query: str, tag: str = None, ...) -> list[dict]:
    """Search papers by keyword, tag, topic, project, or person."""
    return db_papers.search(get_driver(), query, tag=tag, ...)
```

Tools are thin wrappers — validation happens in FastMCP, logic lives in `db/queries/`.

---

## prompts/ — Prompt Templates

All AI prompt templates are plain text files loaded fresh on each API call:

```python
def load_prompt(name: str) -> str:
    path = Path(__file__).parent.parent / "prompts" / name
    return path.read_text()
```

Edit a prompt file without restarting the backend.

---

## Tests

Tests live in `backend/tests/` and use **pytest**. Run with:

```bash
cd backend
pytest
```

Tests mock external services (Neo4j, Drive, Claude) to run without real credentials.
