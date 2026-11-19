"""The vector store interface on both backends: search against a brute-force reference, filters,
upsert / delete / get, normalisation, persistence. The lance cases are skipped without lancedb."""
from __future__ import annotations

import numpy as np
import pytest

from services.vectorstore import compile_filter
from tests.vectorstore_helpers import (DIM, LANCE_AVAILABLE, LANCE_SKIP, make_meta, make_store, reference, spec, unit)

BACKENDS = ["exact", pytest.param("lance", marks=pytest.mark.skipif(not LANCE_AVAILABLE, reason=LANCE_SKIP))]


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param


@pytest.fixture
def filled(tmp_path, backend):
    rng = np.random.default_rng(1)
    V = unit(rng, 600)
    ids, metas = make_meta(rng, 600)
    st = make_store(tmp_path, backend)
    for s in range(0, 600, 200):                      # several batches: rows span many appends
        st.upsert(ids[s:s + 200], V[s:s + 200], metas[s:s + 200])
    yield st, V, ids, metas, rng
    st.close()


def _keep(metas, pred):
    return np.array([pred(m) for m in metas])


def test_search_matches_brute_force_without_filter(filled):
    st, V, ids, metas, rng = filled
    assert st.count() == 600 and st.manifest().count == 600
    for q in unit(rng, 20):
        got = st.search(q, 10)
        want = reference(V, ids, q, 10)
        assert [h.id for h in got] == [i for i, _ in want]
        np.testing.assert_allclose([h.score for h in got], [s for _, s in want], atol=1e-5)


def test_search_returns_metadata_and_clamps_k(filled):
    st, V, ids, metas, _ = filled
    hit = st.search(V[7], 1)[0]
    assert hit.id == "id7" and hit.score == pytest.approx(1.0, abs=1e-5)
    assert hit.metadata == {k: v for k, v in metas[7].items()}
    assert len(st.search(V[0], 5000)) == 600
    assert st.search(V[0], 0) == []


FILTERS = [
    ({"kind": "paper"}, lambda m: m["kind"] == "paper"),
    ({"kind": ["paper", "book"], "source": "arxiv"}, lambda m: m["kind"] in ("paper", "book") and m["source"] == "arxiv"),
    ({"year": 2026}, lambda m: m["year"] == 2026),
    ({"year": {"gte": 2026, "lt": 2027}, "kind": "candidate"}, lambda m: m["year"] == 2026 and m["kind"] == "candidate"),
    ({"published": {"gte": "2026-06-01", "lte": "2026-12-31"}}, lambda m: "2026-06-01" <= m["published"] <= "2026-12-31"),
    ({"published": {"gt": "2026-06-01"}}, lambda m: m["published"] > "2026-06-01"),
    ({"added_at": {"gte": "2026-09-01T00:00:00Z", "lt": "2027-01-01T00:00:00Z"}},
     lambda m: "2026-09-01T00:00:00Z" <= m["added_at"] < "2027-01-01T00:00:00Z"),
    ({"kind": "nothing-like-this"}, lambda m: False),
]


@pytest.mark.parametrize("flt,pred", FILTERS)
def test_filters_match_the_reference(filled, flt, pred):
    st, V, ids, metas, rng = filled
    keep = _keep(metas, pred)
    for q in unit(rng, 5):
        got = st.search(q, 10, flt)
        want = reference(V, ids, q, 10, keep)
        assert [h.id for h in got] == [i for i, _ in want]
        np.testing.assert_allclose([h.score for h in got], [s for _, s in want], atol=1e-5)
    assert {h.id for h in st.search(V[0], 600, flt)} == {i for i, m in zip(ids, metas) if pred(m)}


def test_id_filters_and_all_vectors(filled):
    st, V, ids, metas, _ = filled
    only = st.search(V[0], 50, {"id": ["id3", "id4", "id999"]})
    assert {h.id for h in only} == {"id3", "id4"}
    rest = st.search(V[3], 600, {"exclude_id": ["id3"]})
    assert len(rest) == 599 and "id3" not in {h.id for h in rest}
    got_ids, mat = st.all_vectors({"kind": "book"})
    want = [i for i, m in zip(ids, metas) if m["kind"] == "book"]
    assert sorted(got_ids) == sorted(want) and mat.shape == (len(want), DIM)
    by_id = dict(zip(got_ids, mat))
    np.testing.assert_allclose(by_id[want[0]], V[ids.index(want[0])], atol=1e-6)


def test_bad_filters_are_errors(filled):
    st, V, *_ = filled
    with pytest.raises(ValueError):
        st.search(V[0], 3, {"venue": "x"})
    with pytest.raises(ValueError):
        st.search(V[0], 3, {"year": {"between": 1}})
    with pytest.raises(ValueError):
        st.search(V[0], 3, {"published": "not a date"})
    assert compile_filter(None) == [] and compile_filter({}) == []


def test_upsert_replaces_by_id_and_delete_removes(filled):
    st, V, ids, metas, rng = filled
    new = unit(rng, 1)
    st.upsert(["id10"], new, [{"kind": "book", "source": "library", "year": 1999}])
    assert st.count() == 600
    top = st.search(new[0], 1)[0]
    assert top.id == "id10" and top.metadata["year"] == 1999 and top.metadata["kind"] == "book"
    assert "id10" not in {h.id for h in st.search(V[10], 600)[:1]}       # the old vector is gone
    assert st.delete(["id10", "id11", "nope"]) == 2
    assert st.count() == 598 and "id11" not in set(st.ids())
    assert st.get(["id10", "id11"]) == {}
    assert st.delete([]) == 0


