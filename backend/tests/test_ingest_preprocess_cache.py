"""Tests for upload-queue Docling preprocess cache."""
import json

import pytest

from services import ingest_preprocess_cache as cache


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(cache, "_events", {})
    yield


def test_pdf_cache_key_stable():
    pdf = b"same bytes"
    assert cache.pdf_cache_key(pdf) == cache.pdf_cache_key(pdf)
    assert cache.pdf_cache_key(pdf) != cache.pdf_cache_key(b"other")


def test_get_status_missing():
    assert cache.get_status("nonexistent")["status"] == "missing"


def test_ensure_started_idempotent_when_ready():
    pdf = b"%PDF-1.4 test"
    key = cache.pdf_cache_key(pdf)
    cache._entry_dir(key).mkdir(parents=True)
    cache._write_status(key, "ready", caption_method="docling")
    cache._result_path(key).write_text(json.dumps({"figures": [], "tables": []}), encoding="utf-8")

    r1 = cache.ensure_started(pdf, caption_method="docling")
    r2 = cache.ensure_started(pdf, caption_method="docling")
    assert r1["preprocess_key"] == r2["preprocess_key"] == key
    assert r1["status"] == "ready"
    assert r2["status"] == "ready"


def test_load_result_with_figure_bytes():
    pdf = b"pdf"
    key = cache.pdf_cache_key(pdf)
    fig_dir = cache._figures_dir(key)
    fig_dir.mkdir(parents=True)
    (fig_dir / "0.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    cache._write_status(key, "ready")
    cache._result_path(key).write_text(
        json.dumps({
            "figures": [{
                "page_number": 1,
                "figure_number": 1,
                "caption": "Figure 1: test",
                "file": "figures/0.png",
            }],
            "tables": [{"page_number": 2, "table_number": 1, "caption": "Table 1", "markdown_content": "|a|"}],
        }),
        encoding="utf-8",
    )
    result = cache.load_result(key)
    assert result is not None
    assert len(result["figures"]) == 1
    assert result["figures"][0]["image_bytes"].startswith(b"\x89PNG")
    assert len(result["tables"]) == 1
