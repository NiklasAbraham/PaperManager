"""The SQLite sidecar: candidates, retention, labels, per-user config, library cache."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from services.feed import config
from services.feed.store import Candidate, FeedStore, get_store, reset
from tests.feed_helpers import topic_vec


@pytest.fixture
def st(tmp_path):
    s = FeedStore(tmp_path / "feed.sqlite")
    yield s
    s.close()


def cand(n: int, source="arxiv", published="2026-11-17T10:00:00Z", **kw) -> Candidate:
    ext = f"2611.{n:05d}"
    return Candidate(id=f"{source}:{ext}", source=source, ext_id=ext, title=f"Paper {n}", published=published,
                     authors=["Ada Example"], abstract="abstract", url=f"https://example.invalid/{n}",
                     categories=["cs.LG"], **kw)


def test_upsert_counts_new_and_leaves_known_alone(st):
    assert st.upsert_candidates([cand(1), cand(2)]) == 2
    st.set_embeddings({"arxiv:2611.00001": topic_vec(1, "a")})
    changed = cand(1)
    changed.title = "A new title"
    assert st.upsert_candidates([changed, cand(3)]) == 1
    got = st.get("arxiv:2611.00001")
    assert got.title == "Paper 1" and got.emb is not None            # unchanged, embedding kept
    assert got.authors == ["Ada Example"] and got.categories == ["cs.LG"]
    assert st.known_ids(["arxiv:2611.00001", "arxiv:nope"]) == {"arxiv:2611.00001"}


def test_unique_on_source_and_external_id(st):
    st.upsert_candidates([cand(1)])
    twin = cand(1)
    twin.id = "arxiv:other-spelling"
    assert st.upsert_candidates([twin]) == 0
    assert st.counts()["candidates"] == 1


def test_embeddings_roundtrip_and_pending(st):
    st.upsert_candidates([cand(1), cand(2)])
    assert {c.id for c in st.without_embedding()} == {"arxiv:2611.00001", "arxiv:2611.00002"}
    v = topic_vec(2, "x")
    st.set_embeddings({"arxiv:2611.00001": v})
    assert [c.id for c in st.without_embedding()] == ["arxiv:2611.00002"]
    np.testing.assert_allclose(st.get("arxiv:2611.00001").emb, v)
    assert set(st.get_embeddings(["arxiv:2611.00001", "arxiv:2611.00002"])) == {"arxiv:2611.00001"}
    assert st.counts() == {"candidates": 2, "embedded": 1}


def test_embedded_since_filters_by_date_and_orders_newest_first(st):
    st.upsert_candidates([cand(1, published="2026-11-10T00:00:00Z"), cand(2, published="2026-11-17T00:00:00Z"),
                          cand(3, published="2026-11-15T00:00:00Z")])
    st.set_embeddings({c: topic_vec(0, c) for c in ("arxiv:2611.00001", "arxiv:2611.00002", "arxiv:2611.00003")})
    assert [c.id for c in st.embedded_since("2026-11-14")] == ["arxiv:2611.00002", "arxiv:2611.00003"]


def test_sample_is_reproducible_excludes_and_caps(st):
    st.upsert_candidates([cand(i) for i in range(40)])
    st.set_embeddings({f"arxiv:2611.{i:05d}": topic_vec(i % 8, str(i)) for i in range(40)})
    a = st.sample_embeddings(set(), 10)
    b = st.sample_embeddings(set(), 10)
    assert a.shape == (10, 384) and np.array_equal(a, b)
    assert st.sample_embeddings({f"arxiv:2611.{i:05d}" for i in range(40)}, 10).shape == (0, 384)
    assert st.sample_embeddings({f"arxiv:2611.{i:05d}" for i in range(35)}, 10).shape == (5, 384)


def test_retention_deletes_old_but_keeps_rated(st):
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="seconds")
    st.upsert_candidates([cand(1, fetched_at=old), cand(2, fetched_at=old), cand(3)])
    st.set_label("alice", "arxiv:2611.00002", 1)
    assert st.purge(30) == 1
    assert {i for i in st.known_ids([f"arxiv:2611.{n:05d}" for n in (1, 2, 3)])} == {"arxiv:2611.00002", "arxiv:2611.00003"}


def test_labels_are_per_user_and_replaceable(st):
    st.upsert_candidates([cand(1)])
    st.set_label("alice", "arxiv:2611.00001", 1)
    st.set_label("bob", "arxiv:2611.00001", -1)
    assert st.labels("alice")["arxiv:2611.00001"][0] == 1
    assert st.labels("bob")["arxiv:2611.00001"][0] == -1
    st.set_label("alice", "arxiv:2611.00001", 0)
    assert st.labels("alice")["arxiv:2611.00001"][0] == 0 and st.labels("bob")["arxiv:2611.00001"][0] == -1
    st.clear_label("alice", "arxiv:2611.00001")
    assert st.labels("alice") == {}
    with pytest.raises(ValueError):
        st.set_label("alice", "arxiv:2611.00001", 5)


def test_sql_injection_in_ids_and_users_is_inert(st):
    st.upsert_candidates([cand(1)])
    evil = "x'; DROP TABLE candidate; --"
    st.set_label(evil, evil, 1)
    assert st.get(evil) is None
    assert st.labels(evil)[evil][0] == 1
    assert st.counts()["candidates"] == 1


def test_config_roundtrip_default_and_all(st):
    assert st.get_config("alice") is None
    cfg = config.FeedConfig(sources=["arxiv", "biorxiv"], arxiv_categories=["cs.LG", "q-bio.BM"], digest_days=5,
                            min_score=0.25)
    st.set_config("alice", cfg)
    st.set_config("bob", config.FeedConfig(arxiv_categories=["cs.CV"]))
    assert st.get_config("alice") == cfg
    assert set(st.all_configs()) == {"alice", "bob"}


def test_runs_and_fetch_state(st):
    assert st.last_run() is None
    rid = st.start_run()
    assert st.last_run() is None                      # not finished yet
    st.finish_run(rid, source="arxiv", fetched=10, new=4, embedded=4, error=None)
    last = st.last_run()
    assert (last["fetched"], last["new"], last["embedded"], last["error"]) == (10, 4, 4, None)
    assert st.get_since("arxiv:cs.LG") is None
    st.set_since("arxiv:cs.LG", "2026-11-17T00:00:00+00:00")
    st.set_since("arxiv:cs.LG", "2026-11-18T00:00:00+00:00")
    assert st.get_since("arxiv:cs.LG") == "2026-11-18T00:00:00+00:00"


def test_library_embedding_cache(st):
    st.set_library_embeddings({"p1": ("h1", topic_vec(0, "p1")), "p2": ("h2", topic_vec(1, "p2"))})
    assert st.library_hashes() == {"p1": "h1", "p2": "h2"}
    st.set_library_embeddings({"p1": ("h1b", topic_vec(2, "p1b"))})
    ids, mat = st.library_embeddings()
    assert ids == ["p1", "p2"] and mat.shape == (2, 384)
    st.delete_library_embeddings(["p1"])
    assert st.library_hashes() == {"p2": "h2"}


def test_concurrent_writers_do_not_corrupt(st):
    import threading

    def work(k):
        st.upsert_candidates([cand(k * 100 + i) for i in range(50)])
        st.set_label(f"u{k}", f"arxiv:2611.{k * 100:05d}", 1)

    threads = [threading.Thread(target=work, args=(k,)) for k in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert st.counts()["candidates"] == 300


def test_get_store_follows_the_directory_and_creates_it_lazily(tmp_path, monkeypatch):
    first, second = tmp_path / "one", tmp_path / "two"
    monkeypatch.setenv("PAPER_FEED_DIR", str(first))
    reset()
    assert not first.exists()
    a = get_store()
    assert a is get_store() and (first / "feed.sqlite").exists()
    monkeypatch.setenv("PAPER_FEED_DIR", str(second))
    b = get_store()
    assert b is not a and (second / "feed.sqlite").exists()
    reset()


def test_config_validation_helpers():
    assert config.CATEGORY_RE.match("cs.LG") and config.CATEGORY_RE.match("q-bio.BM") and config.CATEGORY_RE.match("math")
    for bad in ("CS.LG", "cs.", "cs.L G", "cs/LG", "../x", ""):
        assert not config.CATEGORY_RE.match(bad)
    cfg = config.FeedConfig.from_dict({"sources": ["arxiv", "nope", "arxiv"], "arxiv_categories": ["cs.LG", "BAD!", "cs.LG"],
                                       "digest_days": 99, "min_score": 7})
    assert cfg.sources == ["arxiv"] and cfg.arxiv_categories == ["cs.LG"]
    assert cfg.digest_days == 3 and cfg.min_score == 0.0
