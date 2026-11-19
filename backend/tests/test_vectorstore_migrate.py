"""Zero-downtime migration of the old files and blobs, and the semantic index / feed on the store.
Synthetic data only; the embedder is replaced by deterministic fakes, nothing is re-embedded."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import numpy as np
import pytest

from services import vectorstore
from services.conferences import embedder
from services.feed import library, pipeline
from services.feed.store import Candidate, FeedStore
from services.library_search import semantic
from services.vectorstore import migrate, model_config
from services.vectorstore.base import to_timestamp
from tests.vectorstore_helpers import unit

DEFAULT = model_config.DEFAULT_MODEL
OTHER_MODEL = "BAAI/bge-base-en-v1.5"      # 768 dims


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    d = tmp_path / "legacy"
    d.mkdir()
    monkeypatch.setenv("LIBRARY_SEARCH_DIR", str(d))
    monkeypatch.setattr(semantic, "_dir", None)
    monkeypatch.setattr(semantic, "_follow_store", None)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.delenv("CONFERENCE_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_DIM", raising=False)
    return d


def write_legacy(d: Path, ids, V, hashes=None, model=DEFAULT) -> None:
    np.save(d / "emb.npy", V.astype(np.float32))
    (d / "meta.json").write_text(json.dumps({
        "model": model, "dim": int(V.shape[1]), "ids": list(ids),
        "hashes": hashes or [f"h{i}" for i in range(len(ids))], "saved_at": "2026-01-01T00:00:00Z"}))


def digest(d: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir())}


def old_top_k(V, ids, q, k):
    """What semantic.query computed before the vector store: dot product, argpartition, sort."""
    sims = V @ q
    k = min(k, len(ids))
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    return [(ids[i], float(sims[i])) for i in top]


@pytest.fixture
def model_ready(monkeypatch):
    holder = {}
    monkeypatch.setattr(embedder, "ready", lambda: True)
    monkeypatch.setattr(embedder, "embed_query", lambda q: holder["q"])
    return holder


def boom(*a, **k):
    raise AssertionError("migration must not embed anything")


# ── library: emb.npy + meta.json -> the library namespace ────────────────────

def test_library_migration_gives_identical_top_k_without_embedding(legacy, monkeypatch, model_ready):
    rng = np.random.default_rng(1)
    V = unit(rng, 300, 384)
    ids = [f"paper-{i}" for i in range(300)]
    write_legacy(legacy, ids, V)
    before = digest(legacy)
    monkeypatch.setattr(embedder, "embed", boom)
    monkeypatch.setattr(embedder, "_load", boom)
    semantic._load()
    st = vectorstore.get_store("library")
    assert st.count() == 300 and st.manifest().model == DEFAULT and st.manifest().dim == 384
    assert st.metadata(["paper-7"])["paper-7"] == {"kind": "paper", "source": "library", "hash": "h7"}
    for q in unit(rng, 8, 384):
        model_ready["q"] = q
        for k in (1, 10, 100):
            got = semantic.query("anything", k=k)
            want = old_top_k(V, ids, q, k)
            assert [i for i, _ in got] == [i for i, _ in want]
            np.testing.assert_allclose([s for _, s in got], [s for _, s in want], atol=1e-6)
    assert digest(legacy) == before                                    # the old files are untouched
    marker = json.loads(migrate.marker_path("library").read_text())
    assert marker["count"] == 300 and marker["source"] == "emb.npy + meta.json"


def test_migration_runs_once_even_if_the_old_files_change_or_the_namespace_is_lost(legacy, model_ready):
    rng = np.random.default_rng(2)
    V = unit(rng, 20, 384)
    write_legacy(legacy, [f"p{i}" for i in range(20)], V)
    semantic._load()
    assert vectorstore.get_store("library").count() == 20
    write_legacy(legacy, ["x1", "x2"], unit(rng, 2, 384))             # later changes of the old file
    vectorstore.reset()
    semantic._load()
    assert vectorstore.get_store("library").count() == 20
    assert migrate.migrate_library(legacy) is None
    # the marker keeps a deliberately emptied namespace from being refilled with old data
    import shutil
    vectorstore.reset()
    shutil.rmtree(vectorstore.vector_dir() / "library" / "g000001")
    (vectorstore.vector_dir() / "library" / "CURRENT").unlink()
    assert migrate.migrate_library(legacy) is None
    semantic._load()
    assert vectorstore.get_store("library").count() == 0


def test_a_legacy_index_of_another_model_or_a_damaged_one_is_not_migrated(legacy):
    V = unit(np.random.default_rng(3), 10, 384)
    write_legacy(legacy, [f"p{i}" for i in range(10)], V, model="some/other-model")
    assert migrate.migrate_library(legacy) is None
    write_legacy(legacy, [f"p{i}" for i in range(9)], V)               # 9 ids, 10 rows
    assert migrate.migrate_library(legacy) is None
    write_legacy(legacy, [f"p{i}" for i in range(10)], V[:, :100])     # wrong dimension
    assert migrate.migrate_library(legacy) is None
    (legacy / "meta.json").write_text("{broken")
    assert migrate.migrate_library(legacy) is None
    assert not migrate.marker_path("library").exists()
    assert vectorstore.get_store("library", create=False) is None


def test_two_threads_migrating_at_once_build_it_once(legacy):
    V = unit(np.random.default_rng(4), 500, 384)
    write_legacy(legacy, [f"p{i}" for i in range(500)], V)
    results = []
    threads = [threading.Thread(target=lambda: results.append(migrate.migrate_library(legacy))) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r for r in results if r) == [500] and results.count(None) == 3
    assert vectorstore.get_store("library").count() == 500


def test_mcp_style_loading_migrates_and_follows(legacy, monkeypatch, model_ready):
    V = unit(np.random.default_rng(5), 15, 384)
    write_legacy(legacy, [f"p{i}" for i in range(15)], V)
    monkeypatch.setattr(embedder, "embed", boom)
    assert semantic.ensure_loaded() is True
    model_ready["q"] = V[3]
    assert semantic.query("x", k=1)[0][0] == "p3"


def test_a_disabled_semantic_index_touches_nothing(legacy, monkeypatch):
    monkeypatch.setenv("LIBRARY_SEMANTIC", "false")
    vectorstore.reset()
    root = vectorstore.vector_dir()
    assert semantic.query("x") == [] and semantic.status()["indexed"] == 0
    assert list(root.iterdir()) == []


# ── library: sync on the store ───────────────────────────────────────────────

def fake_embed_factory(calls: list):
    def fake(texts, **_):
        calls.append(list(texts))
        out = np.zeros((len(texts), model_config.dim()), dtype=np.float32)
        for i, t in enumerate(texts):
            seed = int(hashlib.sha1(t.encode()).hexdigest()[:8], 16)
            v = np.random.default_rng(seed).normal(size=model_config.dim())
            out[i] = v / np.linalg.norm(v)
        return out
    return fake


def test_sync_after_a_migration_embeds_only_what_changed(legacy, monkeypatch):
    texts = {f"p{i}": f"Title {i}\nAbstract {i}" for i in range(40)}
    rng = np.random.default_rng(6)
    ids = list(texts)[:30]
    write_legacy(legacy, ids, unit(rng, 30, 384), hashes=[semantic.text_hash(texts[i]) for i in ids])
    legacy_ids = set(ids)
    texts["p5"] = "Title 5 revised\nNew abstract"                     # changed text
    del texts["p6"], texts["p7"]                                      # deleted papers
    for i in range(100, 103):                                         # new papers
        texts[f"p{i}"] = f"Title {i}\nAbstract {i}"
    calls: list = []
    monkeypatch.setattr(embedder, "embed", fake_embed_factory(calls))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: dict(texts))
    semantic._load()
    out = semantic.sync(driver=object())
    assert out["embedded"] == 1 + 10 + 3 and out["removed"] == 3           # p5 changed; p30..p39 never indexed
    assert sorted(t for c in calls for t in c) == sorted([texts["p5"]] + [texts[f"p{i}"] for i in range(30, 40)]
                                                         + [texts[f"p{i}"] for i in range(100, 103)])
    st = vectorstore.get_store("library")
    assert set(st.ids()) == set(texts) and st.count() == len(texts)
    assert "p6" not in set(st.ids()) and legacy_ids - {"p6", "p7"} <= set(st.ids())
    assert semantic.status()["indexed"] == len(texts) and semantic.status()["state"] == "ready"
    calls.clear()
    assert semantic.sync(driver=object())["embedded"] == 0 and calls == []   # nothing left to do
    # emb.npy / meta.json follow the store (the topic map reads them)
    meta = json.loads((legacy / "meta.json").read_text())
    emb = np.load(legacy / "emb.npy")
    assert meta["ids"] == st.all_vectors()[0] and meta["model"] == DEFAULT and meta["dim"] == 384
    np.testing.assert_array_equal(emb, st.all_vectors()[1])
    assert meta["hashes"][meta["ids"].index("p5")] == semantic.text_hash(texts["p5"])


def test_a_fresh_install_builds_everything_and_writes_the_files(legacy, monkeypatch):
    texts = {f"q{i}": f"T{i}\nA{i}" for i in range(12)}
    calls: list = []
    monkeypatch.setattr(embedder, "embed", fake_embed_factory(calls))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: dict(texts))
    semantic._load()
    assert semantic.sync(driver=object())["embedded"] == 12
    assert (legacy / "emb.npy").exists() and json.loads((legacy / "meta.json").read_text())["ids"] == list(texts)
    assert semantic.status()["last_build_seconds"] is not None


def test_the_legacy_export_can_be_switched_off(legacy, monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_LEGACY_EXPORT", "0")
    monkeypatch.setattr(embedder, "embed", fake_embed_factory([]))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: {"a": "A\nB"})
    semantic._load()
    semantic.sync(driver=object())
    assert not (legacy / "emb.npy").exists() and vectorstore.get_store("library").count() == 1


def test_switching_the_model_rebuilds_in_the_background_and_search_falls_back_meanwhile(legacy, monkeypatch,
                                                                                         model_ready):
    texts = {f"p{i}": f"T{i}\nA{i}" for i in range(20)}
    calls: list = []
    monkeypatch.setattr(embedder, "embed", fake_embed_factory(calls))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: dict(texts))
    semantic._load()
    semantic.sync(driver=object())
    old_dim = 384
    model_ready["q"] = unit(np.random.default_rng(0), 1, old_dim)[0]
    assert len(semantic.query("x", k=5)) == 5

    monkeypatch.setenv("EMBED_MODEL", OTHER_MODEL)                   # 768 dims
    st = vectorstore.get_store("library")
    assert st.is_stale()
    assert semantic.query("x", k=5) == [] and semantic.status()["indexed"] == 0     # lexical fallback

    gate, started = threading.Event(), threading.Event()
    real = fake_embed_factory(calls)

    def slow(texts_, **kw):
        started.set()
        gate.wait(10)
        return real(texts_, **kw)

    monkeypatch.setattr(embedder, "embed", slow)
    worker = threading.Thread(target=lambda: semantic.sync(driver=object()))
    worker.start()
    assert started.wait(10)
    assert semantic.status()["state"] == "building" and semantic.status()["todo"] == 20
    assert semantic.query("x", k=5) == [] and st.is_stale() and st.manifest().dim == 384   # old data untouched
    gate.set()
    worker.join(30)
    assert not st.is_stale() and st.manifest().dim == 768 and st.manifest().model == OTHER_MODEL
    model_ready["q"] = unit(np.random.default_rng(0), 1, 768)[0]
    assert len(semantic.query("x", k=5)) == 5 and semantic.status()["indexed"] == 20
    assert json.loads((legacy / "meta.json").read_text())["model"] == OTHER_MODEL   # export follows the new model
    assert np.load(legacy / "emb.npy").shape == (20, 768)


# ── feed: candidate.emb and library_emb blobs ────────────────────────────────

def make_cand(n: int, published="2026-11-17T10:00:00Z") -> Candidate:
    return Candidate(id=f"arxiv:2611.{n:05d}", source="arxiv", ext_id=f"2611.{n:05d}", title=f"Paper {n}",
                     published=published, abstract=f"abstract {n}", categories=["cs.LG"])


def put_blob(st: FeedStore, cid: str, v: np.ndarray) -> None:
    """What the feed did before the vector store: the vector as a blob in the candidate row."""
    with st._lock:
        st._db.execute("UPDATE candidate SET emb = ? WHERE id = ?", (v.astype(np.float32).tobytes(), cid))
        st._db.commit()


@pytest.fixture
def feed(tmp_path, monkeypatch):
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.delenv("CONFERENCE_EMBED_MODEL", raising=False)
    st = FeedStore(tmp_path / "feed.sqlite")
    yield st
    st.close()


def test_feed_candidates_migrate_with_identical_scores_and_untouched_blobs(feed):
    rng = np.random.default_rng(7)
    cands = [make_cand(i, published=f"2026-11-{10 + i % 8:02d}T09:00:00Z") for i in range(60)]
    feed.upsert_candidates(cands)
    V = unit(rng, 60, 384)
    for c, v in zip(cands[:50], V):                                    # the last ten were never embedded
        put_blob(feed, c.id, v)
    with feed._lock:
        blobs_before = [bytes(r["emb"]) if r["emb"] else None for r in feed._db.execute(
            "SELECT emb FROM candidate ORDER BY id").fetchall()]
    assert feed.counts() == {"candidates": 60, "embedded": 50}
    assert migrate.marker_path("feed").exists()
    # the pool the digest scores and the scores themselves: identical to reading the blobs
    pool = feed.embedded_since("2026-11-12")
    want = {c.id: V[i] for i, c in enumerate(cands[:50]) if c.published[:10] >= "2026-11-12"}
    assert {c.id for c in pool} == set(want)
    assert [c.published for c in pool] == sorted((c.published for c in pool), reverse=True)
    q = unit(rng, 1, 384)[0]
    got = {c.id: float(c.emb @ q) for c in pool}
    assert got == {i: float(v @ q) for i, v in want.items()}
    assert {c.id for c in feed.without_embedding()} == {c.id for c in cands[50:]}
    np.testing.assert_array_equal(feed.get(cands[3].id).emb, V[3])
    sample = feed.sample_embeddings({cands[0].id}, 10)
    assert sample.shape == (10, 384)
    with feed._lock:
        assert [bytes(r["emb"]) if r["emb"] else None for r in feed._db.execute(
            "SELECT emb FROM candidate ORDER BY id").fetchall()] == blobs_before


def test_new_feed_vectors_go_to_the_store_not_the_column(feed):
    feed.upsert_candidates([make_cand(1), make_cand(2)])
    feed.set_embeddings({"arxiv:2611.00001": unit(np.random.default_rng(1), 1, 384)[0], "ghost": np.ones(384)})
    assert feed.counts()["embedded"] == 1 and feed.vectors().count() == 1
    assert feed.vectors().metadata(["arxiv:2611.00001"])["arxiv:2611.00001"] == {
        "kind": "candidate", "source": "arxiv", "published": "2026-11-17", "year": 2026,
        "added_at": to_timestamp(feed.get("arxiv:2611.00001").fetched_at)}
    with feed._lock:
        assert feed._db.execute("SELECT COUNT(emb) FROM candidate").fetchone()[0] == 0
    assert [c.id for c in feed.without_embedding()] == ["arxiv:2611.00002"]


def test_purging_candidates_drops_their_vectors(feed):
    feed.upsert_candidates([make_cand(1), make_cand(2)])
    feed.set_embeddings({c: unit(np.random.default_rng(i), 1, 384)[0]
                         for i, c in enumerate(["arxiv:2611.00001", "arxiv:2611.00002"])})
    feed.set_label("u", "arxiv:2611.00002", 1)
    with feed._lock:
        feed._db.execute("UPDATE candidate SET fetched_at = '2020-01-01T00:00:00+00:00'")
        feed._db.commit()
    assert feed.purge(30) == 1
    assert feed.vectors().ids() == ["arxiv:2611.00002"]               # the rated one stays


def test_library_cache_migrates_from_library_emb(feed):
    V = unit(np.random.default_rng(8), 3, 384)
    with feed._lock:
        for pid, h, v in zip(["p-b", "p-a", "p-c"], ["h1", "h2", "h3"], V):
            feed._db.execute("INSERT INTO library_emb (paper_id, hash, emb) VALUES (?,?,?)", (pid, h, v.tobytes()))
        feed._db.commit()
    assert feed.library_hashes() == {"p-b": "h1", "p-a": "h2", "p-c": "h3"}
    ids, mat = feed.library_embeddings()
    assert ids == ["p-a", "p-b", "p-c"]
    np.testing.assert_array_equal(mat[1], V[0])
    feed.set_library_embeddings({"p-a": ("h2b", V[2])})
    feed.delete_library_embeddings(["p-b"])
    assert feed.library_hashes() == {"p-a": "h2b", "p-c": "h3"}
    assert migrate.marker_path("feed_library").exists()


def test_feed_blobs_of_an_unknown_model_are_not_taken_over(feed, monkeypatch):
    feed.upsert_candidates([make_cand(1)])
    put_blob(feed, "arxiv:2611.00001", unit(np.random.default_rng(1), 1, 384)[0])
    monkeypatch.setenv("EMBED_MODEL", "example/other-encoder")
    monkeypatch.setenv("EMBED_DIM", "384")                             # same dimension: only the model name tells
    assert feed.counts()["embedded"] == 0 and not migrate.marker_path("feed").exists()
    assert [c.id for c in feed.without_embedding()] == ["arxiv:2611.00001"]


def test_switching_the_model_re_embeds_the_feed_into_a_new_generation(feed, monkeypatch):
    feed.upsert_candidates([make_cand(i) for i in range(10)])
    for i in range(10):
        put_blob(feed, make_cand(i).id, unit(np.random.default_rng(i), 1, 384)[0])
    assert feed.counts()["embedded"] == 10 and not feed.vectors_stale()
    monkeypatch.setenv("EMBED_MODEL", OTHER_MODEL)
    assert feed.vectors_stale() and feed.embedded_since("2000-01-01") == [] and feed.counts()["embedded"] == 0
    assert feed.sample_embeddings(set(), 5).shape == (0, 768) and feed.get_embeddings(["arxiv:2611.00001"]) == {}
    calls: list = []
    assert pipeline.embed_pending(feed, fake_embed_factory(calls)) == 10
    assert not feed.vectors_stale() and feed.counts()["embedded"] == 10
    assert {c.emb.shape for c in feed.embedded_since("2000-01-01")} == {(768,)}
    assert len(calls) == 1 and len(calls[0]) == 10
    assert pipeline.embed_pending(feed, fake_embed_factory([])) == 0


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, *a, **k):
        return self.rows


class _Driver:
    def __init__(self, rows):
        self.rows = rows

    def session(self):
        return _Rows(self.rows)


def test_the_library_cache_of_the_feed_is_rebuilt_after_a_model_switch(feed, monkeypatch):
    rows = [{"id": f"p{i}", "title": f"T{i}", "abstract": f"A{i}", "summary": None} for i in range(5)]
    monkeypatch.setattr(library, "semantic_snapshot", lambda: (["p0"], np.zeros((1, model_config.dim()), np.float32)))
    n = library.sync_missing_embeddings(_Driver(rows), feed, fake_embed_factory([]))
    assert n == 4 and sorted(feed.library_hashes()) == ["p1", "p2", "p3", "p4"]
    monkeypatch.setenv("EMBED_MODEL", OTHER_MODEL)
    assert feed.library_vectors_stale()
    monkeypatch.setattr(library, "semantic_snapshot", lambda: ([], np.zeros((0, 768), np.float32)))
    assert library.sync_missing_embeddings(_Driver(rows), feed, fake_embed_factory([])) == 5
    ids, mat = feed.library_embeddings()
    assert ids == ["p0", "p1", "p2", "p3", "p4"] and mat.shape == (5, 768) and not feed.library_vectors_stale()
