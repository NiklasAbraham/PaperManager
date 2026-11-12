from mcp.server.fastmcp import FastMCP
from db.connection import get_driver
from db.queries.papers import get_paper


def register(mcp: FastMCP):
    @mcp.tool()
    def chat_with_paper(paper_id: str, question: str) -> str:
        """Ask Claude a question about a specific paper using its full extracted text as context.
        Returns Claude's answer as markdown text.
        The question can be anything about the paper's content, methods, contributions, or relevance."""
        # Imported here: services.ai pulls in the anthropic and openai SDKs (~2 s), which
        # every MCP process would otherwise pay at startup for a tool that is rarely called.
        from services.ai import chat_with_paper as _chat

        paper = get_paper(get_driver(), paper_id)
        if not paper:
            return f"Error: Paper {paper_id} not found."
        return _chat(
            paper_text=paper.get("raw_text", ""),
            paper_title=paper.get("title", ""),
            question=question,
        )
