"""Search speed of the exact backend on 200,000 x 384 random vectors."""
from __future__ import annotations

import time

import numpy as np

from tests.vectorstore_helpers import make_store, spec, unit

N, DIM_, QUERIES = 200_000, 384, 15


def test_top_10_of_200k_vectors_is_fast(tmp_path, capsys):
    rng = np.random.default_rng(0)
    st = make_store(tmp_path, "exact", spec=spec(DIM_))
    t0 = time.perf_counter()
    for s in range(0, N, 20_000):
        V = unit(rng, 20_000, DIM_)
        st.upsert([f"id{s + i}" for i in range(20_000)], V,
                  [{"kind": "paper" if i % 2 else "candidate", "year": 2000 + i % 25} for i in range(20_000)])
    load_s = time.perf_counter() - t0
    assert st.count() == N
    q = unit(rng, QUERIES, DIM_)
    st.search(q[0], 10)                                              # warm the page cache
    times = []
    for v in q:
        t = time.perf_counter()
        hits = st.search(v, 10)
        times.append((time.perf_counter() - t) * 1000)
        assert len(hits) == 10
    ft = []
    for v in q[:5]:
        t = time.perf_counter()
        st.search(v, 10, {"kind": "paper", "year": {"gte": 2010}})
        ft.append((time.perf_counter() - t) * 1000)
    # exactness on the same data
    ids, mat = st.all_vectors()
    want = [ids[i] for i in np.argsort(-(mat @ q[1]))[:10]]
    assert [h.id for h in st.search(q[1], 10)] == want
    med, worst = float(np.median(times)), max(times)
    with capsys.disabled():
        print(f"\n[vectorstore perf] {N} x {DIM_}: load {load_s:.1f}s; top-10 median {med:.1f} ms, worst {worst:.1f} ms; "
              f"filtered median {float(np.median(ft)):.1f} ms")
    assert med < 500, f"median {med:.0f} ms"        # the target is ~100 ms; this bound only catches a regression
