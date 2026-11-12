"""Bench + visual check of the topic-map layout.

usage: python scripts/topic_map_bench.py EMB_DIR_OR_EMB_NPY [--attrs attrs.json] [--png out.png]
                                         [--seeded] [--seed 0] [--limit N] [--dump layout.json]

EMB_DIR holds emb.npy and meta.json (as written by services.library_search.semantic).
attrs.json: {"papers": [{id,title,tags,topics,projects}], "projects": [{id,name}]}.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services import topic_map as tm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--attrs")
    ap.add_argument("--png", default="topic_map_bench.png")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seeded", action="store_true", help="also time a seeded re-layout (50 papers removed, re-added)")
    ap.add_argument("--layout", help="reuse a --dump file instead of recomputing the layout (labels iteration)")
    ap.add_argument("--dump", help="write layout.json-style output")
    a = ap.parse_args()
    d = Path(a.path)
    d = d.parent if d.suffix == ".npy" else d
    X = np.load(d / "emb.npy")
    meta = json.loads((d / "meta.json").read_text())
    ids = meta["ids"]
    if a.limit:
        X, ids = X[: a.limit], ids[: a.limit]
    print(f"n={len(ids)} dim={X.shape[1]}")
    t = {}
    t0 = time.perf_counter()
    if a.layout:
        lay = json.loads(Path(a.layout).read_text())
        assert lay["ids"] == ids, "layout file does not match the embedding ids"
        xy = np.stack([lay["x"], lay["y"]], axis=1)
    else:
        xy = tm.compute_layout(X, seed=a.seed, timings=t)
    print({k: round(v, 2) for k, v in t.items()})
    papers = {}
    if a.attrs:
        att = json.loads(Path(a.attrs).read_text())
        papers = {p["id"]: p for p in att["papers"]}
    rec = [papers.get(i, {"title": "", "tags": [], "topics": []}) for i in ids]
    t1 = time.perf_counter()
    k = tm.cluster_count(len(ids))
    assign = tm.cluster(xy, k)
    t_cl = time.perf_counter() - t1
    t1 = time.perf_counter()
    titles = [r.get("title") or "" for r in rec]
    tps, tgs = [r.get("topics", []) for r in rec], [r.get("tags", []) for r in rec]
    info = tm.label_clusters_info(assign, k, titles, tps, tgs)
    labels, muted = info["labels"], info["muted"]
    info = tm.label_clusters_info(assign, k, titles, tps, tgs, top=8)
    pub = tm.label_clusters_info(assign, k, titles, tps, tgs, include=np.array([not r.get("projects") for r in rec]))
    t_lab = time.perf_counter() - t1
    print(f"cluster {t_cl:.2f}s labels (admin + public) {t_lab:.2f}s total {time.perf_counter() - t0:.2f}s")
    rng = np.random.default_rng(0)
    for j in range(k):
        m = np.nonzero(assign == j)[0]
        nj = sum(tm.junk_title(titles[i]) for i in m)
        lib = sum(tm.SYSTEM_TAG not in tgs[i] for i in m)
        print(f"  {j} {len(m):6d} (library {lib}, junk {nj / max(1, len(m)):.0%}){' MUTED' if muted[j] else ''}  "
              f"{labels[j]}   [public: {pub['labels'][j]}]")
        print("      top5:", "; ".join(f"{kd}:{x} {s}" for s, kd, x in info["candidates"][j]))
        good = [i for i in m if not tm.junk_title(titles[i])]
        for i in rng.choice(good, min(5, len(good)), replace=False):
            print("      -", titles[i][:100])
    if a.dump:
        Path(a.dump).write_text(json.dumps({"ids": ids, "x": xy[:, 0].tolist(), "y": xy[:, 1].tolist()}))
    if a.seeded:
        rng = np.random.default_rng(1)
        drop = rng.choice(len(ids), 50, replace=False)
        keep = np.setdiff1d(np.arange(len(ids)), drop)
        prev = {"ids": [ids[i] for i in keep], "x": xy[keep, 0], "y": xy[keep, 1]}
        t1 = time.perf_counter()
        init = tm.seed_init(X, ids, prev)
        t_seed = time.perf_counter() - t1
        t2 = {}
        xy2 = tm.compute_layout(X, seed=a.seed, init=init, timings=t2)
        move = np.sqrt(((xy2[keep] - xy[keep]) ** 2).sum(axis=1))
        print(f"seeded relayout: init {t_seed:.2f}s, layout {t2['total']:.2f}s {({k: round(v, 2) for k, v in t2.items()})}; "
              f"median move of kept points {np.median(move):.4f}, p95 {np.percentile(move, 95):.4f}")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 12), dpi=110)
    pal, s = [], 0
    for j in range(k):
        pal.append(tm.MUTED_COLOR if muted[j] else tm.CLUSTER_COLORS[s % 8])
        s += 0 if muted[j] else 1
    cols = np.array(pal)[assign]
    isref = np.array([tm.SYSTEM_TAG in r.get("tags", []) for r in rec])
    ax.scatter(xy[isref, 0], xy[isref, 1], c=cols[isref], s=2, alpha=0.35, linewidths=0)
    ax.scatter(xy[~isref, 0], xy[~isref, 1], c=cols[~isref], s=9, alpha=0.9, linewidths=0.3, edgecolors="white")
    for j in range(k):
        m = assign == j
        ax.text(np.median(xy[m, 0]), np.median(xy[m, 1]), labels[j], fontsize=13, weight="bold", ha="center",
                bbox=dict(boxstyle="round", fc="white", alpha=0.8, lw=0))
    ax.set_xlim(-0.02, 1.02); ax.set_ylim(-0.02, 1.02); ax.set_aspect("equal"); ax.axis("off")
    fig.savefig(a.png, bbox_inches="tight")
    print("png", a.png)


if __name__ == "__main__":
    main()
