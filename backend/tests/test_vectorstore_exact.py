"""Exact backend specifics: crash safety, damaged files, compaction, threads, the writer lock,
read-only following and the generation directory layout."""
from __future__ import annotations

import os
import threading
import time

import numpy as np
import pytest

from services.vectorstore import StoreLockedError, VectorStoreError, base
from tests.vectorstore_helpers import DIM, make_meta, make_store, reference, unit


def _gen_dir(tmp_path):
    cur = (tmp_path / "ns" / "CURRENT").read_text().strip()
    return tmp_path / "ns" / cur


def test_layout_is_a_generation_directory_with_a_manifest(tmp_path):
    st = make_store(tmp_path, "exact")
    st.upsert(["a"], unit(np.random.default_rng(0), 1))
    gen = _gen_dir(tmp_path)
    assert (gen / "vectors.f32").exists() and (gen / "meta.sqlite").exists() and (gen / "manifest.json").exists()
    assert (tmp_path / "ns" / "LOCK").exists()


def test_a_crash_between_vectors_and_commit_leaves_no_trace(tmp_path):
    """Vectors are written before the SQLite commit. Simulate the crash by failing the commit:
    the new rows must not be visible, and the next write reuses them."""
    rng = np.random.default_rng(1)
    V = unit(rng, 10)
    st = make_store(tmp_path, "exact")
    st.upsert([f"i{i}" for i in range(5)], V[:5])
    gen = st._gen

    class Boom(Exception):
        pass

    real = gen._db

    class Failing:
        def __init__(self, db):
            self._db = db

        def execute(self, sql, *a):
            if sql.strip().upper().startswith("COMMIT"):
                raise Boom("disk gone")
            return self._db.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._db, name)

    gen._db = Failing(real)
    with pytest.raises(Boom):
        st.upsert(["x", "y"], V[5:7])
    real.execute("ROLLBACK") if real.in_transaction else None
    gen._db = real
    assert st.count() == 5 and st.get(["x", "y"]) == {}
    assert "x" not in {h.id for h in st.search(V[5], 10)}
    st.upsert(["z"], V[7:8])
    assert st.count() == 6 and st.search(V[7], 1)[0].id == "z"
    st.close()
    again = make_store(tmp_path, "exact")
    assert again.count() == 6 and again.search(V[7], 1)[0].id == "z"


def test_garbage_rows_after_the_last_committed_one_are_ignored_and_overwritten(tmp_path):
    rng = np.random.default_rng(2)
    V = unit(rng, 6)
    st = make_store(tmp_path, "exact")
    st.upsert(["a", "b", "c"], V[:3])
    path = _gen_dir(tmp_path) / "vectors.f32"
    st.close()
    with open(path, "r+b") as f:               # what a crash after the vector write leaves behind
        f.seek(3 * DIM * 4)
        f.write(V[5].tobytes() * 2)
    again = make_store(tmp_path, "exact")
    assert again.count() == 3 and again.search(V[5], 1)[0].id != "garbage"
    again.upsert(["d"], V[3:4])
    assert again.search(V[3], 1)[0].id == "d" and again.count() == 4


def test_truncated_vector_file_reads_as_empty_and_can_be_rebuilt(tmp_path):
    V = unit(np.random.default_rng(3), 30)
    st = make_store(tmp_path, "exact")
    st.upsert([str(i) for i in range(30)], V)
    path = _gen_dir(tmp_path) / "vectors.f32"
    st.close()
    os.truncate(path, 5 * DIM * 4)
    again = make_store(tmp_path, "exact")
    assert again.count() == 0 and again.state() == "missing"
    again.upsert(["fresh"], V[:1])                      # a writer starts a clean generation
    assert again.count() == 1 and again.search(V[0], 1)[0].id == "fresh"
    assert _gen_dir(tmp_path).name == "g000002"


def test_missing_data_files_read_as_empty(tmp_path):
    st = make_store(tmp_path, "exact")
    st.upsert(["a"], unit(np.random.default_rng(0), 1))
    gen = _gen_dir(tmp_path)
    st.close()
    (gen / "meta.sqlite").unlink()
    assert make_store(tmp_path, "exact").count() == 0


def test_dead_rows_trigger_compaction_without_losing_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "COMPACT_MIN_DEAD", 50)
    rng = np.random.default_rng(4)
    V = unit(rng, 100)
    ids, metas = make_meta(rng, 100)
    st = make_store(tmp_path, "exact")
    st.upsert(ids, V, metas)
    first = _gen_dir(tmp_path).name
    st.delete(ids[:70])                                 # 70 dead > 50 and > half of 30 live
    assert _gen_dir(tmp_path).name != first
    assert st.count() == 30 and st._gen.dead() == 0
    for q in unit(rng, 5):
        got = st.search(q, 5)
        want = reference(V[70:], ids[70:], q, 5)
        assert [h.id for h in got] == [i for i, _ in want]
    assert st.get(["id80"])["id80"][1] == metas[80]


