# Project Structure

## Top-level layout

```
PaperManager/
├── backend/            # FastAPI Python app + MCP server (shared codebase)
├── frontend/           # React web app
├── docs/               # Project docs, design notes, task list
│   └── tasks/          # Step-by-step build tasks
├── notes/              # Your personal paper notes (.md files, git-tracked)
├── memory/             # Claude's persistent memory
├── .env.example        # Template for environment variables
└── README.md
```

There are **three ways to interact** with the system — all backed by the same data:

| Interface | Who uses it | How |
|---|---|---|
| React web app | You in a browser | Drag & drop, visual library, note editor |
| FastAPI REST | Frontend + any HTTP client | `GET/POST /papers`, `/notes`, etc. |
| MCP server | Claude Code / AI assistants | Tool calls: `add_note`, `search_papers`, etc. |

---

## Backend

```
backend/
├── main.py                  # FastAPI app entry, mounts all routers
├── config.py                # Reads env vars (Neo4j, Drive, Claude, etc.)
│
├── db/
│   ├── connection.py        # Neo4j driver singleton
│   └── queries/
│       ├── papers.py        # All Cypher for Paper nodes
│       ├── people.py        # All Cypher for Person nodes
│       ├── topics.py        # All Cypher for Topic nodes
│       ├── tags.py          # All Cypher for Tag nodes
│       ├── notes.py         # All Cypher for Note nodes + MENTIONS
│       └── projects.py      # All Cypher for Project nodes
│
├── routers/
│   ├── papers.py            # POST /papers, GET /papers, GET /papers/{id}
│   ├── people.py            # CRUD for Person nodes
│   ├── topics.py            # CRUD for Topic nodes
│   ├── tags.py              # CRUD for Tag nodes
│   ├── notes.py             # CRUD for notes, triggers mention parsing
│   ├── projects.py          # CRUD for Project nodes
│   └── search.py            # GET /search?q=... full-text + filter
│
├── services/
│   ├── drive.py             # Upload PDF to Drive, get download URL
│   ├── ai.py                # Claude: summarize paper, chat with paper
│   ├── pdf_parser.py        # Extract raw text; orchestrate metadata extraction
│   ├── metadata_lookup.py   # Semantic Scholar + Crossref API clients
│   └── note_parser.py       # Parse @Name and #Topic from markdown text
│
├── models/
│   └── schemas.py           # Pydantic request/response models
│
├── mcp_server.py            # MCP server entry point (runs separately from FastAPI)
│
├── tools/                   # MCP tool definitions (thin wrappers over db/ + services/)
│   ├── __init__.py
│   ├── paper_tools.py       # search_papers, get_paper, add_paper_metadata
│   ├── note_tools.py        # get_note, add_note
│   ├── tag_tools.py         # tag_paper, list_tags
│   ├── person_tools.py      # list_people, link_person_to_paper
│   ├── project_tools.py     # list_projects, add_to_project
│   └── ai_tools.py          # chat_with_paper
│
├── tests/
│   ├── test_papers.py
│   ├── test_notes.py
│   ├── test_note_parser.py
│   ├── test_drive.py
│   ├── test_ai.py
│   └── test_mcp_tools.py    # unit tests for each MCP tool
│
└── requirements.txt
```

### How the backend fits together

```
HTTP Request          MCP Tool Call
     │                     │
     ▼                     ▼
 routers/            tools/           ← both are thin entry points
     │                     │
     └──────────┬──────────┘
                ▼
          db/queries/    ← all Cypher, returns dicts
                │
                ▼
           Neo4j Aura (cloud)

     Also shared:
          services/drive.py    ← Google Drive API
          services/ai.py       ← Claude API
          services/pdf_parser.py + note_parser.py
```

The key architecture principle: `db/` and `services/` are **framework-neutral**.
Neither FastAPI nor MCP specifics leak into them.
`routers/` and `tools/` are just two different ways to call the same logic.

**Paper ingestion flow (the most complex path):**
```
POST /papers (multipart: PDF file)
  → pdf_parser.extract_text()       raw text from PDF

  → pdf_parser.find_doi()
      ├── DOI found → metadata_lookup.lookup_semantic_scholar()  ← preferred
      │                         or .lookup_crossref()            ← fallback
      ├── No DOI   → pdf_parser.extract_metadata_with_llm()     ← Ollama local LLM
      └── Ollama missing → pdf_parser.extract_metadata_heuristic()

  → drive.upload_pdf()              PDF stored in Google Drive
  → ai.summarize_paper()            Claude generates summary
  → db/queries/papers.create_paper()   Paper node in Neo4j
  → db/queries/people.link_author()    Author Person nodes + AUTHORED_BY
  → db/queries/topics.link_paper_topic()  auto-topics from Semantic Scholar
  → returns PaperOut JSON  (includes metadata_source field)
```

