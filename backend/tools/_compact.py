"""Leaner MCP output: compact JSON results and tidy tool definitions.

The desk loads every tool definition into each chat's context and reads every result,
so whitespace there is paid on every turn:

- FastMCP serialises a dict/list result with ``indent=2`` (and, for ``-> dict`` tools, a
  second structured copy). ``json_tool`` registers a tool whose result goes out as one
  compact JSON text block instead — the same keys, about a fifth fewer characters.
- Python 3.11 keeps a docstring's indentation and pydantic gives every parameter a
  ``title``; ``tidy`` strips both from the advertised definitions (validation runs on the
  pydantic argument model, not on the advertised schema) and drops tools named in
  ``PAPERMANAGER_MCP_EXCLUDE`` (comma list, opt-in: a client that never uses some tools).
"""
from __future__ import annotations

import functools
import inspect
import json
import logging
import os

log = logging.getLogger(__name__)


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def json_tool(mcp, **kwargs):
    """``@mcp.tool()`` for a tool returning a dict or list: the result is sent as one
    compact JSON text block (no structured copy, no indentation)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kw):
            return dumps(fn(*args, **kw))

        # FastMCP reads the parameters through inspect.signature (it follows __wrapped__);
        # the return annotation is irrelevant with structured_output=False.
        return mcp.tool(structured_output=False, **kwargs)(wrapper)
    return deco


def _drop_titles(schema: dict) -> None:
    """Remove pydantic's auto ``title`` from the schema and each parameter's schema (not
    parameters that are *named* title)."""
    if not isinstance(schema, dict):
        return
    schema.pop("title", None)
    for prop in (schema.get("properties") or {}).values():
        if isinstance(prop, dict):
            prop.pop("title", None)
            for alt in prop.get("anyOf") or []:
                if isinstance(alt, dict):
                    alt.pop("title", None)
    for sub in (schema.get("$defs") or {}).values():
        _drop_titles(sub)


def tidy(mcp) -> None:
    """Clean every registered tool's description and schema; drop excluded tools."""
    exclude = {t.strip() for t in os.environ.get("PAPERMANAGER_MCP_EXCLUDE", "").split(",") if t.strip()}
    for name in exclude:
        try:
            mcp.remove_tool(name)
        except Exception:  # noqa: BLE001 — an unknown name is not an error
            log.warning("PAPERMANAGER_MCP_EXCLUDE: no tool named %s", name)
    for tool in mcp._tool_manager.list_tools():
        tool.description = inspect.cleandoc(tool.description or "")
        _drop_titles(tool.parameters)
