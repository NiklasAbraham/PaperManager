"""Web search service using DuckDuckGo (no API key required)."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Tool schema for Anthropic and Ollama tool-use APIs
WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for current information about papers, authors, institutions, "
        "research topics, preprints, or any other relevant information. "
        "Use this when the user asks about something not covered in the paper itself, "
        "or wants to find related work, citations, author profiles, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5, max 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

# Ollama-style tool schema (OpenAI function-calling format)
WEB_SEARCH_TOOL_OLLAMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": WEB_SEARCH_TOOL["description"],
        "parameters": WEB_SEARCH_TOOL["input_schema"],
    },
}


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo.

    Returns a list of dicts with keys: title, url, snippet.
    Falls back to an empty list on any error so chat never hard-fails.
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # legacy name fallback

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=min(max_results, 10)):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
        log.info("web_search | query=%.80s | results=%d", query, len(results))
        return results
    except Exception as exc:
        log.warning("web_search failed (non-fatal) | query=%.80s | %s", query, exc)
        return []


def format_results_for_prompt(results: list[dict]) -> str:
    """Format search results as a readable block for injection into prompts."""
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   URL: {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        lines.append("")
    return "\n".join(lines).strip()
