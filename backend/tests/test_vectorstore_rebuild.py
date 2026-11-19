"""Staleness, rebuilds and the atomic swap: no mixed spaces, readers keep working during a build."""
from __future__ import annotations

import threading

import numpy as np
import pytest

from services.vectorstore import StaleStoreError, base
from tests.vectorstore_helpers import DIM, LANCE_AVAILABLE, LANCE_SKIP, make_meta, make_store, spec, unit

BACKENDS = ["exact", pytest.param("lance", marks=pytest.mark.skipif(not LANCE_AVAILABLE, reason=LANCE_SKIP))]


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param


def _built(tmp_path, backend, model="test/model-a", n=50, dim=DIM, seed=0):
    rng = np.random.default_rng(seed)
    V = unit(rng, n, dim)
    st = make_store(tmp_path, backend, spec=spec(dim, model))
    st.upsert([f"id{i}" for i in range(n)], V)
    st.close()
    return V


def test_a_store_built_with_another_model_is_stale_and_refuses_to_mix(tmp_path, backend):
    V = _built(tmp_path, backend, "test/model-a")
    st = make_store(tmp_path, backend, spec=spec(DIM, "test/model-b"))      # same dimension, other model
    assert st.is_stale() and st.state() == "stale" and st.count() == 50
    with pytest.raises(StaleStoreError):
        st.search(V[0], 3)
    with pytest.raises(StaleStoreError):
        st.upsert(["x"], V[:1])
    with pytest.raises(StaleStoreError):
        st.get(["id1"])
    with pytest.raises(StaleStoreError):
        st.all_vectors()
    assert st.ids() and st.metadata()                                       # bookkeeping stays readable
    assert make_store(tmp_path, backend, spec=spec(DIM, "test/model-a")).state() == "ready"


@pytest.mark.parametrize("change", [
    {"dim": 12}, {"pooling": "mean"}, {"doc_prefix": "passage: "}, {"text_format": "title-abstract-2"}])
def test_every_part_of_the_space_key_makes_it_stale(tmp_path, backend, change):
    _built(tmp_path, backend)
    other = spec(**{"dim": DIM, **change})
    assert make_store(tmp_path, backend, spec=other).is_stale()


def test_the_query_prefix_does_not_make_it_stale(tmp_path, backend):
    _built(tmp_path, backend)
    assert not make_store(tmp_path, backend, spec=spec(DIM, "test/model-a", query_prefix="q: ")).is_stale()


def test_rebuild_for_a_new_model_swaps_in_atomically(tmp_path, backend):
    old = _built(tmp_path, backend, "test/model-a", dim=DIM)
    st = make_store(tmp_path, backend, spec=spec(16, "test/model-b"))
    assert st.is_stale()
    new = unit(np.random.default_rng(1), 30, 16)
    rb = st.begin_rebuild()
    rb.upsert([f"n{i}" for i in range(30)], new)
    assert st.is_stale() and st.count() == 50                               # nothing visible before commit
    rb.commit()
    assert not st.is_stale() and st.count() == 30
    m = st.manifest()
    assert (m.model, m.dim, m.count) == ("test/model-b", 16, 30) and m.generation == "g000002"
    assert st.search(new[4], 1)[0].id == "n4"
    assert st.get(["id1"]) == {}                                            # the old vectors are gone
    st.upsert(["n_extra"], unit(np.random.default_rng(2), 1, 16))           # writable again
    st.close()
    reopened = make_store(tmp_path, backend, spec=spec(16, "test/model-b"))
    assert reopened.state() == "ready" and reopened.count() == 31


def test_an_aborted_rebuild_leaves_the_old_generation_alone(tmp_path, backend):
    V = _built(tmp_path, backend, "test/model-a")
    st = make_store(tmp_path, backend, spec=spec(DIM, "test/model-a"))
    with st.begin_rebuild(spec(8, "test/model-b")) as rb:
        rb.upsert(["z"], unit(np.random.default_rng(3), 1, 8))
    assert st.count() == 50 and st.manifest().model == "test/model-a" and not st.is_stale()
    assert st.search(V[5], 1)[0].id == "id5"
    with pytest.raises(RuntimeError):
        with st.begin_rebuild(spec(DIM, "test/model-a")) as rb:
            rb.upsert(["z"], V[:1])
            raise RuntimeError("embedding failed halfway")
    assert st.count() == 50 and st._read_current() == "g000001"
    st.upsert(["after"], V[:1])                                             # the store still works
    assert st.count() == 51


