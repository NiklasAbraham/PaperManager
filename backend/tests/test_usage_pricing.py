"""Price table and cost computation (services/usage/pricing.py)."""
import json

import pytest

from config import settings
from services.usage import pricing


@pytest.mark.parametrize(
    "model, prefix",
    [
        ("claude-opus-4-5", "claude-opus-4-5"),
        ("claude-opus-4-5-20251101", "claude-opus-4-5"),
        ("claude-opus-4-8", "claude-opus-4-8"),
        ("claude-opus-4-1-20250805", "claude-opus-4-1"),
        ("claude-opus-4-20250514", "claude-opus-4"),
        ("claude-opus-4-0", "claude-opus-4"),
        ("claude-opus-5", "claude-opus-5"),
        ("claude-opus-5-5", "claude-opus-5-5"),
        ("claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("claude-haiku-4-5-20251001", "claude-haiku-4-5"),
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5"),
        ("anthropic/claude-3-5-haiku-latest", "claude-3-5-haiku"),
        ("eu.anthropic.claude-sonnet-5", "claude-sonnet-5"),
        ("openai/gpt-5-mini", "gpt-5-mini"),
        ("gpt-5", "gpt-5"),
        ("gpt-5-nano-2026-01-01", "gpt-5-nano"),
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("gpt-4o-2024-08-06", "gpt-4o"),
        ("GPT-4.1-mini", "gpt-4.1-mini"),
        ("o4-mini", "o4-mini"),
    ],
)
def test_longest_prefix_match(model, prefix):
    assert pricing.price_for(model) == pricing.PRICES[prefix]


def test_unknown_and_empty_model():
    assert pricing.price_for("gemma-3-27b") is None
    assert pricing.price_for("") is None
    assert pricing.price_for(None) is None


def test_every_row_has_four_numbers():
    for prefix, row in pricing.PRICES.items():
        assert prefix == prefix.lower()
        assert len(row) == 4 and all(isinstance(v, float) for v in row)


def test_cost_anthropic_with_cache():
    # haiku 4.5: 1 / 5 / 1.25 / 0.1 per MTok
    cost, known = pricing.cost("anthropic", "claude-haiku-4-5-20251001", 1_000_000, 200_000, 500_000, 100_000)
    assert known
    assert cost == pytest.approx(1.0 + 1.0 + 0.05 + 0.125)


def test_cost_unknown_model_is_none():
    assert pricing.cost("anthropic-gateway", "mystery-1", 10, 10) == (None, False)


def test_litellm_is_free_by_default(monkeypatch):
    assert pricing.cost("litellm", "gemma-3-27b", 5000, 5000) == (0.0, True)
    monkeypatch.setattr(settings, "usage_litellm_free", False)
    assert pricing.cost("litellm", "gemma-3-27b", 5000, 5000) == (None, False)
    cost, known = pricing.cost("litellm", "gpt-5-mini", 1_000_000, 0)
    assert known and cost == pytest.approx(0.25)


def test_claude_code_reported_cost_wins_and_alias_fallback():
    assert pricing.cost("claude-code", "opus", 10, 10, reported_cost=0.1234) == (0.1234, True)
    cost, known = pricing.cost("claude-code", "opus", 1_000_000, 0)
    assert known and cost == pytest.approx(4.0)  # alias -> claude-opus-5-5
    cost, known = pricing.cost("claude-code", "haiku", 1_000_000, 0)
    assert known and cost == pytest.approx(1.0)


def test_prices_file_overrides_and_extends(tmp_path, monkeypatch):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"claude-haiku-4-5": [2, 10, 2.5, 0.2], "my-model": [1, 2]}))
    monkeypatch.setattr(settings, "usage_prices_file", str(path))
    assert pricing.price_for("claude-haiku-4-5-20251001") == (2.0, 10.0, 2.5, 0.2)
    assert pricing.price_for("my-model-v2") == (1.0, 2.0, 0.0, 0.0)
    assert pricing.price_for("claude-sonnet-4-6") == pricing.PRICES["claude-sonnet-4-6"]
    assert "my-model" in pricing.price_table()


def test_bad_prices_file_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "prices.json"
    path.write_text("not json")
    monkeypatch.setattr(settings, "usage_prices_file", str(path))
    assert pricing.price_for("claude-haiku-4-5") == pricing.PRICES["claude-haiku-4-5"]
