"""Search over several namespaces at once (library + feed)."""
from __future__ import annotations

import numpy as np
import pytest

from services import vectorstore
from services.conferences import embedder
from services.vectorstore.similar import find_similar, find_similar_text
from tests.vectorstore_helpers import unit

D = 384


@pytest.fixture
def two_namespaces():
    rng = np.random.default_rng(1)
    V = unit(rng, 20, D)
    lib = vectorstore.get_store("library")
    lib.upsert([f"p{i}" for i in range(10)], V[:10], [{"kind": "paper", "source": "library"}] * 10)
    feed = vectorstore.get_store("feed")
    feed.upsert([f"c{i}" for i in range(10)], V[10:], [{"kind": "candidate", "source": "arxiv", "published": f"2026-11-{10 + i:02d}"}
                                                        for i in range(10)])
    return V


def test_results_from_both_namespaces_are_merged_by_score(two_namespaces):
    V = two_namespaces
    res = find_similar(V[12], k=5)
    assert res.hits[0].namespace == "feed" and res.hits[0].id == "c2" and res.hits[0].score == pytest.approx(1.0, abs=1e-5)
    assert res.skipped == {}
    scores = [h.score for h in res.hits]
    assert scores == sorted(scores, reverse=True) and len(res.hits) == 5
    both = find_similar(V[3], k=20)
    assert {h.namespace for h in both.hits} == {"library", "feed"}
    brute = sorted(((float(V[i] @ V[3]), ("library" if i < 10 else "feed")) for i in range(20)), reverse=True)[:20]
    np.testing.assert_allclose([h.score for h in both.hits], [s for s, _ in brute], atol=1e-5)


def test_a_filter_is_applied_in_every_namespace(two_namespaces):
    V = two_namespaces
    res = find_similar(V[3], k=20, filter={"kind": "candidate", "published": {"gte": "2026-11-15"}})
    assert {h.namespace for h in res.hits} == {"feed"} and len(res.hits) == 5
    assert all(h.metadata["published"] >= "2026-11-15" for h in res.hits)


def test_missing_and_stale_namespaces_are_skipped_and_named(two_namespaces, monkeypatch):
    V = two_namespaces
    res = find_similar(V[0], namespaces=("library", "feed", "nothing"), k=3)
    assert res.skipped == {"nothing": "missing"}
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    stale = find_similar(np.ones(768, np.float32), k=3)
    assert stale.hits == [] and stale.skipped == {"library": "stale", "feed": "stale"}


def test_text_search_embeds_with_the_configured_model(two_namespaces, monkeypatch):
    V = two_namespaces
    seen = []
    monkeypatch.setattr(embedder, "ready", lambda: True)
    monkeypatch.setattr(embedder, "embed_query", lambda t: seen.append(t) or V[5])
    res = find_similar_text("a pasted abstract about something", k=2)
    assert seen == ["a pasted abstract about something"] and res.hits[0].id == "p5"
    assert find_similar_text("   ").hits == []
    monkeypatch.setattr(embedder, "ready", lambda: False)
    monkeypatch.setattr(embedder, "remote_url", lambda: "")
    with pytest.raises(RuntimeError):
        find_similar_text("x")
