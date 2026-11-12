"""
PaperManager MCP Server

Exposes the paper library as tools that Claude Code (or any MCP client) can call.

Usage:
    python backend/mcp_server.py

Configure in Claude Code by adding to ~/.claude/settings.json:
    {
      "mcpServers": {
        "paperManager": {
          "command": "/path/to/conda/envs/papermanager/bin/python",
          "args": ["backend/mcp_server.py"],
          "cwd": "/Users/you/Desktop/PaperManager"
        }
      }
    }

Or use the project-level .mcp.json at the repo root.
"""
import os

# Query vectors for semantic search come from the backend, which has the model loaded,
# instead of torch + the model in every MCP process (services/conferences/embedder.py;
# falls back to a local load if the backend cannot answer).
os.environ.setdefault("PM_EMBED_URL", f"http://127.0.0.1:{os.environ.get('BACKEND_PORT', '8000')}/conferences/embed")

from mcp.server.fastmcp import FastMCP
from config import settings
from services.auth import set_request_user
from tools import paper_tools, note_tools, tag_tools, person_tools, project_tools, ai_tools, library_tools, upload_tools, maintenance_tools, conference_tools

set_request_user(settings.default_user_name)

# LLM calls made by MCP tools land in the same token ledger as the backend's (.specs/013_tokens.md).
# Lazily: the MCP server keeps anthropic/openai out of its startup (tests/test_mcp_lean.py).
from services.usage import install_lazy as install_usage_ledger  # noqa: E402
install_usage_ledger()

mcp = FastMCP("PaperManager")

paper_tools.register(mcp)
note_tools.register(mcp)
tag_tools.register(mcp)
person_tools.register(mcp)
project_tools.register(mcp)
ai_tools.register(mcp)
library_tools.register(mcp)
upload_tools.register(mcp)
maintenance_tools.register(mcp)
conference_tools.register(mcp)

# Compact descriptions and schemas (every chat loads them), PAPERMANAGER_MCP_EXCLUDE.
from tools._compact import tidy  # noqa: E402
tidy(mcp)

if __name__ == "__main__":
    mcp.run()
