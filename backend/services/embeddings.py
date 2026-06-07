"""Vector embedding service via LiteLLM (768-dim nomic-embed-text)."""
from __future__ import annotations

import logging

from services.litellm_client import embed_text as _litellm_embed_text

log = logging.getLogger(__name__)

EMBED_DIM = 768  # nomic-embed-text output dimension
_MAX_CHARS = 8192  # model context limit in characters (conservative)


def embed_text(text: str) -> list[float]:
    """Embed *text* using LiteLLM.

    Returns a 768-dimensional float list.
    Raises on connectivity or model errors — callers should wrap in try/except.
    """
    return _litellm_embed_text(text[:_MAX_CHARS])


def embed_paper(title: str, abstract: str = "", summary: str = "") -> list[float]:
    """Build a canonical text representation of a paper and embed it."""
    parts = [p for p in [title, abstract, summary] if p and p.strip()]
    combined = "\n".join(parts)
    return embed_text(combined)
