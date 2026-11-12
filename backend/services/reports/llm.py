"""One ``complete()`` over the models a report can be written with.

``fast``        the app's fast provider (LiteLLM, Anthropic Haiku or OpenAI) via
                ``services.litellm_client.chat_completion``
``claude``      the user's personal Anthropic key, ``REPORTS_CLAUDE_MODEL``
``claude-work`` the work gateway key, same model

The Anthropic clients read the effective AI config of the request user, so the job thread sets
the report owner as request user before calling.
"""
from __future__ import annotations

import json
import logging
import re

from config import settings

log = logging.getLogger(__name__)

MODELS = ("fast", "claude", "claude-work")
DEFAULT_MODEL = "fast"
_FENCE = re.compile(r"^```[\w-]*\s*|\s*```$")


def claude_label(model_id: str | None = None) -> str:
    """``claude-sonnet-4-6`` -> ``Claude Sonnet 4.6``."""
    name = re.sub(r"-\d{8}$", "", model_id or settings.reports_claude_model)
    name = re.sub(r"^claude-", "", name)
    name = re.sub(r"(\d)-(\d)", r"\1.\2", name)
    return "Claude " + " ".join(w.capitalize() for w in name.split("-"))


def model_label(model: str) -> str:
    """Human label of a model id as used in the UI and the HTML export."""
    if model == "claude":
        return claude_label()
    if model == "claude-work":
        return claude_label() + " (work)"
    try:
        from services import litellm_client

        return litellm_client.fast_model_label()
    except Exception:  # noqa: BLE001
        return "fast model"


def available_models(username: str | None = None) -> list[dict]:
    """``[{"id", "label", "available"}]`` for the three models."""
    fast = False
    try:
        from services import litellm_client

        fast = litellm_client.fast_provider() is not None
    except Exception:  # noqa: BLE001
        pass
    personal = work = False
    try:
        from services.user_ai_config import get_effective_ai_config

        cfg = get_effective_ai_config(username)
        personal = bool((cfg.get("anthropic_api_key") or "").strip())
        work = bool((cfg.get("anthropic_work_api_key") or "").strip())
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read the AI config: %s", exc)
    return [
        {"id": "fast", "label": model_label("fast"), "available": fast},
        {"id": "claude", "label": model_label("claude"), "available": personal},
        {"id": "claude-work", "label": model_label("claude-work"), "available": work},
    ]


def evidence_budget(model: str) -> int:
    """Characters of evidence per section: the setting, else 20,000 on LiteLLM, 60,000 elsewhere."""
    if settings.reports_evidence_chars > 0:
        return settings.reports_evidence_chars
    if model == "fast":
        try:
            from services import litellm_client

            if litellm_client.fast_provider() == "litellm":
                return 20_000
        except Exception:  # noqa: BLE001
            return 20_000
    return 60_000


def _anthropic_client(model: str):
    from services import ai

    return ai._work_client() if model == "claude-work" else ai._personal_client()


def complete(messages: list[dict], *, model: str, max_tokens: int, json_mode: bool = False) -> str:
    """Run one chat completion and return the text. Raises on provider errors."""
    if model not in MODELS:
        raise ValueError(f"Unknown report model: {model}")
    if model == "fast":
        from services import litellm_client

        return litellm_client.chat_completion(
            messages, json_mode=json_mode, max_tokens=max_tokens, timeout=300
        )
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") != "system"]
    if json_mode:
        system = (system + "\n\nReply with one JSON object and nothing else.").strip()
    kwargs = {"system": system} if system else {}
    response = _anthropic_client(model).messages.create(
        model=settings.reports_claude_model, max_tokens=max_tokens, messages=turns, **kwargs
    )
    return "".join(getattr(b, "text", "") for b in response.content).strip()


def parse_json(text: str) -> dict:
    """The outermost ``{...}`` of a model reply (code fences stripped); ValueError if none."""
    cleaned = _FENCE.sub("", (text or "").strip()).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object in the model reply")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in the model reply: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("The model reply is not a JSON object")
    return data
