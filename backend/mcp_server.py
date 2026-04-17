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
          "cwd": "/Users/M350238/Desktop/PaperManager"
        }
      }
    }

Or use the project-level .mcp.json at the repo root.
"""
from mcp.server.fastmcp import FastMCP
from tools import paper_tools, note_tools, tag_tools, person_tools, project_tools, ai_tools

mcp = FastMCP("PaperManager")

paper_tools.register(mcp)
note_tools.register(mcp)
tag_tools.register(mcp)
person_tools.register(mcp)
project_tools.register(mcp)
ai_tools.register(mcp)

if __name__ == "__main__":
    mcp.run()
