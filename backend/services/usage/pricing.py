"""List prices (USD per million tokens) and the cost of one LLM call.

Rows are ``(input, output, cache_write_5m, cache_read)``. A model id is matched by the
longest prefix after normalising it (lower case, provider prefixes dropped), so dated ids
such as ``claude-haiku-4-5-20251001`` hit ``claude-haiku-4-5`` and ``claude-opus-4-5`` is
never swallowed by the shorter ``claude-opus-4``. ``USAGE_PRICES_FILE`` (JSON
``{"model-prefix": [in, out, cache_write, cache_read]}``) adds or overrides rows.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from config import settings

log = logging.getLogger(__name__)

PRICES_AS_OF = "2026-11-12"

_FABLE_5_1 = (10.0, 50.0, 12.5, 0.25)
_FABLE_5 = (10.0, 50.0, 12.5, 1.0)
_OPUS_5 = (5.0, 25.0, 6.25, 0.5)
_OPUS_4 = (15.0, 75.0, 18.75, 1.5)
_SONNET_3 = (3.0, 15.0, 3.75, 0.3)
_SONNET_5 = (2.0, 10.0, 2.5, 0.2)

PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": _FABLE_5_1,
    "claude-fable-5": _FABLE_5,
    "claude-mythos-5-1": _FABLE_5_1,
    "claude-mythos-5": _FABLE_5,
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-opus-5": _OPUS_5,
    "claude-opus-4-8": _OPUS_5,
    "claude-opus-4-7": _OPUS_5,
    "claude-opus-4-6": _OPUS_5,
    "claude-opus-4-5": _OPUS_5,
    "claude-opus-4-1": _OPUS_4,
    "claude-opus-4": _OPUS_4,
    "claude-3-opus": _OPUS_4,
    "claude-sonnet-5-5": _SONNET_5,
    "claude-sonnet-5": _SONNET_5,
    "claude-sonnet-4-6": _SONNET_3,
    "claude-sonnet-4-5": _SONNET_3,
    "claude-sonnet-4": _SONNET_3,
    "claude-3-7-sonnet": _SONNET_3,
    "claude-3-5-sonnet": _SONNET_3,
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.1),
    "claude-3-5-haiku": (0.8, 4.0, 1.0, 0.08),
    "claude-3-haiku": (0.25, 1.25, 0.3, 0.03),
    "gpt-5": (1.25, 10.0, 0.0, 0.125),
    "gpt-5-mini": (0.25, 2.0, 0.0, 0.025),
    "gpt-5-nano": (0.05, 0.4, 0.0, 0.005),
    "gpt-4.1": (2.0, 8.0, 0.0, 0.5),
    "gpt-4.1-mini": (0.4, 1.6, 0.0, 0.1),
    "gpt-4.1-nano": (0.1, 0.4, 0.0, 0.025),
    "gpt-4o": (2.5, 10.0, 0.0, 1.25),
    "gpt-4o-mini": (0.15, 0.6, 0.0, 0.075),
    "o3": (2.0, 8.0, 0.0, 0.5),
    "o3-mini": (1.1, 4.4, 0.0, 0.55),
    "o4-mini": (1.1, 4.4, 0.0, 0.275),
    # OpenAI embeddings (input only)
    "text-embedding-3-small": (0.02, 0.0, 0.0, 0.0),
    "text-embedding-3-large": (0.13, 0.0, 0.0, 0.0),
    "text-embedding-ada-002": (0.10, 0.0, 0.0, 0.0),
}

# The Claude Code CLI reports its own cost; this is the fallback for the aliases it is given.
_CLAUDE_CODE_ALIASES = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-4-5"}

_PREFIXES = ("anthropic/", "openai/", "us.anthropic.", "eu.anthropic.", "anthropic.")

_overrides_cache: tuple[str, float, dict[str, tuple[float, float, float, float]]] | None = None


def normalise(model: str | None) -> str:
    """Lower-case model id without provider prefixes."""
    name = re.sub(r"\[[^\]]*\]$", "", (model or "").strip().lower())  # Claude Code's "[1m]" context suffix
    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                changed = True
    return name


def _row(values: object) -> Optional[tuple[float, float, float, float]]:
    try:
        nums = [float(v) for v in values]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return None
    if not 2 <= len(nums) <= 4:
        return None
    nums += [0.0] * (4 - len(nums))
    return (nums[0], nums[1], nums[2], nums[3])


def _overrides() -> dict[str, tuple[float, float, float, float]]:
    """Rows from USAGE_PRICES_FILE (re-read when the file changes)."""
    global _overrides_cache
    path = (settings.usage_prices_file or "").strip()
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
        if _overrides_cache and _overrides_cache[0] == path and _overrides_cache[1] == mtime:
            return _overrides_cache[2]
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        rows = {normalise(k): r for k, v in raw.items() if (r := _row(v)) is not None}
        _overrides_cache = (path, mtime, rows)
        return rows
    except Exception as exc:  # noqa: BLE001 — a bad file must not break recording
        log.warning("USAGE_PRICES_FILE %s unreadable: %s", path, exc)
        return {}


def price_table() -> dict[str, tuple[float, float, float, float]]:
    """Built-in rows with the overrides applied."""
    return {**PRICES, **_overrides()}


def price_for(model: str | None) -> Optional[tuple[float, float, float, float]]:
    """Row of the longest table prefix of *model*, or None when unknown."""
    name = normalise(model)
    if not name:
        return None
    table = price_table()
    best = None
    for prefix in table:
        if name.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return table[best] if best else None


def cost(
    provider: str,
    model: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reported_cost: float | None = None,
) -> tuple[Optional[float], bool]:
    """``(cost_usd, price_known)`` of one call at list price.

    LiteLLM is free (own hardware) unless USAGE_LITELLM_FREE is off; a cost reported by the
    Claude Code CLI wins over the table; an unknown model gives ``(None, False)``.
    """
    if provider == "litellm" and settings.usage_litellm_free:
        return 0.0, True
    if reported_cost is not None:
        return round(float(reported_cost), 8), True
    name = model
    if provider == "claude-code":
        name = _CLAUDE_CODE_ALIASES.get(normalise(model), model)
    row = price_for(name)
    if row is None:
        return None, False
    p_in, p_out, p_cw, p_cr = row
    total = (
        input_tokens * p_in + output_tokens * p_out + cache_write_tokens * p_cw + cache_read_tokens * p_cr
    ) / 1_000_000
    return round(total, 8), True
