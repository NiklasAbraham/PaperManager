# T22 — MCP Server

**Phase:** 6 — MCP
**Depends on:** T05–T09 (core data layer must exist), T12 (AI), T14 (chat)
**Touches:** `backend/mcp_server.py`, `backend/tools/`

## Goal
An MCP server that exposes the PaperManager as tools Claude Code (or any MCP client)
can call directly. Write a note, query the graph, link a person, chat with a paper —
all without opening the browser.

## Setup

Install the MCP Python SDK:
```
mcp
```
Add to `requirements.txt`.

---

## mcp_server.py

```python
from mcp.server.fastmcp import FastMCP
from tools import paper_tools, note_tools, tag_tools, person_tools, project_tools, ai_tools

mcp = FastMCP("PaperManager")

# Register all tools
paper_tools.register(mcp)
note_tools.register(mcp)
tag_tools.register(mcp)
person_tools.register(mcp)
project_tools.register(mcp)
ai_tools.register(mcp)

if __name__ == "__main__":
    mcp.run()
```

---

## Tool definitions (one file per domain)

Each `tools/*.py` file has a `register(mcp)` function that calls `@mcp.tool()`.

### paper_tools.py

```python
@mcp.tool()
def search_papers(query: str = "", tag: str = "", topic: str = "", project_id: str = "") -> list[dict]:
    """Search papers by keyword, tag, topic, or project. All params optional."""
    ...

@mcp.tool()
def get_paper(paper_id: str) -> dict:
    """Get full details of a paper including tags, topics, people, and projects."""
    ...

@mcp.tool()
def add_paper_metadata(title: str, year: int = None, doi: str = None, abstract: str = None) -> dict:
    """Add a paper to the library without a PDF. Returns the new paper with its id."""
    ...
```

### note_tools.py

```python
@mcp.tool()
def get_note(paper_id: str) -> str:
    """Read the markdown note for a paper. Returns the raw markdown content."""
    ...

@mcp.tool()
def add_note(paper_id: str, content: str) -> dict:
    """
    Write or update the markdown note for a paper.
    Use @PersonName to link a person, #TopicName to link a topic.
    These create graph relationships automatically.
    """
    ...
```

### tag_tools.py

```python
@mcp.tool()
def tag_paper(paper_id: str, tag_name: str) -> dict:
    """Add a free-form tag to a paper. Tag is created if it doesn't exist."""
    ...

@mcp.tool()
def list_tags() -> list[dict]:
    """List all tags with their paper counts."""
    ...

@mcp.tool()
def list_topics() -> list[dict]:
    """List all research topics."""
    ...
```

### person_tools.py

```python
@mcp.tool()
def list_people() -> list[dict]:
    """List all people with their specialties and linked paper counts."""
    ...

@mcp.tool()
def add_person(name: str, affiliation: str = "") -> dict:
    """Create a new person node."""
    ...

@mcp.tool()
def link_person_to_paper(paper_id: str, person_name: str, role: str) -> dict:
    """
    Link a person to a paper with a role.
    Role examples: "feedback_needed", "working_on", "shared_by", "collaborating".
    Person is looked up by name (created if not found).
    """
    ...
```

### project_tools.py

```python
@mcp.tool()
def list_projects() -> list[dict]:
    """List all projects with paper counts and status."""
    ...

@mcp.tool()
def create_project(name: str, description: str = "") -> dict:
    """Create a new project."""
    ...

@mcp.tool()
def add_to_project(paper_id: str, project_id: str) -> dict:
    """Add a paper to a project."""
    ...
```

### ai_tools.py

```python
@mcp.tool()
def chat_with_paper(paper_id: str, question: str) -> str:
    """
    Ask Claude a question about a specific paper.
    Uses the paper's extracted text as context.
    """
    ...
```

---

## Claude Code settings

To connect Claude Code to this MCP server, add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "paperManager": {
      "command": "python",
      "args": ["backend/mcp_server.py"],
      "cwd": "/Users/M350238/Desktop/PaperManager"
    }
  }
}
```

Or use the project-level `.mcp.json` at the repo root:
```json
{
  "mcpServers": {
    "paperManager": {
      "command": "python",
      "args": ["backend/mcp_server.py"]
    }
  }
}
```

---

## Example usage from Claude Code

```
You: Search for papers about transformers and add a note to the first one
     saying Nele gave me this, need to follow up with @Jan

Claude:
  [calls search_papers(query="transformers")]
  → returns list, first paper is "Attention Is All You Need" (id: abc123)

  [calls add_note(paper_id="abc123",
    content="Nele gave me this, need to follow up with @Jan")]
  → note saved, MENTIONS → Person "Jan" created in Neo4j
```

---

## Done when
- [ ] `python backend/mcp_server.py` starts without errors
- [ ] MCP server listed in `claude mcp list`
- [ ] `search_papers` returns real data from Neo4j
- [ ] `add_note` with @mentions updates graph relationships
- [ ] `chat_with_paper` returns a Claude answer
- [ ] All tools have clear docstrings (these become the tool descriptions Claude sees)

## Tests
`backend/tests/test_mcp_tools.py`
- Unit test each tool function directly (not via MCP protocol)
- `search_papers(query="")` → returns list
- `add_note(paper_id, "@Jan see #NLP")` → MENTIONS relationships created
- `link_person_to_paper(paper_id, "Jan", "feedback_needed")` → INVOLVES relationship

## Notes
- Tool docstrings are critical — Claude reads them to decide which tool to use
- Keep tool names and descriptions action-oriented and clear
- `add_note` is the most powerful tool — it's the main way Claude writes to the system
- PDF upload is intentionally NOT exposed as an MCP tool (file upload via browser only)
