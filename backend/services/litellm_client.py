"""LiteLLM proxy client (OpenAI-compatible API)."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from config import settings

log = logging.getLogger(__name__)

# OpenAI function-calling schema (same shape previously used for Ollama tools)
WEB_SEARCH_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information about papers, authors, institutions, "
            "research topics, preprints, or any other relevant information."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5, max 10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}


def get_litellm_client() -> OpenAI:
    """Return an OpenAI client routed through the self-hosted LiteLLM proxy."""
    api_key = (settings.litellm_api_key or "").strip()
    endpoint = (settings.litellm_endpoint or "").strip().rstrip("/")
    if not api_key:
        raise ValueError("LITELLM_API_KEY is required.")
    if not endpoint:
        raise ValueError("LITELLM_ENDPOINT is required.")
    if not endpoint.endswith("/v1"):
        endpoint = f"{endpoint}/v1"
    # Set timeout to prevent hanging on slow/busy LiteLLM proxy
    return OpenAI(base_url=endpoint, api_key=api_key, timeout=20.0)


def resolve_chat_model(model: str | None) -> str:
    """Map legacy Ollama model names and empty values to the configured LiteLLM model."""
    if not model or model in ("llama3.2:3b", "ollama", "litellm"):
        return settings.litellm_model
    return model


def chat_completion(
    messages: list[dict[str, Any]],
    model: str | None = None,
    *,
    json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
) -> str:
    """Run a chat completion and return the assistant message text."""
    import time as _time

    client = get_litellm_client()
    resolved = resolve_chat_model(model)
    kwargs: dict[str, Any] = {"model": resolved, "messages": messages}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if tools:
        kwargs["tools"] = tools
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    endpoint = (settings.litellm_endpoint or "").strip()
    log.info("LiteLLM → chat_completion | model=%s | endpoint=%s | messages=%d | json_mode=%s",
             resolved, endpoint, len(messages), json_mode)
    t0 = _time.time()
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:
        log.error("LiteLLM ✗ chat_completion FAILED after %.2fs | model=%s | %s: %s",
                  _time.time() - t0, resolved, type(exc).__name__, exc)
        raise
    content = (response.choices[0].message.content or "").strip()
    log.info("LiteLLM ✓ chat_completion OK | model=%s | %.2fs | %d chars returned",
             resolved, _time.time() - t0, len(content))
    return content


def embed_text(text: str, model: str | None = None) -> list[float]:
    """Embed text via LiteLLM embeddings API."""
    import time as _time

    client = get_litellm_client()
    embed_model = model or settings.litellm_embed_model
    log.info("LiteLLM → embed_text | model=%s | chars=%d", embed_model, len(text))
    t0 = _time.time()
    try:
        response = client.embeddings.create(
            model=embed_model,
            input=text,
        )
    except Exception as exc:
        log.error("LiteLLM ✗ embed_text FAILED after %.2fs | model=%s | %s: %s",
                  _time.time() - t0, embed_model, type(exc).__name__, exc)
        raise
    log.info("LiteLLM ✓ embed_text OK | model=%s | %.2fs", embed_model, _time.time() - t0)
    return list(response.data[0].embedding)


def list_available_models() -> list[str]:
    """Return model IDs from LiteLLM, or the configured default on failure."""
    try:
        client = get_litellm_client()
        models = client.models.list()
        names = sorted({m.id for m in models.data if m.id})
        if names:
            return names
    except Exception as exc:
        log.debug("LiteLLM models.list failed: %s", exc)
    return [settings.litellm_model]


def parse_tool_args(raw: str | dict | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
