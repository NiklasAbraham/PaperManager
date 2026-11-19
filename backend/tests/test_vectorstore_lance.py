"""LanceDB backend specifics (skipped, with the reason, when the optional package is missing)."""
from __future__ import annotations

import numpy as np
import pytest

from services.vectorstore import backend_name, registry
from services.vectorstore.lance_store import where_sql
from services.vectorstore import compile_filter
from tests.vectorstore_helpers import LANCE_AVAILABLE, LANCE_SKIP, make_meta, make_store, reference, unit


def test_where_clause_values_are_escaped_or_validated():
    sql = where_sql(compile_filter({"kind": "it's", "year": {"gte": 2020}, "id": ["a'b"],
                                    "published": {"lt": "2026-02-03"}}))
    assert sql == "kind IN ('it''s') AND year >= 2020 AND id IN ('a''b') AND published < '2026-02-03'"
    assert where_sql([]) is None
    assert where_sql(compile_filter({"id": []})) == "1 = 0"
    with pytest.raises(ValueError):
        compile_filter({"year": "2020; DROP"})
    with pytest.raises(ValueError):
        where_sql([("in", "kind", ["a\x00b"])])


def test_without_the_package_the_exact_backend_is_used_with_a_warning(monkeypatch, caplog):
    import builtins

    real_import = builtins.__import__

    def no_lance(name, *a, **kw):
        if name == "lancedb":
            raise ImportError("no lancedb here")
        return real_import(name, *a, **kw)

    monkeypatch.setenv("VECTOR_STORE", "lance")
    monkeypatch.setattr(builtins, "__import__", no_lance)
    with caplog.at_level("WARNING"):
        assert backend_name() == "exact"
        assert backend_name() == "exact"
    assert sum("lancedb" in r.message for r in caplog.records) == 1            # warned once
    st = registry.get_store("fallback")
    assert st.backend == "exact"


def test_an_unknown_backend_name_falls_back_to_exact(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "faiss")
    assert backend_name() == "exact"
    monkeypatch.setenv("VECTOR_STORE", "")
    assert backend_name() == "exact"


@pytest.mark.skipif(not LANCE_AVAILABLE, reason=LANCE_SKIP)
def test_env_selects_the_lance_backend_for_new_namespaces(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "lance")
    assert backend_name() == "lance"
    st = registry.get_store("viaenv")
    st.upsert(["a"], unit(np.random.default_rng(0), 1, 384))
    assert st.manifest().backend == "lance" and st.search(unit(np.random.default_rng(0), 1, 384)[0], 1)[0].id == "a"


@pytest.mark.skipif(not LANCE_AVAILABLE, reason=LANCE_SKIP)
def test_an_ann_index_is_built_above_the_threshold_and_filters_still_apply(tmp_path, monkeypatch):
    from services.vectorstore import lance_store

    monkeypatch.setattr(lance_store, "INDEX_MIN_ROWS", 400)
    rng = np.random.default_rng(3)
    dim = 32
    V = unit(rng, 1500, dim)
    ids, metas = make_meta(rng, 1500)
    st = make_store(tmp_path, "lance", dim=dim)
    st.upsert(ids[:300], V[:300], metas[:300])
    assert st._gen._indexed_at == 0                                    # below the threshold: flat search
    st.upsert(ids[300:], V[300:], metas[300:])
    assert st._gen._indexed_at == 1500
    assert any("vector" in (getattr(i, "columns", None) or []) for i in st._gen._t.list_indices())
    hits_total, hit_in_top = 0, 0
    for q in unit(rng, 20, dim):
        got = [h.id for h in st.search(q, 10)]
        want = [i for i, _ in reference(V, ids, q, 10)]
        hits_total += 10
        hit_in_top += len(set(got) & set(want))
    assert hit_in_top / hits_total >= 0.85                             # approximate, but close
    flt = {"kind": "paper", "year": {"gte": 2026}}
    got = st.search(V[0], 25, flt)
    assert got and all(h.metadata["kind"] == "paper" and h.metadata["year"] >= 2026 for h in got)
    st.upsert(["late"], V[:1])                                          # rows added after the index are found too
    assert st.search(V[0], 5)[0].score == pytest.approx(1.0, abs=1e-3)
