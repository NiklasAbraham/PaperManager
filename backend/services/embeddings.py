"""Vector embedding service using local Ollama nomic-embed-text (768-dim)."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text output dimension
_MAX_CHARS = 8192  # model context limit in characters (conservative)


def embed_text(text: str) -> list[float]:
    """Embed *text* using local Ollama nomic-embed-text.

    Returns a 768-dimensional float list.
    Raises on Ollama connectivity or model errors — callers should wrap in try/except.
    """
    import ollama
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text[:_MAX_CHARS])
    return response["embedding"]


def embed_paper(title: str, abstract: str = "", summary: str = "") -> list[float]:
    """Build a canonical text representation of a paper and embed it.

    Concatenates title, abstract, and summary (whichever are non-empty) separated
    by newlines, then calls embed_text.  The ordering puts title first so the most
    discriminative signal is at the start of the context window.
    """
    parts = [p for p in [title, abstract, summary] if p and p.strip()]
    combined = "\n".join(parts)
    return embed_text(combined)