def test_growth_past_the_initial_capacity_keeps_every_row(tmp_path):
    rng = np.random.default_rng(5)
    V = unit(rng, 2500)
    st = make_store(tmp_path, "exact")
    for s in range(0, 2500, 700):
        st.upsert([f"i{i}" for i in range(s, min(s + 700, 2500))], V[s:s + 700])
    assert st.count() == 2500
    for i in (0, 1023, 1024, 2499):
        assert st.search(V[i], 1)[0].id == f"i{i}"
    st.close()
    assert make_store(tmp_path, "exact").search(V[2000], 1)[0].id == "i2000"


def test_concurrent_writers_and_readers_stay_consistent(tmp_path):
    rng = np.random.default_rng(6)
    V = unit(rng, 400)
    st = make_store(tmp_path, "exact")
    st.upsert([f"base{i}" for i in range(100)], V[:100])
    errors, stop = [], threading.Event()

    def reader():
        try:
            while not stop.is_set():
                q = V[int(np.random.randint(0, 100))]
                hits = st.search(q, 5)
                assert hits and all(np.isfinite(h.score) for h in hits)
                assert hits[0].score >= hits[-1].score
                st.get(["base1", "base2"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def writer(k):
        try:
            for j in range(10):
                n = 100 + k * 100 + j * 10
                st.upsert([f"w{k}_{n + i}" for i in range(10)], V[n:n + 10])
                st.delete([f"w{k}_{n}"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    writers = [threading.Thread(target=writer, args=(k,)) for k in range(3)]
    [t.start() for t in readers + writers]
    [t.join() for t in writers]
    stop.set()
    [t.join() for t in readers]
    assert not errors, errors[:1]
    assert st.count() == 100 + 3 * 10 * 9


def test_second_writer_process_is_refused_and_a_follower_reads(tmp_path):
    rng = np.random.default_rng(7)
    V = unit(rng, 20)
    writer = make_store(tmp_path, "exact")
    writer.upsert(["a", "b"], V[:2])
    other = make_store(tmp_path, "exact")               # same process, own file descriptor: flock refuses it too
    with pytest.raises(StoreLockedError):
        other.upsert(["c"], V[2:3])
    follower = make_store(tmp_path, "exact", follow=True)
    assert follower.count() == 2 and follower.search(V[1], 1)[0].id == "b"
    with pytest.raises(VectorStoreError):
        follower.upsert(["c"], V[2:3])
    follower._last_follow = 0
    writer.upsert(["c"], V[2:3])
    follower._last_follow = 0                           # do not wait for the poll interval
    assert follower.count() == 3 and follower.search(V[2], 1)[0].id == "c"
    writer.close()
    other.upsert(["d"], V[3:4])                         # the lock is free once the writer is closed
    assert other.count() == 4


def test_the_follower_picks_up_a_swapped_generation(tmp_path):
    rng = np.random.default_rng(8)
    V = unit(rng, 10)
    writer = make_store(tmp_path, "exact")
    writer.upsert(["old"], V[:1])
    follower = make_store(tmp_path, "exact", follow=True)
    assert follower.ids() == ["old"]
    rb = writer.begin_rebuild()
    rb.upsert(["new1", "new2"], V[1:3])
    rb.commit()
    follower._last_follow = 0
    assert sorted(follower.ids()) == ["new1", "new2"]


def test_search_over_a_few_thousand_rows_with_a_selective_filter_uses_the_sparse_path(tmp_path):
    rng = np.random.default_rng(10)
    V = unit(rng, 3000)
    ids, metas = make_meta(rng, 3000)
    st = make_store(tmp_path, "exact")
    st.upsert(ids, V, metas)
    flt = {"kind": "book", "source": "biorxiv", "year": 2026}
    keep = np.array([m["kind"] == "book" and m["source"] == "biorxiv" and m["year"] == 2026 for m in metas])
    assert 0 < keep.sum() < 1500
    q = unit(rng, 1)[0]
    assert [h.id for h in st.search(q, 7, flt)] == [i for i, _ in reference(V, ids, q, 7, keep)]


def test_namespace_names_are_restricted(tmp_path):
    for bad in ("", "../x", "a b", "UPPER", "a/b"):
        with pytest.raises(ValueError):
            make_store(tmp_path, "exact", namespace=bad)


def test_search_time_is_not_blocked_by_a_long_write(tmp_path):
    rng = np.random.default_rng(12)
    V = unit(rng, 5000)
    st = make_store(tmp_path, "exact")
    st.upsert([str(i) for i in range(2000)], V[:2000])
    done = threading.Event()

    def write():
        for s in range(2000, 5000, 500):
            st.upsert([str(i) for i in range(s, s + 500)], V[s:s + 500])
        done.set()

    t = threading.Thread(target=write)
    t.start()
    worst = 0.0
    while not done.is_set():
        t0 = time.perf_counter()
        st.search(V[0], 5)
        worst = max(worst, time.perf_counter() - t0)
    t.join()
    assert worst < 2.0