**Note save flow:**
```
PUT /notes/{id} (body: markdown string)
  → note_parser.py      scans for @Name and #Topic tokens
  → db/queries/notes.py  saves Note content, upserts MENTIONS relationships
  → returns Note JSON
```

---

## Frontend

```
frontend/
├── index.html
├── package.json
├── vite.config.ts
│
└── src/
    ├── main.tsx             # React entry point
    ├── App.tsx              # Router setup (React Router)
    │
    ├── api/
    │   └── client.ts        # All fetch calls to backend (typed)
    │
    ├── types/
    │   └── index.ts         # TypeScript types matching backend schemas
    │
    ├── components/          # Reusable UI pieces
    │   ├── PaperDrop.tsx    # Drag & drop zone for PDF upload
    │   ├── PaperCard.tsx    # Summary card shown in library grid
    │   ├── NoteEditor.tsx   # Markdown editor with @/# autocomplete
    │   ├── TagBadge.tsx     # Small coloured tag pill
    │   ├── PersonChip.tsx   # Person mention chip
    │   ├── SearchBar.tsx    # Global search input
    │   └── ChatPanel.tsx    # Chat with paper sidebar
    │
    └── pages/
        ├── Library.tsx      # Main view: paper grid + filters
        ├── PaperDetail.tsx  # Single paper: metadata, note, chat, tags
        ├── Projects.tsx     # Project list + papers per project
        ├── People.tsx       # People list + their papers/specialties
        └── Explore.tsx      # Tag/topic browser, graph-style overview
```

### Page flows

```
Library (/)
  ├── drop PDF → upload → shows new PaperCard
  ├── click paper → PaperDetail
  └── filter by tag / topic / project / person

PaperDetail (/paper/:id)
  ├── metadata panel (left)
  ├── NoteEditor (center) — @Name and #Topic create graph links on save
  └── ChatPanel (right) — ask Claude about this paper

Projects (/projects)
  └── click project → filtered Library view

People (/people)
  └── click person → their papers (AUTHORED_BY + INVOLVES) + specialties

Explore (/explore)
  └── tag cloud / topic list / graph view (later)
```

---

---

## MCP Server

```
backend/
├── mcp_server.py            # Entry point: registers all tools, starts MCP server
└── tools/
    ├── paper_tools.py       # search_papers, get_paper, add_paper_metadata
    ├── note_tools.py        # get_note, add_note
    ├── tag_tools.py         # tag_paper, list_tags, list_topics
    ├── person_tools.py      # list_people, add_person, link_person_to_paper
    ├── project_tools.py     # list_projects, create_project, add_to_project
    └── ai_tools.py          # chat_with_paper
```

### Full tool list

| Tool | What it does |
|---|---|
| `search_papers` | Search by keyword, tag, topic, project, person |
| `get_paper` | Get full details of one paper by id |
| `add_paper_metadata` | Add a paper without a PDF (title, year, doi, etc.) |
| `get_note` | Read the markdown note for a paper |
| `add_note` | Write/update the markdown note for a paper |
| `tag_paper` | Add a tag to a paper |
| `list_tags` | List all tags + paper counts |
| `list_topics` | List all topics |
| `list_people` | List all people |
| `add_person` | Create a person node |
| `link_person_to_paper` | Link a person to a paper with a role |
| `list_projects` | List all projects |
| `create_project` | Create a new project |
| `add_to_project` | Add a paper to a project |
| `chat_with_paper` | Ask Claude a question about a specific paper |

### How to use it with Claude Code

Add to your `~/.claude/settings.json` (or project-level settings):
```json
{
  "mcpServers": {
    "paperManager": {
      "command": "python",
      "args": ["backend/mcp_server.py"],
      "cwd": "/path/to/PaperManager"
    }
  }
}
```

Then Claude Code can call tools directly:
```
You: add a note to paper abc123 saying "@Jan is working on a follow-up"
Claude: [calls add_note tool] → note saved, MENTIONS relationship created in Neo4j
```

### MCP server flow
```
Claude Code calls tool
        │
        ▼
   tools/*.py        ← validates args, calls into shared layer
        │
        ├──► db/queries/   → Neo4j Aura
        ├──► services/ai.py → Claude API (for chat_with_paper)
        └──► services/note_parser.py → parses @/# on add_note
```

---

## Environment variables

```
# Neo4j
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=...

# Google Drive
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_DRIVE_FOLDER_ID=...   # folder in your Drive where PDFs go

# Anthropic
ANTHROPIC_API_KEY=...

# App
BACKEND_PORT=8000
FRONTEND_URL=http://localhost:5173
```

---

## Notes folder

```
notes/
└── {paper-id}.md    # one file per paper, named by Neo4j paper ID
```

These are plain markdown files, git-tracked, editable in any editor.
The system reads/writes them via the notes API.
The `@Name` and `#Topic` syntax is parsed on every save.
