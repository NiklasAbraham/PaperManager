"""Expand a plain prompt into an Ideogram 4 structured "boxes" caption.

This is the "magic prompt" step: an LLM rewrites the user's plain idea into the
structured JSON caption the image model consumes. Instead of Ideogram's hosted /
OpenRouter callers (which need an external key), we run it through the
self-hosted **LiteLLM / Gemma** model — always-on on GPUs 0/1, so it never
contends with Ideogram on GPU 2 — using Ideogram's own bundled magic-prompt
system prompt (``ideogram_magic_prompt_v1.txt``).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from math import gcd
from pathlib import Path
from typing import Any

from config import settings
from services.litellm_client import chat_completion

log = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).resolve().parent / "ideogram_magic_prompt_v1.txt"

# Which LLM rewrites the plain prompt into the structured caption.
#   "gemma"  → self-hosted LiteLLM/Gemma (GPUs 0/1, always-on, free)
#   "claude" → Anthropic personal key (cloud, best at the strict schema)
MAGIC_PROVIDERS = ("gemma", "claude")
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"


def _llm_raw(provider: str, messages: list[dict[str, str]]) -> str:
    """Run the expansion messages through the chosen provider, return raw text."""
    if provider == "claude":
        import anthropic

        api_key = (settings.anthropic_api_key or "").strip()
        if not api_key:
            raise ValueError("Claude (personal Anthropic) API key is not configured")
        client = anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        resp = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    # default: gemma via LiteLLM (json_mode nudges valid JSON out of the model)
    return chat_completion(messages, model=None, json_mode=True, max_tokens=2048)


@lru_cache(maxsize=1)
def _sections() -> dict[str, str]:
    """Parse the ``[SECTION]``-delimited system-prompt file into a dict."""
    raw = _PROMPT_FILE.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and " " not in stripped:
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current = stripped[1:-1].strip().lower()
            lines = []
        else:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    if "system" not in sections:
        raise ValueError("ideogram_magic_prompt_v1.txt has no [SYSTEM] section")
    return sections


def aspect_ratio_from_size(width: int, height: int) -> str:
    divisor = gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


def _build_messages(prompt: str, aspect_ratio: str) -> list[dict[str, str]]:
    sec = _sections()
    template = sec.get("user") or "TARGET IMAGE ASPECT RATIO: {{aspect_ratio}} (width:height)."
    user = template.replace("{{aspect_ratio}}", aspect_ratio)
    if "{{original_prompt}}" in user:
        user = user.replace("{{original_prompt}}", prompt)
    else:
        user = f"{user}\n\n{prompt}"
    return [
        {"role": "system", "content": sec["system"]},
        {"role": "user", "content": user},
    ]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _normalize_caption(caption: Any) -> Any:
    """Repair common small-model deviations so the renderer accepts the caption.

    Gemma reliably produces the right *content* but sometimes drifts on exact
    key names / enum spellings (e.g. ``compositional_decomposition`` instead of
    ``compositional_deconstruction``, or ``type:"obj"`` instead of ``"object"``).
    Ideogram's renderer needs the canonical spellings, so we coerce them here.
    """
    if not isinstance(caption, dict):
        return caption

    # Canonicalize the compositional_deconstruction key.
    if "compositional_deconstruction" not in caption:
        for key in list(caption.keys()):
            normalized = key.lower().replace("-", "_")
            if normalized.startswith("compositional") or normalized in ("composition", "scene", "layout"):
                caption["compositional_deconstruction"] = caption.pop(key)
                break

    cd = caption.get("compositional_deconstruction")
    if isinstance(cd, dict):
        cd.setdefault("background", "")
        elements = cd.get("elements")
        if isinstance(elements, list):
            for el in elements:
                if isinstance(el, dict):
                    t = str(el.get("type", "")).lower()
                    el["type"] = "text" if ("text" in t or t == "txt") else "object"
                    # bbox is optional in the schema (auto-placement), but the box
                    # editor needs a concrete [y_min,x_min,y_max,x_max] to show and
                    # edit. Give unplaced elements a large default the user can drag.
                    bbox = el.get("bbox")
                    if isinstance(bbox, list) and len(bbox) == 4 and all(
                        isinstance(v, (int, float)) for v in bbox
                    ):
                        el["bbox"] = [int(v) for v in bbox]
                    else:
                        el["bbox"] = [100, 100, 900, 900]
    return caption


def _valid_caption(caption: Any) -> bool:
    if not isinstance(caption, dict):
        return False
    cd = caption.get("compositional_deconstruction")
    return isinstance(cd, dict) and isinstance(cd.get("elements"), list)


def expand_prompt_to_caption(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    provider: str = "gemma",
) -> dict:
    """Return a structured caption dict for ``prompt`` (raises on failure).

    ``provider`` selects the rewriting model ("gemma" or "claude"). Retries once
    — smaller models occasionally emit malformed JSON for this strict schema; a
    normalization pass plus a second sample usually recovers it.
    """
    if provider not in MAGIC_PROVIDERS:
        provider = "gemma"
    aspect = aspect_ratio_from_size(width, height)
    messages = _build_messages(prompt, aspect)
    last_err: Exception | None = None
    for attempt in range(2):
        raw = _llm_raw(provider, messages)
        try:
            caption = _normalize_caption(json.loads(_strip_fences(raw)))
        except json.JSONDecodeError as exc:
            last_err = exc
            log.warning("magic-prompt attempt %d: invalid JSON (%s)", attempt + 1, exc)
            continue
        if _valid_caption(caption):
            return caption
        last_err = ValueError("caption missing compositional_deconstruction.elements")
        log.warning("magic-prompt attempt %d: %s", attempt + 1, last_err)
    raise ValueError(f"magic-prompt could not produce a valid caption: {last_err}")
