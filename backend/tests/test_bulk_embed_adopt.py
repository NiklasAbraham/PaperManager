"""Adoption of a prepared generation on start, the kept generation as rollback target, and the fallback to the
rebuild that embeds everything. Synthetic vectors; the embedder is replaced by a recording fake."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from services import vectorstore
from services.conferences import embedder
from services.feed.store import Candidate, FeedStore
from services.library_search import semantic
from services.vectorstore import ModelSpec, base, model_config, registry
from tests.bulk_embed_helpers import load_script
from tests.vectorstore_helpers import unit

rollback_script = load_script("vectors_rollback")

A = ModelSpec("test/model-a", 24)
B = ModelSpec("test/model-b", 16, "mean")


def fill(ns: str, spec: ModelSpec, ids, seed=1, prepare=False, hashes=None):
    """A store of ``spec`` holding ``ids`` (live, via the writer; or prepared next to the live one)."""
    st = registry._make(registry.vector_dir(), ns, prepare, spec)
    V = unit(np.random.default_rng(seed), len(ids), spec.dim)
    metas = [{"kind": "paper", "source": "library", "hash": (hashes or {}).get(i, f"h-{i}")} for i in ids]
    if prepare:
        with st.begin_prepare(spec) as pr:
            pr.upsert(ids, V, metas)
            pr.commit()
    else:
        st.upsert(ids, V, metas)
    return st, V


def open_for(ns: str, spec: ModelSpec):
    """A fresh store object as a restarted backend has it, expecting ``spec`` (a new process: the old closed)."""
    return registry._make(registry.vector_dir(), ns, False, spec)


def dirs(ns: str):
    return sorted(p.name for p in (registry.vector_dir() / ns).iterdir() if p.is_dir())


# ── the store ─────────────────────────────────────────────────────────────────────────────────────

def test_a_prepared_generation_is_adopted_instead_of_rebuilding(monkeypatch):
    ids = [f"p{i}" for i in range(25)]
    live, VA = fill("lib", A, ids[:20])
    _, VB = fill("lib", B, ids, prepare=True, seed=2)
    live.close()
    st = open_for("lib", B)                           # the backend restarted with the other model configured
    assert st.is_stale() and st.state() == "stale"
    assert st.adopt_matching() == "prepared"
    assert not st.is_stale() and st.state() == "ready"
    assert (st.manifest().model, st.manifest().dim, st.count()) == ("test/model-b", 16, 25)
    assert st.manifest().generation == "g000002" and (st.dir / "CURRENT").read_text().strip() == "g000002"
    hit = st.search(VB[7], 1)[0]
    assert hit.id == "p7" and hit.score == pytest.approx(1.0, abs=1e-5) and hit.metadata["hash"] == "h-p7"
    assert st.prepared() == [] and [m.model for m in st.retained()] == ["test/model-a"]
    assert dirs("lib") == ["g000001", "g000002"]                 # the old files are still there
    assert st.adopt_matching() is None                # idempotent: nothing left to adopt, live is fine
    st.close()


def test_a_reader_of_the_old_model_is_refused_after_the_swap_never_mixed(monkeypatch):
    live, VA = fill("lib", A, [f"p{i}" for i in range(10)])
    fill("lib", B, [f"p{i}" for i in range(10)], prepare=True, seed=2)
    follower = registry._make(registry.vector_dir(), "lib", True, A)           # e.g. the MCP server
    assert follower.search(VA[3], 1)[0].id == "p3"
    live.close()
    st = open_for("lib", B)
    assert st.adopt_matching() == "prepared"
    follower._last_follow = 0.0
    with pytest.raises(vectorstore.StaleStoreError):  # it expects A, the namespace now holds B: refused, never mixed
        follower.search(VA[3], 1)
    follower2 = registry._make(registry.vector_dir(), "lib", True, B)
    assert follower2.manifest().model == "test/model-b" and follower2.count() == 10
    for s in (follower, follower2, st):
        s.close()


def test_a_following_reader_sees_the_adopted_generation(monkeypatch):
    live, VA = fill("lib", A, [f"p{i}" for i in range(6)])
    _, VB = fill("lib", B, [f"p{i}" for i in range(6)], prepare=True, seed=2)
    follower = registry._make(registry.vector_dir(), "lib", True, B)            # the MCP server, configured with B
    assert follower.is_stale()
    live.close()
    st = open_for("lib", B)
    assert st.adopt_matching() == "prepared"
    follower._last_follow = 0.0
    assert not follower.is_stale() and follower.search(VB[4], 1)[0].id == "p4"
    follower.close()
    st.close()


def test_the_keep_setting_is_read_leniently(monkeypatch):
    for raw, want in (("", 2), ("3", 3), ("1", 1), ("0", 1), ("-4", 1), ("many", 2), (" 5 ", 5)):
        monkeypatch.setenv("VECTOR_STORE_KEEP_GENERATIONS", raw)
        assert base.keep_generations() == want
    monkeypatch.delenv("VECTOR_STORE_KEEP_GENERATIONS")
    assert base.keep_generations() == 2


def test_a_prepared_generation_survives_the_writer_start_gc_and_a_crashed_one_is_collected(monkeypatch):
    live, _ = fill("lib", A, ["a", "b"])
    fill("lib", B, ["a"], prepare=True)
    crashed = live.dir / "p000009"
    crashed.mkdir()
    (crashed / "vectors.f32").write_bytes(b"x")
    import os, time
    old = time.time() - 3 * 24 * 3600
    os.utime(crashed, (old, old))
    live.begin_prepare(B).abort()                      # the next preparation clears long-dead leftovers
    live._gc()
    assert not crashed.exists() and [m.model for m in live.prepared()] == ["test/model-b"]
    live.close()


def test_without_a_prepared_generation_nothing_is_adopted():
    live, _ = fill("lib", A, ["a", "b"])
    live.close()
    st = open_for("lib", B)
    assert st.adopt_matching() is None and st.is_stale()
    assert st.begin_rebuild(B) is not None            # the rebuild path of before is untouched
    st.close()


def test_a_prepared_generation_of_another_model_is_ignored():
    live, _ = fill("lib", A, ["a", "b"])
    fill("lib", ModelSpec("test/model-c", 16), ["a"], prepare=True)
    live.close()
    st = open_for("lib", B)
    assert st.adopt_matching() is None
    st.close()


def test_a_healthy_live_generation_is_not_replaced():
    live, _ = fill("lib", B, ["live1", "live2"])
    fill("lib", B, ["x1", "x2", "x3"], prepare=True, seed=4)
    assert live.adopt_matching() is None and live.count() == 2 and len(live.prepared()) == 1
    live.close()


def test_an_empty_live_generation_of_the_new_model_is_replaced():
    """A fresh namespace the backend initialised for the configured model before the import existed."""
    fill("feed", B, ["x1", "x2", "x3"], prepare=True)
    st = registry.get_store("feed", spec=B)           # creates an empty live generation for B
    assert st.count() == 0
    assert st.adopt_matching(B) == "prepared" and st.count() == 3
    assert st.retained() == []                        # an empty generation of the same space is not worth keeping
    st.close()


def test_follow_mode_never_adopts():
    live, _ = fill("lib", A, ["a"])
    fill("lib", B, ["a"], prepare=True)
    follower = registry._make(registry.vector_dir(), "lib", True, B)
    assert follower.adopt_matching() is None and follower.is_stale()
    follower.close()
    live.close()


def test_a_second_process_holding_the_writer_lock_defers_adoption():
    live, _ = fill("lib", A, ["a"])
    fill("lib", B, ["a"], prepare=True)
    other = registry._make(registry.vector_dir(), "lib", False, B)
    assert other.adopt_matching() is None             # the lock is held by `live`: logged, not raised
    live.close()
    assert other.adopt_matching() == "prepared"
    other.close()


# ── kept generations, rollback ────────────────────────────────────────────────────────────────────

def switch(ns, spec_from, spec_to, ids, seed):
    """Live generation of spec_from -> adopted prepared generation of spec_to."""
    fill(ns, spec_to, ids, seed=seed, prepare=True)
    registry._make(registry.vector_dir(), ns, False, spec_from).close()
    st = open_for(ns, spec_to)
    assert st.adopt_matching() == "prepared"
    return st


def test_rollback_swaps_back_and_can_be_undone():
    ids = [f"p{i}" for i in range(12)]
    live, VA = fill("lib", A, ids)
    live.close()
    st = switch("lib", A, B, ids, 2)
    st.close()
    st = open_for("lib", B)
    assert st.manifest().model == "test/model-b"
    m = st.rollback()
    assert m.model == "test/model-a" and st.manifest().dim == 24 and st.count() == 12
    assert st.is_stale()                                                 # until EMBED_MODEL is set back
    assert [x.model for x in st.retained()] == ["test/model-b"]         # the switched generation is kept in turn
    st.close()
    back = open_for("lib", A)                                            # the backend restarted with the old model
    assert not back.is_stale() and back.search(VA[5], 1)[0].id == "p5"
    back.close()
    st = open_for("lib", B)
    assert st.rollback().model == "test/model-b"                        # and the rollback can be undone
    st.close()


def test_rollback_with_nothing_kept_does_nothing():
    live, _ = fill("lib", A, ["a"])
    assert live.rollback() is None and live.manifest().model == "test/model-a"
    live.close()


def test_the_old_model_set_again_adopts_the_kept_generation_instead_of_rebuilding():
    ids = [f"p{i}" for i in range(12)]
    live, VA = fill("lib", A, ids)
    live.close()
    switch("lib", A, B, ids, 2).close()
    st = open_for("lib", A)                          # EMBED_MODEL set back, no script run
    assert st.is_stale() and st.adopt_matching() == "retained"
    assert st.manifest().model == "test/model-a" and st.search(VA[2], 1)[0].id == "p2"
    assert [m.model for m in st.retained()] == ["test/model-b"]
    st.close()


def test_by_default_one_generation_is_kept_and_keep_one_keeps_none(monkeypatch):
    monkeypatch.setattr(base, "RETIRE_GRACE_SECONDS", 0.0)
    assert base.keep_generations() == 2
    ids = ["a", "b", "c"]
    live, _ = fill("lib", A, ids)
    live.close()
    st = switch("lib", A, B, ids, 2)
    assert [m.model for m in st.retained()] == ["test/model-a"]
    st.close()
    monkeypatch.setenv("VECTOR_STORE_KEEP_GENERATIONS", "1")
    registry.reset()
    st = open_for("lib", B)
    st._acquire_writer()
    st._gc()
    assert st.retained() == [] and st.rollback() is None
    st.close()


def test_keep_three_holds_two_older_generations(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_KEEP_GENERATIONS", "3")
    monkeypatch.setattr(base, "RETIRE_GRACE_SECONDS", 0.0)
    C = ModelSpec("test/model-c", 8)
    ids = ["a", "b"]
    fill("lib", A, ids)[0].close()
    switch("lib", A, B, ids, 2).close()
    st = switch("lib", B, C, ids, 3)
    assert {m.model for m in st.retained()} == {"test/model-a", "test/model-b"}
    st.close()
    monkeypatch.setenv("VECTOR_STORE_KEEP_GENERATIONS", "2")
    fill("lib", A, ids, prepare=True, seed=5)
    st = open_for("lib", A)
    assert st.adopt_matching() == "prepared"        # a switch back to A: C is kept, B (the oldest) is dropped
    assert [m.model for m in st.retained()] == ["test/model-c"]
    st.close()


def test_a_cpu_rebuild_for_another_model_keeps_the_old_generation_too():
    live, _ = fill("lib", A, ["a", "b"])
    live.close()
    st = open_for("lib", B)
    with st.begin_rebuild(B) as rb:
        rb.upsert(["a"], unit(np.random.default_rng(0), 1, 16))
        rb.commit()
    assert st.manifest().model == "test/model-b" and [m.model for m in st.retained()] == ["test/model-a"]
    st.close()


def test_compaction_within_one_model_keeps_nothing():
    st, _ = fill("lib", A, [f"p{i}" for i in range(5)])
    st.compact()
    assert st.retained() == []
    st.close()


def test_the_rollback_script_prints_the_environment_to_set(capsys):
    ids = ["a", "b"]
    fill("lib", A, ids)[0].close()
    switch("lib", A, B, ids, 2).close()
    root = registry.vector_dir()
    rollback_script.status(["lib"], root)
    out = capsys.readouterr().out
    assert "live:" in out and "test/model-b" in out and "kept:" in out and "test/model-a" in out
    done = rollback_script.rollback(["lib"], root, log=lambda *_: None)
    assert done["lib"].model == "test/model-a"
    assert rollback_script.env_lines(done["lib"]) == ["EMBED_MODEL=test/model-a", "EMBED_DIM=24", "EMBED_POOLING=cls",
                                                      "EMBED_QUERY_PREFIX=", "EMBED_DOC_PREFIX="]


def test_the_rollback_script_needs_the_backend_stopped():
    live, _ = fill("lib", A, ["a"])
    fill("lib", B, ["a"], prepare=True)
    with pytest.raises(SystemExit, match="locked"):
        rollback_script.rollback(["lib"], registry.vector_dir(), log=lambda *_: None)
    live.close()


# ── the library search on start ───────────────────────────────────────────────────────────────────

def _text_hash(t):
    return semantic.text_hash(t)


@pytest.fixture
def lib_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARY_SEARCH_DIR", str(tmp_path / "legacy"))
    monkeypatch.setattr(semantic, "_dir", None)
    monkeypatch.setattr(semantic, "_follow_store", None)
    monkeypatch.setattr(semantic, "_adopted", False)
    for var in ("EMBED_MODEL", "CONFERENCE_EMBED_MODEL", "EMBED_DIM", "EMBED_POOLING", "EMBED_DOC_PREFIX",
                "EMBED_QUERY_PREFIX"):
        monkeypatch.delenv(var, raising=False)


TARGET = "BAAI/bge-base-en-v1.5"            # 768 dims, a known model


def fake_embed(calls):
    def embed(texts, **kw):
        calls.append(list(texts))
        out = np.stack([np.random.default_rng(int(hashlib.sha1(t.encode()).hexdigest()[:8], 16)).normal(size=768)
                        for t in texts]) if texts else np.zeros((0, 768))
        return (out / np.linalg.norm(out, axis=1, keepdims=True)).astype(np.float32) if len(texts) else out.astype(np.float32)
    return embed


def prepare_library(texts: dict[str, str], spec: ModelSpec):
    st = registry._make(registry.vector_dir(), "library", True, spec)
    ids = list(texts)
    with st.begin_prepare(spec) as pr:
        pr.upsert(ids, unit(np.random.default_rng(8), len(ids), spec.dim),
                  [{"kind": "paper", "source": "library", "hash": _text_hash(texts[i])} for i in ids])
        pr.commit()
    st.close()


def old_library(texts: dict[str, str]):
    st = registry._make(registry.vector_dir(), "library", False, model_config.current())
    ids = list(texts)
    st.upsert(ids, unit(np.random.default_rng(2), len(ids), 384),
              [{"kind": "paper", "source": "library", "hash": _text_hash(texts[i])} for i in ids])
    st.close()


def test_the_backend_starts_on_the_prepared_generation_and_embeds_only_the_difference(lib_env, monkeypatch):
    texts = {f"p{i}": f"Title {i}\nAbstract {i}" for i in range(40)}
    old_library(texts)
    prepare_library(texts, ModelSpec(TARGET, 768, "cls", model_config.KNOWN[TARGET][2], ""))
    monkeypatch.setenv("EMBED_MODEL", TARGET)
    # papers added and changed since the export
    texts["p100"] = "Title 100\nAbstract 100"
    texts["p5"] = "Title 5\nA revised abstract"
    del texts["p6"]
    calls = []
    monkeypatch.setattr(embedder, "embed", fake_embed(calls))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: dict(texts))
    rebuilds = []
    real = base.GenerationalStore.begin_rebuild
    monkeypatch.setattr(base.GenerationalStore, "begin_rebuild",
                        lambda self, *a, **k: rebuilds.append(1) or real(self, *a, **k))
    semantic._load()
    st = vectorstore.get_store("library")
    assert not st.is_stale() and st.manifest().model == TARGET and st.count() == 40      # adopted at load
    out = semantic.sync(driver=object())
    assert out["embedded"] == 2 and out["removed"] == 2                  # p100 new, p5 changed; p5 and p6 removed/replaced
    assert sorted(t for c in calls for t in c) == sorted([texts["p100"], texts["p5"]])
    assert rebuilds == [] and set(st.ids()) == set(texts) and st.count() == 40
    assert semantic.status()["indexed"] == 40
    # the legacy files (topic map) follow the adopted generation, though the delta was tiny
    meta = json.loads((semantic.data_dir() / "meta.json").read_text())
    assert meta["model"] == TARGET and meta["dim"] == 768 and len(meta["ids"]) == 40
    assert [m.model for m in st.retained()] == [model_config.DEFAULT_MODEL]      # the rollback target


def test_adoption_does_not_even_load_the_model_when_nothing_changed(lib_env, monkeypatch):
    texts = {f"p{i}": f"Title {i}\nAbstract {i}" for i in range(15)}
    old_library(texts)
    prepare_library(texts, ModelSpec(TARGET, 768, "cls", model_config.KNOWN[TARGET][2], ""))
    monkeypatch.setenv("EMBED_MODEL", TARGET)
    monkeypatch.setattr(embedder, "embed", lambda *a, **k: pytest.fail("nothing should be embedded"))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: dict(texts))
    semantic._load()
    assert semantic.sync(driver=object())["embedded"] == 0
    assert vectorstore.get_store("library").count() == 15


def test_without_a_prepared_generation_the_old_rebuild_runs(lib_env, monkeypatch):
    texts = {f"p{i}": f"Title {i}\nAbstract {i}" for i in range(12)}
    old_library(texts)
    monkeypatch.setenv("EMBED_MODEL", TARGET)
    calls = []
    monkeypatch.setattr(embedder, "embed", fake_embed(calls))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: dict(texts))
    semantic._load()
    assert vectorstore.get_store("library").is_stale()               # nothing to adopt: stale until the rebuild is done
    assert semantic.sync(driver=object())["embedded"] == 12          # everything, on the CPU, as before
    st = vectorstore.get_store("library")
    assert not st.is_stale() and st.manifest().model == TARGET and sum(len(c) for c in calls) == 12


def test_a_broken_adoption_falls_back_to_the_rebuild(lib_env, monkeypatch, caplog):
    texts = {f"p{i}": f"Title {i}\nAbstract {i}" for i in range(6)}
    old_library(texts)
    prepare_library(texts, ModelSpec(TARGET, 768, "cls", model_config.KNOWN[TARGET][2], ""))
    monkeypatch.setenv("EMBED_MODEL", TARGET)
    monkeypatch.setattr(base.GenerationalStore, "adopt_matching",
                        lambda self, spec=None: (_ for _ in ()).throw(OSError("disk trouble")))
    calls = []
    monkeypatch.setattr(embedder, "embed", fake_embed(calls))
    monkeypatch.setattr(semantic, "_fetch_texts", lambda driver: dict(texts))
    semantic._load()
    assert semantic.sync(driver=object())["embedded"] == 6
    assert not vectorstore.get_store("library").is_stale()


# ── the feed ──────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def feed(tmp_path):
    st = FeedStore(tmp_path / "feed.sqlite")
    yield st
    st.close()


def cand(i):
    return Candidate(f"c{i}", "arxiv", f"2501.{i:05d}", f"Candidate {i}", "2026-01-02", abstract=f"abstract {i}",
                     fetched_at="2026-01-03T00:00:00+00:00")


def test_the_feed_adopts_prepared_vectors_and_embeds_only_new_candidates(feed, monkeypatch):
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    feed.upsert_candidates([cand(i) for i in range(10)])
    spec = ModelSpec(TARGET, 768, "cls", model_config.KNOWN[TARGET][2], "")
    # the old candidate vectors (default model) and a prepared generation made for the target model;
    # c99 was purged from the database after the export
    st = registry._make(registry.vector_dir(), "feed", False, model_config.current())
    st.upsert(["c0", "c1"], unit(np.random.default_rng(1), 2, 384), [{"kind": "candidate"}] * 2)
    st.close()
    prep = registry._make(registry.vector_dir(), "feed", True, spec)
    with prep.begin_prepare(spec) as pr:
        ids = [f"c{i}" for i in range(8)] + ["c99"]
        pr.upsert(ids, unit(np.random.default_rng(2), len(ids), 768), [{"kind": "candidate", "source": "arxiv"}] * 9)
        pr.commit()
    prep.close()
    registry.reset()
    monkeypatch.setenv("EMBED_MODEL", TARGET)
    assert not feed.vectors_stale()
    assert {c.id for c in feed.without_embedding()} == {"c8", "c9"}
    assert "c99" not in set(feed.vectors().ids()) and feed.vectors().count() == 8
    from services.feed import pipeline

    calls = []
    assert pipeline.embed_pending(feed, fake_embed(calls)) == 2
    assert sorted(t for c in calls for t in c) == ["Candidate 8\nabstract 8", "Candidate 9\nabstract 9"]


def test_the_feed_without_a_prepared_generation_rebuilds_as_before(feed, monkeypatch):
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    feed.upsert_candidates([cand(i) for i in range(4)])
    st = registry._make(registry.vector_dir(), "feed", False, model_config.current())
    st.upsert(["c0"], unit(np.random.default_rng(1), 1, 384), [{"kind": "candidate"}])
    st.close()
    registry.reset()
    monkeypatch.setenv("EMBED_MODEL", TARGET)
    assert feed.vectors_stale()
    from services.feed import pipeline

    calls = []
    assert pipeline.embed_pending(feed, fake_embed(calls)) == 4
    assert not feed.vectors_stale() and feed.vectors().manifest().model == TARGET
