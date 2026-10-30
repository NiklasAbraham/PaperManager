"""LiteLLM proxy client (OpenAI-compatible API)."""
from __future__ import annotations

import json
import logging
import re
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


# Defaults for the fast tasks when no LiteLLM proxy is configured (FAST_MODEL overrides).
ANTHROPIC_FAST_MODEL = "claude-haiku-4-5-20251001"
OPENAI_FAST_MODEL = "gpt-5-mini"
_PROVIDERS = ("litellm", "anthropic", "openai")


def _configured() -> dict[str, bool]:
    return {
        "litellm": bool(settings.litellm_endpoint.strip() and settings.litellm_api_key.strip()),
        "anthropic": bool(settings.anthropic_api_key.strip()),
        "openai": bool(settings.openai_api_key.strip()),
    }


def fast_provider() -> str | None:
    """Provider that runs the fast tasks: AI_PROVIDER, or with "auto" the first one configured."""
    choice = (settings.ai_provider or "auto").strip().lower()
    if choice in _PROVIDERS:
        return choice
    configured = _configured()
    return next((p for p in _PROVIDERS if configured[p]), None)


def fast_model() -> str:
    """Model id for the fast tasks on the active provider."""
    if settings.fast_model.strip():
        return settings.fast_model.strip()
    return {"anthropic": ANTHROPIC_FAST_MODEL, "openai": OPENAI_FAST_MODEL}.get(
        fast_provider() or "", settings.litellm_model
    )


def fast_model_label() -> str:
    """Short human name of the fast model for the UI, e.g. "Claude Haiku 4.5"."""
    model = fast_model()
    if model.startswith("claude-haiku-4-5"):
        return "Claude Haiku 4.5"
    if model.startswith("gpt-"):
        return "GPT-" + model[4:].replace("-", " ", 1)
    return model.rsplit("/", 1)[-1]


def get_litellm_client() -> OpenAI:
    """Return an OpenAI-compatible client for the fast tasks (LiteLLM proxy or OpenAI)."""
    provider = fast_provider()
    if provider == "openai":
        if not settings.openai_api_key.strip():
            raise ValueError("OPENAI_API_KEY is required.")
        return OpenAI(api_key=settings.openai_api_key.strip(), timeout=120.0)
    if provider == "anthropic":
        raise ValueError("The fast model runs on Anthropic, which has no OpenAI-compatible client.")
    api_key = (settings.litellm_api_key or "").strip()
    endpoint = (settings.litellm_endpoint or "").strip().rstrip("/")
    if not api_key:
        raise ValueError("No AI provider configured: set ANTHROPIC_API_KEY, OPENAI_API_KEY or LITELLM_*.")
    if not endpoint:
        raise ValueError("LITELLM_ENDPOINT is required.")
    if not endpoint.endswith("/v1"):
        endpoint = f"{endpoint}/v1"
    # Set timeout to prevent hanging on slow/busy LiteLLM proxy
    return OpenAI(base_url=endpoint, api_key=api_key, timeout=20.0)


def resolve_chat_model(model: str | None) -> str:
    """Map legacy Ollama model names, empty values and LITELLM_MODEL to the active fast model."""
    if not model or model in ("llama3.2:3b", "ollama", "litellm", settings.litellm_model):
        return fast_model()
    return model


def _anthropic_completion(
    messages: list[dict[str, Any]],
    model: str,
    *,
    json_mode: bool,
    max_tokens: int | None,
    timeout: float | None,
    max_retries: int | None,
) -> str:
    """chat_completion on the Anthropic Messages API (fast provider "anthropic")."""
    import anthropic

    if not settings.anthropic_api_key.strip():
        raise ValueError("ANTHROPIC_API_KEY is required.")
    verify: bool | str = (settings.ssl_ca_bundle or True) if settings.ssl_verify else False
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.strip(),
        base_url="https://api.anthropic.com",
        timeout=timeout or 120.0,
        max_retries=2 if max_retries is None else max_retries,
        http_client=anthropic.DefaultHttpxClient(verify=verify),
    )
    system = "\n\n".join(str(m["content"]) for m in messages if m["role"] == "system")
    if json_mode:
        system += "\n\nRespond with one JSON object only: no prose, no code fences."
    convo = [
        {"role": m["role"], "content": str(m.get("content") or "")}
        for m in messages if m["role"] in ("user", "assistant")
    ]
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens or 4096, "messages": convo}
    if system.strip():
        kwargs["system"] = system.strip()
    response = client.messages.create(**kwargs)
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if json_mode:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return text


def _can_fall_back(provider: str | None, tools: list[dict[str, Any]] | None) -> bool:
    """A failed LiteLLM call is retried on Anthropic when AI_FALLBACK is on and a key is set.

    Tool calls stay on LiteLLM: the Anthropic path here has no tool support.
    """
    return (
        provider == "litellm"
        and not tools
        and settings.ai_fallback
        and bool(settings.anthropic_api_key.strip())
    )


def chat_completion(
    messages: list[dict[str, Any]],
    model: str | None = None,
    *,
    json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> str:
    """Run a chat completion and return the assistant message text.

    ``timeout`` overrides the client's 20 s default for long generations;
    ``max_retries`` overrides the SDK's automatic retries (2 by default).
    """
    import time as _time

    provider = fast_provider()
    resolved = resolve_chat_model(model)
    endpoint = (settings.litellm_endpoint or "").strip() if provider == "litellm" else provider
    log.info("LiteLLM → chat_completion | model=%s | endpoint=%s | messages=%d | json_mode=%s",
             resolved, endpoint, len(messages), json_mode)
    t0 = _time.time()
    try:
        if provider == "anthropic":
            content = _anthropic_completion(
                messages, resolved, json_mode=json_mode, max_tokens=max_tokens,
                timeout=timeout, max_retries=max_retries,
            )
        else:
            client = get_litellm_client()
            overrides = {k: v for k, v in (("timeout", timeout), ("max_retries", max_retries)) if v is not None}
            if overrides:
                client = client.with_options(**overrides)
            kwargs: dict[str, Any] = {"model": resolved, "messages": messages}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if tools:
                kwargs["tools"] = tools
            # OpenAI's reasoning models reject max_tokens and spend part of any cap on
            # reasoning, so the cap only goes to the proxy.
            if max_tokens is not None and provider != "openai":
                kwargs["max_tokens"] = max_tokens
            response = client.chat.completions.create(**kwargs)
            content = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        log.error("LiteLLM ✗ chat_completion FAILED after %.2fs | model=%s | %s: %s",
                  _time.time() - t0, resolved, type(exc).__name__, exc)
        if not _can_fall_back(provider, tools):
            raise
        log.warning("LiteLLM ↪ falling back to Anthropic | model=%s", ANTHROPIC_FAST_MODEL)
        content = _anthropic_completion(
            messages, ANTHROPIC_FAST_MODEL, json_mode=json_mode, max_tokens=max_tokens,
            timeout=timeout, max_retries=max_retries,
        )
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
    if fast_provider() != "litellm":
        return [fast_model()]
    try:
        client = get_litellm_client()
        models = client.models.list()
        names = sorted({m.id for m in models.data if m.id})
        if names:
            return names
    except Exception as exc:
        log.debug("LiteLLM models.list failed: %s", exc)
    return [fast_model()]


def parse_tool_args(raw: str | dict | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