def test_a_rebuild_cannot_be_used_after_it_finished(tmp_path, backend):
    _built(tmp_path, backend)
    st = make_store(tmp_path, backend)
    rb = st.begin_rebuild()
    rb.commit()
    for call in (rb.commit, lambda: rb.upsert(["a"], unit(np.random.default_rng(0), 1))):
        with pytest.raises(Exception):
            call()
    rb.abort()                                                              # harmless after commit
    assert st.manifest().generation == "g000002"


def test_readers_never_see_two_generations_mixed_during_swaps(tmp_path):
    """Hammer search() while a rebuild is committed over and over: every result comes wholly from
    one generation (its ids carry the generation's prefix), and no search fails."""
    rng = np.random.default_rng(4)
    V = unit(rng, 60)
    st = make_store(tmp_path, "exact")
    st.upsert([f"g0_{i}" for i in range(60)], V)
    errors, seen, stop = [], set(), threading.Event()

    def reader():
        try:
            while not stop.is_set():
                hits = st.search(V[int(np.random.randint(0, 60))], 8)
                assert len(hits) == 8
                prefixes = {h.id.split("_")[0] for h in hits}
                assert len(prefixes) == 1, prefixes
                seen.update(prefixes)
                st.get(["g0_1", "g1_1", "g2_1"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    [t.start() for t in threads]
    for gen in range(1, 13):
        with st.begin_rebuild() as rb:
            rb.upsert([f"g{gen}_{i}" for i in range(60)], V)
            rb.commit()
    stop.set()
    [t.join() for t in threads]
    assert not errors, errors[:1]
    assert len(seen) >= 2                                                   # the readers did span swaps
    assert st.manifest().generation == "g000013" and st.count() == 60


def test_old_generations_are_removed_after_the_grace_period(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "RETIRE_GRACE_SECONDS", 0.0)
    V = _built(tmp_path, "exact")
    st = make_store(tmp_path, "exact")
    rb = st.begin_rebuild()
    rb.upsert(["a"], V[:1])
    rb.commit()
    rb2 = st.begin_rebuild()
    rb2.upsert(["b"], V[1:2])
    rb2.commit()
    names = sorted(p.name for p in (tmp_path / "ns").iterdir() if p.name.startswith("g"))
    assert names == ["g000003"]
    st.close()


def test_a_new_writer_removes_generations_left_by_a_crash(tmp_path):
    _built(tmp_path, "exact")
    leftover = tmp_path / "ns" / "g000009"
    leftover.mkdir()
    (leftover / "vectors.f32").write_bytes(b"x")
    st = make_store(tmp_path, "exact")
    st.upsert(["n"], unit(np.random.default_rng(0), 1))
    assert not leftover.exists() and st.count() == 51


def test_rebuilding_while_the_old_generation_is_stale_keeps_bookkeeping_readable(tmp_path):
    _built(tmp_path, "exact", "test/model-a")
    st = make_store(tmp_path, "exact", spec=spec(DIM, "test/model-b"))
    rb = st.begin_rebuild()
    rb.upsert(["only"], unit(np.random.default_rng(1), 1))
    assert st.count() == 50 and st.manifest().model == "test/model-a"
    rb.commit()
    assert st.count() == 1 and st.manifest().model == "test/model-b"


@pytest.mark.skipif(not LANCE_AVAILABLE, reason=LANCE_SKIP)
def test_converting_between_backends_keeps_every_vector(tmp_path):
    rng = np.random.default_rng(6)
    V = unit(rng, 80)
    ids, metas = make_meta(rng, 80)
    st = make_store(tmp_path, "exact")
    st.upsert(ids, V, metas)
    assert not st.backend_mismatch()
    st.close()
    lance = make_store(tmp_path, "lance")
    assert lance.backend_mismatch() and lance.manifest().backend == "exact"
    assert lance.convert_backend() is True
    assert lance.manifest().backend == "lance" and lance.count() == 80
    got = lance.get(ids)
    assert all(np.array_equal(got[i][0], V[n]) and got[i][1] == metas[n] for n, i in enumerate(ids))
    assert lance.search(V[3], 1)[0].id == "id3"
    assert lance.convert_backend() is False
    lance.close()
    back = make_store(tmp_path, "exact")
    assert back.convert_backend() is True and back.manifest().backend == "exact"
    assert back.search(V[9], 1)[0].id == "id9" and back.count() == 80
