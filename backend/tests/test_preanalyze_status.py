from routers.papers import preanalyze_status
from services import ingest_analysis_cache as cache


def test_preanalyze_status_ready_includes_meta_without_raw_text(monkeypatch):
    monkeypatch.setattr(cache, "get_status", lambda key: {"analysis_key": key, "status": "ready"})
    monkeypatch.setattr(
        cache,
        "load_result",
        lambda key: {
            "meta": {
                "title": "Gemma Title",
                "authors": ["A. Author"],
                "metadata_source": "llm",
                "raw_text": "very long full text",
            },
            "tag_suggestions": {"existing": ["AI"], "new": [], "all_tags": ["AI"]},
        },
    )

    out = preanalyze_status("k1")

    assert out["status"] == "ready"
    assert out["meta"]["title"] == "Gemma Title"
    assert out["meta"]["authors"] == ["A. Author"]
    assert "raw_text" not in out["meta"]
    assert out["tag_suggestions"]["existing"] == ["AI"]


def test_preanalyze_status_not_ready_skips_result_load(monkeypatch):
    called = {"load_result": False}

    monkeypatch.setattr(cache, "get_status", lambda key: {"analysis_key": key, "status": "pending"})

    def _fail_if_called(_key: str):
        called["load_result"] = True
        raise AssertionError("load_result should not be called when status is not ready")

    monkeypatch.setattr(cache, "load_result", _fail_if_called)

    out = preanalyze_status("k2")

    assert out == {"analysis_key": "k2", "status": "pending"}
    assert called["load_result"] is False
