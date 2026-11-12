# MCP Server

PaperManager ships an MCP (Model Context Protocol) server at `backend/mcp_server.py` that lets Claude Desktop interact with your library directly.

---

## Setup

### Configure Claude Desktop

Add to `~/.claude/claude_desktop_config.json`:

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

The MCP server runs as a separate process from the FastAPI backend and communicates via stdio. It shares the same `db/queries/` and `services/` layer — no HTTP overhead.

**Requirements:** Neo4j must be reachable (same `NEO4J_*` env vars from `.env`). Anthropic API key must be set for AI tools.

---

## Available Tools

### Paper Search & Retrieval

| Tool | Description |
|---|---|
| `search_papers` | Search by keyword, tag, topic, project, person, year range, reading_status, or bookmark |
| `get_paper_detail` | Full paper metadata including reading_status, rating, bookmarked, venue |
| `get_paper_concepts` | Concepts detected on the paper's PDF pages, with any generated visualisation spec |
| `get_random_paper` | Random paper (optionally filtered by reading_status) |

### Reading the library (no model calls)

`tools/library_tools.py`. Read-only tools for a client that does its own reading — Claude Code
over a research repository — so the library acts as a database. None of them calls a language
model, so they cost nothing on the PaperManager side. Every result carries `paper_id`, `title`
and `url` (the frontend's `/paper/<id>`) so a client UI can show which papers entered a
conversation. Results stay under ~31 KB: Claude Code moves larger MCP results into a file.

| Tool | Description |
|---|---|
| `library_lookup` | Batch existence check before adding cited papers: up to 200 `dois` and/or `titles` (paired by index) in two Cypher queries. Match by normalised DOI (arXiv forms one id, bioRxiv versions dropped), else normalised title (`[a-z0-9]` only, markup stripped) exactly, else on its first 45 characters; `kind` says which. Per item only id, title, DOI, year, projects, `reference_stub`, `has_text`, `url` (a list with `duplicates` when several papers match); `project` adds `in_project`. Compact JSON, about 350 bytes per found item. Logic in `services/library_lookup.py` |
| `library_add` | Batch add of a reference list in one call: `path` (absolute path of a report's `papers.json`, a list or `{"papers": [...]}`) or `papers` inline, up to 200 entries with `title` and optionally `doi`, `arxiv`, `paperId`, `year`, `venue`, `abstract`, `document_type`, `published_date`, `authors` (list of full names). Confirms given `paperId`s, runs `library_lookup` on the rest, creates the missing papers (metadata only), dedupes within the batch (`same_as`), MERGEs every paper into `project` (must exist), and rewrites the file with `paperId`, `url`, `status` (`present` / `added`). `dry_run` writes nothing. Logic in `services/library_add.py` |
| `library_search` | One query across metadata, notes, highlights and their comments, claims and extracted full text; each hit says where it matched, with snippets. `project` filters by project name or id |
| `get_paper_context` | Metadata, authors, tags, topics, projects, the note (own text split from saved chat answers), every highlight with page, colour and comment, claims, `text_chars` |
| `read_paper_text` | Extracted full text, 30 000 characters per call from `offset`; page with `next_offset` |
| `find_in_paper` | Passages in one paper's text for a phrase, else ranked by how many query words co-occur; returns offsets for `read_paper_text` |
| `list_highlights` | Highlights, filterable by project, paper or text |
| `list_notes` | Notes, filterable by project or text; own text in full, saved answers only counted |

A paper note is the user's own text followed by chat answers the frontend saved below it
(`---` / `**Claude (date):**`); the library tools return the two separately.

### Paper Interaction

| Tool | Description |
|---|---|
| `chat_with_paper` | Ask a question about a paper's content. Calls the Anthropic API (or LiteLLM) with the configured key — billed per token; prefer `read_paper_text` from a client that is itself a model |
| `add_note` | Write or update a paper's markdown note |
| `get_note` | Read a paper's markdown note |
| `tag_paper_with` | Add a tag to a paper |
| `add_topic` | Link a research topic to a paper |
| `link_person_to_paper` | Link a person with a role |
| `set_reading_status` | Set reading_status: `unread` / `reading` / `read` |
| `rate_paper` | Rate a paper 1–5 stars |
| `bookmark_paper` | Bookmark or un-bookmark a paper |

### Library Management

| Tool | Description |
|---|---|
| `add_paper_metadata` | Add a paper by metadata (no PDF) |
| `upload_pdf` | Add a paper with its PDF through the full upload pipeline (path, URL, arXiv id or DOI) |
| `list_tags` | All tags with counts |
| `list_topics` | All topics with counts |

### Maintenance (`tools/maintenance_tools.py`)

Write tools preview by default: `merge_papers` runs with `dry_run=true`, `delete_paper` needs
`confirm=true`.

| Tool | Description |
|---|---|
| `find_duplicates` | Duplicate groups from `services/duplicate_scan.py` (keeper + papers to merge into it), optionally by class; papers carrying another paper's DOI |
| `merge_papers` | `services/paper_merge.py`: merge `remove_ids` into `keep_id` without losing notes, highlights, links or the PDF; `dry_run` reports only |
| `update_paper_metadata` | Correct title, year, venue, DOI, abstract, date, type; `authors` replaces the author list (placeholders dropped, orphaned people removed) |
| `regenerate_summary` | Re-run the summary on the stored full text (LiteLLM summary model) |
| `delete_paper` | `services/paper_delete.py` (shared with `DELETE /papers/{id}`): paper, note, highlights, claims, figures, PDF to Drive trash; preview unless `confirm=true` |

### Conferences (`tools/conference_tools.py`)

Read-only, over the datasets of the conference explorer (`.specs/011_conferences.md`). A
conference not loaded returns an error naming its state rather than starting a download.

| Tool | Description |
|---|---|
| `list_conferences` | Conference-years with state, paper and institution counts (`only_loaded`) |
| `conference_topic` | `store.topic`: top-k papers closest to a query, counted per institution (academia / industry), area mix, closest papers with `library_paper_id`. `conference="all"`: `search.topic` over every loaded conference (k defaults to 300): per-conference count and rate per 1,000, trend per series, pooled institutions with per-conference counts |
| `conference_institution` | Best name match, then `store.institution_detail`: rank, papers, fractional, area mix with the conference share, collaborators, authors, papers |
| `conference_search_papers` | `search.search_papers`: title matches (`title_match`: exact, prefix, phrase, words, most words) then closest by meaning, each with conference; `series`, `year_min`, `year_max` filters |
| `conference_search_author` | `search.search_authors`: name matches with papers (capped by `papers`), per-conference counts, institutions, co-author count, `possible_identities` when the papers split into groups sharing no institution or co-author |

`library_paper_id` comes from `routers.conferences.library_titles()` for the MCP default user.

### People & Projects

| Tool | Description |
|---|---|
| `list_people` | All people |
| `get_person_papers` | Papers associated with a person |
| `add_person` | Create a person node |
| `list_projects` | List all projects |
| `list_project_papers` | Papers in a project |
| `add_to_project` | Add a paper to a project |
| `create_project` | Create a new project |

---

## Architecture Note

`tools/upload_tools.py` exposes `upload_pdf(source, project="")`: one paper with its PDF through
`POST /papers/upload`, the same pipeline as a drag-and-drop upload (no upload-queue precompute, so
a call takes a few minutes). `source` is a local PDF path, a PDF URL, an arXiv id or a DOI; the
logic is `services/pdf_import.py`, shared with `scripts/import_to_project.py`. The MCP server runs
inside the backend container (`docker exec`), so local paths must lie under `HOST_IMPORT_ROOT`
(default `/srv/papers` in `docker-compose.example.yml`), which the compose file bind-mounts read-only at the same path.

The MCP server uses **FastMCP**. Tool handlers are thin wrappers that call `db/queries/` functions directly — the same functions used by FastAPI routers.
