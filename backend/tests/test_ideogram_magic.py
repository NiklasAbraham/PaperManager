"""Tests for the Gemma-powered magic-prompt expansion (plain text → boxes)."""
import json
import pytest
from unittest.mock import patch

import services.ideogram_magic as im

VALID = {
    "aspect_ratio": "1:1",
    "high_level_description": "a poster",
    "compositional_deconstruction": {
        "background": "white",
        "elements": [{"type": "text", "bbox": [0, 0, 100, 100], "text": "HI"}],
    },
}


def test_aspect_ratio_from_size():
    assert im.aspect_ratio_from_size(1024, 1024) == "1:1"
    assert im.aspect_ratio_from_size(1536, 1024) == "3:2"


def test_expand_parses_caption():
    with patch.object(im, "chat_completion", return_value=json.dumps(VALID)):
        out = im.expand_prompt_to_caption("a poster", 1024, 1024)
    assert out["compositional_deconstruction"]["elements"][0]["text"] == "HI"


def test_expand_strips_code_fences():
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    with patch.object(im, "chat_completion", return_value=fenced):
        out = im.expand_prompt_to_caption("x")
    assert "compositional_deconstruction" in out


def test_expand_retries_then_succeeds():
    with patch.object(im, "chat_completion", side_effect=["not json", json.dumps(VALID)]):
        out = im.expand_prompt_to_caption("x")
    assert out["compositional_deconstruction"]["elements"][0]["text"] == "HI"


def test_expand_raises_on_persistent_bad_output():
    with patch.object(im, "chat_completion", side_effect=["nope", '{"no":"elements"}']):
        with pytest.raises(ValueError):
            im.expand_prompt_to_caption("x")


def test_system_prompt_bundled_and_parsed():
    sec = im._sections()
    assert "system" in sec and len(sec["system"]) > 100  # the real v1 prompt is large


def test_normalize_fixes_decomposition_key():
    # Gemma sometimes emits 'compositional_decomposition' — coerce to the canonical key.
    raw = {"compositional_decomposition": {"background": "w", "elements": [{"type": "obj", "bbox": [0, 0, 1, 1]}]}}
    out = im._normalize_caption(raw)
    assert "compositional_deconstruction" in out
    assert out["compositional_deconstruction"]["elements"][0]["type"] == "object"


def test_normalize_maps_text_type_variants():
    raw = {"compositional_deconstruction": {"elements": [{"type": "txt"}, {"type": "Text Element"}]}}
    out = im._normalize_caption(raw)
    assert out["compositional_deconstruction"]["elements"][0]["type"] == "text"
    assert out["compositional_deconstruction"]["elements"][1]["type"] == "text"


def test_expand_recovers_from_decomposition_key():
    bad_key = {"compositional_decomposition": {"background": "w", "elements": [{"type": "obj", "bbox": [0, 0, 1, 1]}]}}
    with patch.object(im, "_llm_raw", return_value=json.dumps(bad_key)):
        out = im.expand_prompt_to_caption("x", provider="gemma")
    assert out["compositional_deconstruction"]["elements"][0]["type"] == "object"


def test_expand_invalid_provider_falls_back_to_gemma():
    with patch.object(im, "_llm_raw", return_value=json.dumps(VALID)) as m:
        im.expand_prompt_to_caption("x", provider="bogus")
    assert m.call_args[0][0] == "gemma"


def test_normalize_defaults_missing_bbox():
    raw = {"compositional_deconstruction": {"elements": [{"type": "text", "text": "HI"}]}}
    out = im._normalize_caption(raw)
    bbox = out["compositional_deconstruction"]["elements"][0]["bbox"]
    assert isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, int) for v in bbox)