def test_batch_with_a_repeated_id_keeps_the_last(tmp_path, backend):
    rng = np.random.default_rng(3)
    V = unit(rng, 3)
    st = make_store(tmp_path, backend)
    st.upsert(["a", "b", "a"], V, [{"kind": "x"}, {"kind": "y"}, {"kind": "z"}])
    assert st.count() == 2
    got = st.get(["a"])["a"]
    np.testing.assert_allclose(got[0], V[2], atol=1e-6)
    assert got[1]["kind"] == "z"


def test_get_and_metadata_without_vectors(filled):
    st, V, ids, metas, _ = filled
    got = st.get(["id5", "id6", "missing"])
    assert set(got) == {"id5", "id6"}
    np.testing.assert_allclose(got["id5"][0], V[5], atol=1e-6)
    assert got["id5"][1]["n"] == 5
    md = st.metadata(["id1", "id2", "missing"])
    assert set(md) == {"id1", "id2"} and md["id2"]["n"] == 2
    assert len(st.metadata()) == 600
    assert set(st.ids()) == set(ids)


def test_vectors_are_normalised_and_input_is_validated(tmp_path, backend):
    st = make_store(tmp_path, backend)
    st.upsert(["a", "b"], np.array([[3.0] + [0.0] * (DIM - 1), [0.0, 5.0] + [0.0] * (DIM - 2)], np.float32))
    v = st.get(["a"])["a"][0]
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-6
    q = np.array([10.0] + [0.0] * (DIM - 1), np.float32)       # a query is normalised too
    assert st.search(q, 1)[0].id == "a" and st.search(q, 1)[0].score == pytest.approx(1.0, abs=1e-6)
    for bad in (np.zeros((1, DIM + 1), np.float32), np.full((1, DIM), np.nan, np.float32)):
        with pytest.raises(ValueError):
            st.upsert(["x"], bad)
    with pytest.raises(ValueError):
        st.upsert(["x", "y"], np.ones((1, DIM), np.float32))
    with pytest.raises(ValueError):
        st.search(np.ones(DIM + 3, np.float32), 1)
    with pytest.raises(ValueError):
        st.upsert(["x"], np.ones((1, DIM), np.float32), [{"o": object()}])
    assert st.count() == 2


def test_already_unit_vectors_are_stored_bit_identically(tmp_path, backend):
    V = unit(np.random.default_rng(5), 50)
    st = make_store(tmp_path, backend)
    st.upsert([str(i) for i in range(50)], V)
    got = st.get([str(i) for i in range(50)])
    assert all(np.array_equal(got[str(i)][0], V[i]) for i in range(50))


def test_reopen_reads_what_was_written(tmp_path, backend):
    rng = np.random.default_rng(9)
    V = unit(rng, 80)
    ids, metas = make_meta(rng, 80)
    st = make_store(tmp_path, backend)
    st.upsert(ids, V, metas)
    st.delete(["id3"])
    st.upsert(["id4"], V[3:4], [{"kind": "book"}])
    st.close()
    again = make_store(tmp_path, backend)
    assert again.count() == 79 and again.state() == "ready" and again.manifest().count == 79
    assert again.search(V[3], 1)[0].id == "id4"
    assert again.get(["id3"]) == {}
    assert again.search(V[9], 1)[0].metadata == metas[9]


def test_odd_ids_and_filter_values_are_data_not_syntax(tmp_path, backend):
    rng = np.random.default_rng(11)
    V = unit(rng, 4)
    odd = ["a'b", 'q"x', "p/1", "x'); DROP TABLE items; --"]
    st = make_store(tmp_path, backend)
    st.upsert(odd, V, [{"kind": "it's", "source": "s'"} for _ in odd])
    assert st.get([odd[3]])[odd[3]][1]["kind"] == "it's"
    assert {h.id for h in st.search(V[0], 10, {"kind": "it's"})} == set(odd)
    assert [h.id for h in st.search(V[0], 10, {"id": [odd[0]]})] == [odd[0]]
    assert st.delete([odd[3]]) == 1 and st.count() == 3
    assert st.search(V[0], 10, {"kind": "x' OR '1'='1"}) == []


def test_empty_store(tmp_path, backend):
    st = make_store(tmp_path, backend)
    assert st.count() == 0 and st.ids() == [] and st.search(np.ones(DIM, np.float32), 3) == []
    assert st.state() == "missing" and st.manifest() is None
    ids, mat = st.all_vectors()
    assert ids == [] and mat.shape == (0, DIM)


def test_manifest_records_model_and_counts(tmp_path, backend):
    st = make_store(tmp_path, backend, spec=spec(DIM, "test/m", pooling="mean", doc_prefix="d: "))
    st.upsert(["a"], unit(np.random.default_rng(0), 1))
    m = st.manifest()
    assert (m.namespace, m.backend, m.model, m.dim, m.pooling, m.doc_prefix, m.count) == \
        ("ns", backend, "test/m", DIM, "mean", "d: ", 1)
    assert m.text_format and m.created_at and m.updated_at and m.generation == "g000001"
