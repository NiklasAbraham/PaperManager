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
| `get_random_paper` | Random paper (optionally filtered by reading_status) |

### Paper Interaction

| Tool | Description |
|---|---|
| `chat_with_paper` | Ask a question about a paper's content |
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
| `list_tags` | All tags with counts |
| `list_topics` | All topics with counts |

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

PDF upload is intentionally **not** exposed as an MCP tool — file upload must go through the browser frontend. All read and metadata operations are available via MCP.

The MCP server uses **FastMCP**. Tool handlers are thin wrappers that call `db/queries/` functions directly — the same functions used by FastAPI routers.
