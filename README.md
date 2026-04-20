# PaperManager

A personal academic paper manager. Upload PDFs, ingest papers from URLs, chat with papers using AI, explore a knowledge graph of authors and topics, and track references — all in a local web app backed by Neo4j and Google Drive.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Configuration](#configuration)
4. [Ingestion — Getting Papers In](#ingestion)
   - [PDF Upload](#pdf-upload)
   - [URL / DOI / arXiv Ingest](#url-ingest)
   - [Bulk Import from JSON](#bulk-import)
5. [Library — Browsing & Searching](#library)
6. [Paper Detail](#paper-detail)
   - [Metadata & Abstract](#metadata--abstract)
   - [PDF Viewer](#pdf-viewer)
   - [Figures](#figures)
   - [Notes](#notes)
   - [Chat with Paper](#chat-with-paper)
   - [References & Citations](#references--citations)
7. [People](#people)
8. [Projects](#projects)
9. [Tags & Topics](#tags--topics)
10. [Knowledge Graph](#knowledge-graph)
11. [Knowledge Chat](#knowledge-chat)
12. [Cypher Editor](#cypher-editor)
13. [Settings](#settings)
14. [Export & Backfill](#export--backfill)
15. [MCP Server (Claude Desktop)](#mcp-server)
16. [API Reference](#api-reference)
17. [Data Model](#data-model)
18. [AI Models & Pipelines](#ai-models--pipelines)

---

## Quick Start

```bash
# 1. Clone and enter
git clone <repo> && cd PaperManager

# 2. Create conda env
conda create -n papermanager python=3.11 -y
conda activate papermanager
pip install -r backend/requirements.txt

# 3. Install frontend
cd frontend && npm install && cd ..

# 4. Copy and fill in your .env
cp .env.example .env
# Edit .env — see Configuration section

# 5. Start everything
./start.sh
# Opens http://localhost:5173
```

`start.sh` starts the FastAPI backend (port 8000), the Vite frontend (port 5173), and optionally Ollama. Logs go to `/tmp/papermanager-backend.log` and `/tmp/papermanager-frontend.log`.

---

## Architecture Overview

```
┌─────────────────────┐     HTTP / SSE      ┌──────────────────────────┐
│   React Frontend    │ ◄──────────────────► │   FastAPI Backend        │
│   (Vite, port 5173) │                      │   (uvicorn, port 8000)   │
└─────────────────────┘                      └──────────┬───────────────┘
                                                         │
                          ┌──────────────────────────────┼──────────────────┐
                          │                              │                  │
                   ┌──────▼──────┐              ┌────────▼──────┐  ┌───────▼───────┐
                   │  Neo4j Aura │              │ Google Drive  │  │  Anthropic /  │
                   │  (graph DB) │              │ (PDF storage) │  │  Ollama (AI)  │
                   └─────────────┘              └───────────────┘  └───────────────┘
```

**Backend:** Python 3.11, FastAPI, Neo4j driver, httpx, Anthropic SDK, Ollama SDK, Google Drive API, Docling (PDF parsing).

**Frontend:** React + TypeScript, Vite, Tailwind CSS, react-force-graph (WebGL graph), react-dropzone.

**Database:** Neo4j Aura (cloud) — stores paper metadata, authors, topics, tags, projects, notes, and the full citation graph. PDFs and figures are stored in Google Drive; only the Drive file ID is kept in Neo4j.

---

## Configuration

Create a `.env` file at the project root:

```env
# ── Neo4j ──────────────────────────────────────────────────────
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# ── Google Drive ───────────────────────────────────────────────
# OAuth desktop app credentials from Google Cloud Console
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
GOOGLE_DRIVE_FOLDER_ID=xxxx   # Folder where PDFs will be stored

# ── Anthropic ─────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-xxxx

# Anthropic Foundry enterprise gateway (optional)
ANTHROPIC_WORK_API_KEY=xxxx
ANTHROPIC_WORK_BASE_URL=https://your-foundry-gateway.com/...

# ── App ────────────────────────────────────────────────────────
BACKEND_PORT=8000
FRONTEND_URL=http://localhost:5173

# ── Ollama ─────────────────────────────────────────────────────
OLLAMA_MODEL=llama3.2:3b   # Local model for metadata extraction / tag suggestion

# ── Corporate network (optional) ──────────────────────────────
SSL_VERIFY=true
SSL_CA_BUNDLE=/path/to/corporate-ca.pem
```

**Google Drive auth:** On first use the backend opens a browser window for OAuth. Credentials are saved to `backend/token.json` and reused on subsequent runs.

---

## Ingestion

### PDF Upload

Drag a PDF onto the Library page or click the **+** button.

**What happens automatically:**

1. **Metadata extraction (4-layer pipeline)**
   - Layer 1a: DOI or arXiv ID detected in text → Semantic Scholar API → CrossRef fallback
   - Layer 1b: S2 title search if a title was found without a DOI
   - Layer 2: Ollama LLM (`llama3.2:3b`) on the first 3 000 chars
   - Layer 3: Heuristics (first line = title, year regex)
   - Abstract fallback: `ABSTRACT_RE` regex → Claude Haiku if regex fails

2. **Confirmation modal** — Review extracted metadata before committing. You can override any field. A duplicate check runs against existing papers.

3. **Upload pipeline** (after confirmation)
   - PDF uploaded to Google Drive
   - Paper node created in Neo4j (or existing stub enriched if DOI matches)
   - AI summary generated (Claude Opus) from abstract / full text
   - Authors linked as `Person` nodes
   - Topics suggested (Claude Haiku) and linked
   - References extracted (Semantic Scholar API → regex → Claude Haiku) and shown for review
   - Figures extracted from PDF pages (Docling / Ollama / Claude Vision)
   - Paper auto-tagged `pdf-upload`

**Upload modal options:**

| Option | Default | Description |
|--------|---------|-------------|
| Source step | on | Record how you found the paper (person, LinkedIn, Twitter, conference, etc.) |
| Summary prompt step | on | Edit the AI summary instructions before upload |
| Auto-save references | off | Skip reference review and save all automatically |
| Tags step | on | Review AI-suggested tags before saving |
| Summary instructions | built-in | Custom Claude prompt prepended to summarisation |

---

### URL Ingest

Click the **+** button → **URL / DOI** tab. Paste any of:

| Input format | Example |
|---|---|
| arXiv URL | `https://arxiv.org/abs/1706.03762` |
| arXiv ID | `1706.03762` or `arXiv:1706.03762` |
| DOI URL | `https://doi.org/10.1038/nature14539` |
| Bare DOI | `10.1038/nature14539` |
| PubMed URL | `https://pubmed.ncbi.nlm.nih.gov/12345678/` |
| bioRxiv URL | `https://www.biorxiv.org/content/10.1101/...` |
| medRxiv URL | `https://www.medrxiv.org/content/10.1101/...` |

Metadata is fetched from the source API (arXiv Atom, Semantic Scholar, CrossRef, PubMed eUtils, bioRxiv). If a real DOI is found, Semantic Scholar is queried for richer data including citation count and affiliations. Paper is auto-tagged `from-url`. No PDF is stored.

---

### Bulk Import

Go to **Bulk Import** in the nav bar. Upload or paste a JSON file:

```json
{
  "fetch_pdf": true,
  "project_id": "optional-project-uuid",
  "papers": [
    {"url": "https://arxiv.org/abs/1706.03762"},
    {"arxiv": "1810.04805"},
    {"doi": "10.1038/nature14539"},
    {"url": "https://pubmed.ncbi.nlm.nih.gov/30082513/"},
    {"title": "AlphaFold protein structure prediction"},
    {"title": "CRISPR-Cas9 genome editing", "fetch_pdf": false}
  ]
}
```

Each entry needs at least one of: `url`, `arxiv`, `doi`, `title`. You can mix formats freely.

**Resolution order per entry:**

1. `url` → existing URL resolver (arXiv, DOI, PubMed, bioRxiv)
2. `arxiv` → arXiv API
3. `doi` → Semantic Scholar → CrossRef
4. `title` → Semantic Scholar title search → arXiv title search → Ollama-improved arXiv search

**PDF fetching** (`fetch_pdf: true`):
- arXiv papers: downloaded from `arxiv.org/pdf/{id}`
- Other papers: Unpaywall API checked for open-access PDF URL

Progress is shown as a live log stream. Papers that already exist by DOI are reported as "skipped". All imported papers are auto-tagged `bulk-import`.

---

## Library

The main page shows all papers in your library.

**Search & filter:**
- Full-text search across title, abstract, and summary
- Filter by tag, topic, project, or person (sidebar)
- Active filters shown as removable chips
- Searches update the URL for bookmarking

**View options:**
- Grid or list view toggle
- Sort by date added (newest/oldest), year, or title
- Configurable page size (20 / 50 / 100 / all)

**Paper cards show:**
- Title, year, authors, metadata source badge (color-coded: green = Semantic Scholar/CrossRef, yellow = LLM-extracted, red = guessed)
- Abstract preview (optional)
- Tags
- Quick edit / delete buttons

**Dashboard** (when no filters active):
- Count cards: papers, authors, topics, tags, projects
- Papers by year bar chart
- Top topics
- Recently added papers

---

## Paper Detail

Click any paper to open its detail view.

### Metadata & Abstract

Left panel — shows title, authors, year, DOI, venue, citation count, metadata source, abstract, and AI summary. The **Edit** button opens a modal to update any field.

Author and topic chips are clickable — clicking an author opens the People page; clicking a topic filters the library.

### PDF Viewer

The PDF is streamed from Google Drive and rendered inline in the browser. Available when a PDF was uploaded (not for URL-only papers).

### Figures

Figures are extracted from the PDF and stored on Drive. Each figure shows:
- Figure number, page number
- Caption (generated by Docling, Ollama, or Claude Vision depending on settings)
- Full-size image on click
- **Ask about this figure** — opens a vision chat powered by Claude; ask anything about the figure

To extract (or re-extract) figures: click **Extract Figures** and choose a caption method.

### Notes

A markdown editor attached to each paper. Supports:
- `@PersonName` — links to a Person node (created if not found)
- `#TopicName` — links to a Topic node (created if not found)
- Preview mode renders the markdown
- All `@mentions` and `#topics` become graph relationships (`Note -[:MENTIONS]-> Person/Topic`)

### Chat with Paper

Ask questions about the paper's full text. Three model options:

| Model | When to use |
|---|---|
| Claude (Opus 4.6) | Best quality, uses personal API key |
| Claude Work | Enterprise Anthropic Foundry gateway |
| Ollama (local) | Fully offline, uses `llama3.2:3b` |

The full `raw_text` extracted from the PDF is included in context (truncated to model limits).

### References & Citations

**Outgoing references** (papers this paper cites): extracted on-demand, shown in a review list, then saved as `CITES` relationships.

**Incoming citations** (papers in your library that cite this paper): automatically maintained as you import papers.

**Reference extraction pipeline:**
1. Semantic Scholar `/references` API (requires DOI)
2. Regex on raw text (`REFERENCES` section detection)
3. Claude Haiku AI on the last 30% of document text (when regex returns < 3 results)

Each saved reference creates a `Paper` stub node (title + DOI), tagged `from-references`, and linked with `CITES`. If you later import the full paper by DOI, the stub is enriched rather than duplicated.

---

## People

Track authors, collaborators, and colleagues.

- All people listed in the sidebar with search
- **Person detail**: name, affiliation, papers linked, research specialties (topics)
- **Roles on papers**: `AUTHORED_BY` (author), `INVOLVES` (with custom role: `shared_by`, `working_on`, `collaborating`, `supervisor`, `feedback_needed`)
- **Research specialties**: `SPECIALIZES` relationship to Topic nodes — used to discover who works on what
- People are auto-created when papers are ingested (from author lists)

---

## Projects

Group papers into named collections.

- Create a project with a name, description, and status
- Add/remove papers from a project
- Papers can belong to multiple projects
- Filter library by project
- Projects can be linked as related (`RELATED_TO`)
- Select a project during PDF upload, URL ingest, or bulk import to add papers automatically

---

## Tags & Topics

**Tags** are free-form labels. **Topics** are research areas (more structured, used in the knowledge graph and specialties).

### Tags

157 tags are seeded on startup across categories:

- **Source:** `pdf-upload`, `from-url`, `from-references`, `bulk-import`, `from-linkedin`, `from-twitter`, `from-email`, `from-conference`, `from-newsletter`, `from-google-scholar`, `from-colleague`
- **Workflow:** `to-read`, `reading`, `read`, `important`, `revisit`, `needs-review`, `relevant`, `in-bibliography`, `reproduced`, `code-available`
- **Content type:** `review`, `benchmark`, `dataset`, `method`, `theory`, `negative-result`, `foundational`, `highly-cited`, `sota`
- **Math:** algebra, topology, differential geometry, probability, statistics, optimization, graph theory, information theory, and more
- **ML/AI:** machine-learning, deep-learning, transformers, LLMs, diffusion models, GNNs, Bayesian inference, and ~40 more
- **Physics/Simulation:** statistical mechanics, quantum mechanics, molecular dynamics, Monte Carlo, biophysics, and more
- **Biology:** protein structure/folding/design, genomics, CRISPR, single-cell, evolutionary biology, and more
- **Drug discovery:** drug design, molecular docking, ADMET, QSAR, retrosynthesis, PROTAC, and more

**AI tag suggestion** (Ollama): the upload modal offers AI-suggested tags based on title and abstract. You can accept or skip.

### Topics

Research area nodes in the graph. Topics are linked to papers via `ABOUT` relationships and to people via `SPECIALIZES`. Claude Haiku suggests 3–6 topics per paper during upload (title-case, e.g. `Protein Structure Prediction`). Topics can be renamed — all relationships move to the new name automatically.

---

## Knowledge Graph

Go to **Graph** for an interactive WebGL visualization (powered by react-force-graph).

**Node types and colours:**

| Colour | Node type |
|---|---|
| Purple | Paper |
| Blue | Person |
| Green | Topic |
| Orange | Tag |
| Pink | Project |
| Grey | Note |

**Controls:**
- Pan and zoom the canvas
- Drag individual nodes
- Click a node → properties panel on the right
  - View all node properties
  - Navigate to paper detail page
  - Delete node
- Toggle between **Full graph** (all node types) and **Papers only** (Papers, People, Topics)
- Adjust node size, link distance, and repulsion force with sliders
- Toggle node and edge labels

**Graph modes** available via API (`GET /graph?mode=...`):
- `full` — everything (up to 500 nodes)
- `papers` — Papers, Persons, Topics only
- `paper` — single paper with all direct neighbours

---

## Knowledge Chat

Go to **Knowledge** for graph-aware conversation across your entire library.

Ask questions about multiple papers at once. Use `@mentions` to bring specific papers into context:

```
@tag:deep-learning What are the main architectural differences across these papers?

@topic:Protein Folding How has the approach changed from RoseTTAFold to AlphaFold?

@project:my-phd-papers Summarise the key open problems.

@paper:Attention is All You Need What positional encoding does this use?
```

Without mentions, the 10 most recently added papers are used as context.

**Features:**
- SSE streaming response — see the answer appear token by token
- Step-by-step progress: shows which Cypher queries are run to fetch context and how many papers are loaded
- Context window visualization: stacked bar chart of token usage per paper
- Model selector: Claude Opus, Claude Work (enterprise), Ollama
- Conversation history: create new conversations, load old ones
- **Compact** a conversation: summarises the history into a system message to free up context window

---

## Cypher Editor

Go to **Cypher** for direct access to the Neo4j database.

**Schema browser:** live view of all node labels, relationship types, and property keys.

**Query editor:** write and run raw Cypher. Results shown in a table with mutation counters (nodes created/deleted, relationships created/deleted, properties set). Maximum 500 rows returned.

**AI assist:** describe what you want in plain English → Ollama generates the Cypher query.

**Example queries:**
```cypher
-- Papers citing a specific paper
MATCH (a:Paper)-[:CITES]->(b:Paper {title: "..."})
RETURN a.title, a.year

-- Most connected authors
MATCH (p:Person)<-[:AUTHORED_BY]-(paper:Paper)
RETURN p.name, count(paper) AS papers ORDER BY papers DESC LIMIT 10

-- Papers without summaries
MATCH (p:Paper) WHERE p.summary IS NULL RETURN p.title, p.year

-- All papers on a topic
MATCH (p:Paper)-[:ABOUT]->(t:Topic {name: "Transformers"})
RETURN p.title, p.year ORDER BY p.year DESC
```

---

## Settings

All settings are persisted to `localStorage`.

### Library display

| Setting | Options | Default |
|---|---|---|
| Default view | grid / list | grid |
| Default sort | date desc/asc, year desc, title asc | date desc |
| Abstract preview | on / off | on |
| Papers per page | 20 / 50 / 100 / all | 20 |

### Upload workflow

| Setting | Default | Description |
|---|---|---|
| Source step | on | Ask how you found the paper (person, social media, conference…) |
| Summary prompt step | on | Edit AI summary instructions before upload |
| Auto-save references | off | Skip reference review, save all automatically |
| Tags step | on | Review AI-suggested tags before saving |
| Default summary instructions | built-in | Pre-filled Claude prompt; reset button available |

### Figure extraction

Choose the caption method used when extracting figures from PDFs:
- **Docling** — structural PDF parser, fast, no AI cost
- **Ollama** — local LLM captions (default)
- **Claude Vision** — highest quality, uses Anthropic API

### Graph visualization

| Setting | Default |
|---|---|
| Default graph mode | full |
| Node size | 4 |
| Show node labels | on |
| Show edge labels | off |

---

## Export & Backfill

### Export

- **BibTeX** (`GET /export/bibtex`) — downloads a `.bib` file containing all papers
- **JSON** — export from the Settings page

### Backfill (bulk enrichment)

Run from the Settings page or directly via API:

| Operation | Endpoint | Description |
|---|---|---|
| Backfill topics | `POST /backfill/topics` | Run Claude Haiku topic suggestion on all papers without topics |
| Backfill summaries | `POST /backfill/summary` | Generate AI summaries for papers that have `raw_text` but no summary |
| Backfill figures | `POST /backfill/figures` | Extract figures from all papers that have a PDF but no figures yet |

Each returns `{processed, skipped, errors}`.

---

## MCP Server

PaperManager ships with an MCP (Model Context Protocol) server at `backend/mcp_server.py` that lets Claude Desktop interact with your library directly.

**Configure in `~/.claude/claude_desktop_config.json`:**

```json
{
  "mcpServers": {
    "paperManager": {
      "command": "/path/to/conda/envs/papermanager/bin/python",
      "args": ["/path/to/PaperManager/backend/mcp_server.py"]
    }
  }
}
```

**Available MCP tools:**

| Tool | Description |
|---|---|
| `search_papers` | Search by keyword, tag, topic, project, or person |
| `get_paper_detail` | Full paper metadata |
| `chat_with_paper` | Ask a question about a paper's content |
| `add_note` | Write/update a paper's markdown note |
| `get_note` | Read a paper's note |
| `tag_paper_with` | Add a tag to a paper |
| `add_topic` | Link a research topic to a paper |
| `link_person_to_paper` | Link a person with a role |
| `add_paper_metadata` | Add a paper by metadata (no PDF) |
| `list_projects` | List all projects |
| `list_project_papers` | Papers in a project |
| `add_to_project` | Add a paper to a project |
| `list_tags` | All tags with counts |
| `list_topics` | All topics with counts |
| `list_people` | All people |
| `get_person_papers` | Papers associated with a person |
| `add_person` | Create a person node |
| `create_project` | Create a new project |

---

## API Reference

All endpoints served from `http://localhost:8000`.

### Papers

| Method | Path | Description |
|---|---|---|
| `GET` | `/papers` | List papers (`?skip=&limit=`) |
| `POST` | `/papers` | Create paper (manual) |
| `GET` | `/papers/{id}` | Get paper detail |
| `PATCH` | `/papers/{id}` | Update paper fields |
| `DELETE` | `/papers/{id}` | Delete paper + Drive file + figures |
| `POST` | `/papers/parse` | Extract metadata from PDF (no save) |
| `GET` | `/papers/check-duplicate` | Check by `?doi=` or `?title=` |
| `POST` | `/papers/upload` | Upload PDF (multipart) |
| `POST` | `/papers/from-url` | Ingest from URL/DOI/arXiv |
| `POST` | `/papers/bulk-import` | Bulk import (SSE stream) |
| `POST` | `/papers/{id}/chat` | Chat with paper |
| `GET` | `/papers/{id}/pdf` | Stream PDF from Drive |
| `GET` | `/papers/{id}/note` | Get markdown note |
| `PUT` | `/papers/{id}/note` | Create/update note |
| `GET` | `/papers/{id}/extract-references` | Extract references (no save) |
| `POST` | `/papers/{id}/references` | Save reference list |
| `GET` | `/papers/{id}/references` | List outgoing + incoming citations |
| `POST` | `/papers/{id}/tags` | Add tag |
| `DELETE` | `/papers/{id}/tags/{name}` | Remove tag |
| `POST` | `/papers/{id}/topics` | Add topic |
| `DELETE` | `/papers/{id}/topics/{name}` | Remove topic |
| `POST` | `/papers/{id}/topics/suggest` | AI topic suggestion |
| `POST` | `/papers/{id}/authors` | Link author (Person) |
| `DELETE` | `/papers/{id}/authors/{person_id}` | Unlink author |
| `POST` | `/papers/{id}/involves` | Link person with role |
| `DELETE` | `/papers/{id}/involves/{person_id}` | Unlink person |
| `GET` | `/papers/{id}/figures` | List figures |
| `GET` | `/papers/{id}/figures/{fig_id}/image` | Get figure image (PNG) |
| `POST` | `/papers/{id}/figures/extract` | Extract figures from PDF |
| `POST` | `/papers/{id}/figures/{fig_id}/chat` | Vision chat about figure |

### People

| Method | Path | Description |
|---|---|---|
| `GET` | `/people` | List all people |
| `POST` | `/people` | Create person |
| `POST` | `/people/get-or-create` | Get or create by name |
| `GET` | `/people/{id}` | Person detail + papers + specialties |
| `PATCH` | `/people/{id}` | Update name / affiliation |
| `DELETE` | `/people/{id}` | Delete person |
| `POST` | `/people/{id}/specialties` | Add research specialty |

### Tags

| Method | Path | Description |
|---|---|---|
| `GET` | `/tags` | List tags with counts |
| `POST` | `/tags` | Create tag |
| `DELETE` | `/tags/{name}` | Delete tag |
| `POST` | `/tags/suggest` | AI tag suggestion (Ollama) |
| `GET` | `/tags/{name}/papers` | Papers with this tag |

### Topics

| Method | Path | Description |
|---|---|---|
| `GET` | `/topics` | List topics |
| `POST` | `/topics` | Create topic |
| `DELETE` | `/topics/{name}` | Delete topic |
| `PATCH` | `/topics/{name}` | Rename topic |
| `GET` | `/topics/{name}/papers` | Papers with this topic |
| `POST` | `/topics/{a}/related/{b}` | Mark two topics as related |

### Projects

| Method | Path | Description |
|---|---|---|
| `GET` | `/projects` | List projects |
| `POST` | `/projects` | Create project |
| `GET` | `/projects/{id}` | Project + papers |
| `PATCH` | `/projects/{id}` | Update project |
| `DELETE` | `/projects/{id}` | Delete project |
| `POST` | `/projects/{id}/papers` | Add paper to project |
| `DELETE` | `/projects/{id}/papers/{paper_id}` | Remove paper |
| `POST` | `/projects/{a}/related/{b}` | Link related projects |

### Search, Graph, Stats

| Method | Path | Description |
|---|---|---|
| `GET` | `/search` | Full-text + filtered search (`?q=&tag=&topic=&project_id=&person_id=`) |
| `GET` | `/graph` | Graph data (`?mode=full\|papers\|paper&id=`) |
| `POST` | `/graph/cypher` | Custom Cypher → graph nodes + links |
| `GET` | `/stats` | Library statistics (counts, by year, top topics, recent) |

### Cypher, Export, Backfill, Knowledge Chat

| Method | Path | Description |
|---|---|---|
| `GET` | `/cypher/schema` | Live Neo4j schema |
| `POST` | `/cypher/run` | Run raw Cypher (max 500 rows) |
| `POST` | `/cypher/assist` | Ollama generates Cypher from natural language |
| `DELETE` | `/cypher/nodes/{id}` | Delete any node by id |
| `GET` | `/export/bibtex` | Download BibTeX |
| `POST` | `/backfill/topics` | Bulk AI topic assignment |
| `POST` | `/backfill/summary` | Bulk AI summarisation |
| `POST` | `/backfill/figures` | Bulk figure extraction |
| `POST` | `/knowledge-chat/stream` | Multi-paper chat (SSE) |
| `GET` | `/knowledge-chat/conversations` | List conversations |
| `GET` | `/knowledge-chat/conversations/{id}/messages` | Conversation messages |
| `POST` | `/knowledge-chat/conversations/{id}/compact` | Compact conversation history |
| `DELETE` | `/knowledge-chat/conversations/{id}` | Delete conversation |
| `GET` | `/health` | Health check |

---

## Data Model

### Nodes

| Label | Key properties |
|---|---|
| `Paper` | `id` (uuid), `title`, `year`, `doi`, `abstract`, `summary`, `drive_file_id`, `raw_text`, `citation_count`, `metadata_source`, `created_at`, `updated_at` |
| `Person` | `id`, `name`, `affiliation` |
| `Topic` | `id`, `name` |
| `Tag` | `id`, `name` |
| `Project` | `id`, `name`, `description`, `status`, `created_at` |
| `Note` | `id`, `content`, `created_at`, `updated_at` |
| `Figure` | `id`, `paper_id`, `figure_number`, `caption`, `drive_file_id`, `page_number` |

### Relationships

| Relationship | Direction | Notes |
|---|---|---|
| `CITES` | Paper → Paper | Citation; target may be a stub |
| `AUTHORED_BY` | Paper → Person | Author |
| `INVOLVES` | Person → Paper | Non-author role stored on relationship |
| `TAGGED` | Paper → Tag | Idempotent MERGE |
| `ABOUT` | Paper → Topic | Research area |
| `CONTAINS` | Project → Paper | Project membership |
| `ABOUT` | Note → Paper | Note ownership |
| `MENTIONS` | Note → Person\|Topic | @mention / #topic in note text |
| `RELATED_TO` | Topic ↔ Topic | Bidirectional |
| `SPECIALIZES` | Person → Topic | Research specialty |

### Fulltext indexes

- `paper_search` on `Paper(title, abstract, summary)`
- `note_search` on `Note(content)`

### `metadata_source` values

| Value | Meaning |
|---|---|
| `semantic_scholar` | Fetched from Semantic Scholar API |
| `crossref` | Fetched from CrossRef API |
| `arxiv` | Fetched from arXiv Atom API |
| `pubmed` | Fetched from PubMed eUtils |
| `biorxiv` / `medrxiv` | Fetched from bioRxiv/medRxiv API |
| `llm` | Extracted by Ollama from PDF text |
| `heuristic` | Guessed from first lines of PDF |
| `bulk` | Added via bulk import |

---

## AI Models & Pipelines

### Models used

| Model | Provider | Used for |
|---|---|---|
| `claude-opus-4-6` | Anthropic | Paper summarisation, paper chat, knowledge chat |
| `claude-haiku-4-5-20251001` | Anthropic | Abstract extraction, reference extraction, topic suggestion, conversation compaction |
| `llama3.2:3b` | Ollama (local) | Metadata extraction (layer 2), tag suggestion, arXiv query generation, figure captions, affiliation extraction, Cypher assist |
| Claude Vision | Anthropic | Figure chat, figure captioning (claude-vision mode) |

All Anthropic calls can be routed through an enterprise Foundry gateway by setting `ANTHROPIC_WORK_API_KEY` and `ANTHROPIC_WORK_BASE_URL`.

### Metadata extraction pipeline (PDF upload)

```
PDF bytes
  ├─ 1a. Find DOI/arXiv in text → Semantic Scholar API
  │                                └─ fail → CrossRef API
  ├─ 1b. S2 title search (if title found, no DOI)
  ├─ 2.  Ollama LLM on first 3 000 chars
  ├─ 3.  Heuristics (first line = title, year regex)
  └─ Abstract fallback: ABSTRACT_RE regex → Claude Haiku
```

### Reference extraction pipeline

```
Paper with raw_text
  ├─ Strategy A: Semantic Scholar /references API (needs DOI)
  ├─ Strategy B: Regex on REFERENCES section of raw_text
  └─ Strategy C: Claude Haiku on last 30% of document
                 (when A+B give < 3 results)
```

### Knowledge chat context assembly

```
User question
  └─ Parse @mentions (@tag:, @topic:, @project:, @paper:)
      ├─ Mentions found → Cypher queries to fetch matching papers
      └─ No mentions   → 10 most recently added papers
          └─ Assemble context (truncated to token budget per paper)
              └─ Stream Claude Opus response via SSE
```

### Prompt templates

All prompts live in `prompts/` and are loaded fresh on each call — edit without restarting the backend:

| File | Purpose |
|---|---|
| `summary.txt` | Paper summarisation — problem, method, findings, relevance |
| `topics.txt` | Research topic suggestion (3–6 title-case topics) |
| `chat_system.txt` | Single-paper Q&A system prompt |
| `knowledge_chat_system.txt` | Multi-paper synthesis system prompt |
| `figure_captions.txt` | Figure caption generation |
| `author_affiliations.txt` | Affiliation extraction from paper text |
