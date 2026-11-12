"""Pure tests for services.topic_map (no database, no model)."""
import types
from datetime import datetime, timezone

import numpy as np
import pytest

from services import topic_map as tm


def blobs(n_per=60, d=384, centres=3, seed=0, noise=0.15):
    rng = np.random.default_rng(seed)
    C = rng.normal(size=(centres, d))
    X = np.vstack([c + noise * rng.normal(size=(n_per, d)) * np.abs(c).mean() for c in C])
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return X.astype(np.float32), np.repeat(np.arange(centres), n_per)


def test_layout_shape_finite_range_and_determinism():
    X, _ = blobs()
    a = tm.compute_layout(X, seed=3, epochs=40)
    b = tm.compute_layout(X, seed=3, epochs=40)
    assert a.shape == (180, 2)
    assert np.isfinite(a).all()
    assert a.min() >= 0.0 and a.max() <= 1.0
    assert np.array_equal(a, b)
    assert not np.array_equal(a, tm.compute_layout(X, seed=4, epochs=40))


def test_blobs_stay_together_and_apart():
    X, truth = blobs()
    xy = tm.compute_layout(X, epochs=80)
    cent = np.array([xy[truth == j].mean(axis=0) for j in range(3)])
    within = np.mean([np.linalg.norm(xy[truth == j] - cent[j], axis=1).mean() for j in range(3)])
    between = min(np.linalg.norm(cent[i] - cent[j]) for i in range(3) for j in range(i))
    assert between > 2 * within
    lab = tm.cluster(xy, 3)
    # every blob maps to (almost) one cluster
    for j in range(3):
        assert np.bincount(lab[truth == j], minlength=3).max() >= 0.95 * 60


def test_tiny_inputs():
    assert tm.compute_layout(np.zeros((0, 384), dtype=np.float32)).shape == (0, 2)
    assert tm.compute_layout(np.ones((1, 384), dtype=np.float32)).shape == (1, 2)
    rng = np.random.default_rng(0)
    X = rng.normal(size=(7, 384)).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    xy = tm.compute_layout(X)
    assert xy.shape == (7, 2) and np.isfinite(xy).all() and xy.min() >= 0 and xy.max() <= 1
    same = np.tile(X[:1], (5, 1))                    # identical vectors
    assert tm.compute_layout(same).shape == (5, 2)
    assert np.isfinite(tm.compute_layout(np.tile(X[:1], (40, 1)), epochs=5)).all()   # duplicates, n >= 20
    assert tm.cluster(np.zeros((0, 2))).shape == (0,)
    assert tm.cluster(np.array([[0.1, 0.2]]), 5).tolist() == [0]


def test_seeded_layout_stays_close():
    X, _ = blobs()
    full = tm.compute_layout(X, epochs=60)
    again = tm.compute_layout(X, init=full, epochs=10)
    assert np.median(np.linalg.norm(again - full, axis=1)) < 0.1


def test_seed_init_places_new_ids_near_neighbours():
    X, truth = blobs()
    ids = [f"p{i}" for i in range(len(X))]
    xy = tm.compute_layout(X, epochs=40)
    keep = [i for i in range(len(X)) if i % 10 != 0]
    prev = {"ids": [ids[i] for i in keep], "x": xy[keep, 0], "y": xy[keep, 1]}
    init = tm.seed_init(X, ids, prev)
    assert init.shape == (len(X), 2)
    assert np.median(np.linalg.norm(init - xy, axis=1)) < 0.05
    assert tm.seed_init(X, ids, None) is None
    assert tm.seed_init(X, ids, {"ids": ["zz"], "x": [0], "y": [0]}) is None     # too little overlap


def test_cluster_count_and_order():
    assert tm.cluster_count(0) == 3 and tm.cluster_count(100) == 3
    assert tm.cluster_count(10635) == 8 and tm.cluster_count(1173) == 7
    rng = np.random.default_rng(1)
    xy = np.vstack([rng.normal([0, 0], 0.02, (50, 2)), rng.normal([1, 1], 0.02, (200, 2)),
                    rng.normal([0, 1], 0.02, (100, 2))])
    a = tm.cluster(xy, 3)
    assert np.bincount(a).tolist() == [200, 100, 50]
    assert np.array_equal(a, tm.cluster(xy, 3))


def test_normalize_xy_aspect_and_outliers():
    rng = np.random.default_rng(0)
    Y = rng.normal(size=(500, 2)) * [4, 1]
    Y[0] = [1e6, 1e6]
    out = tm.normalize_xy(Y)
    assert out.min() >= 0 and out.max() <= 1
    assert np.ptp(out[:, 0]) > 2 * np.ptp(out[:, 1])        # aspect ratio kept
    assert np.round(out, 4).tolist() == out.tolist()
    assert tm.normalize_xy(np.zeros((3, 2))).tolist() == [[0.5, 0.5]] * 3


def _label(assign, titles, topics=None, tags=None, k=None):
    n = len(assign)
    return tm.label_clusters(np.array(assign), k or int(max(assign)) + 1, titles,
                             topics or [[] for _ in range(n)], tags or [[] for _ in range(n)])


def test_label_prefers_topic_with_threshold():
    assign = [0] * 10 + [1] * 10
    topics = [["Protein design"]] * 5 + [[]] * 5 + [["Other"]] * 2 + [[]] * 8
    labels = _label(assign, [f"Qq{chr(97 + i)}x Zz{chr(97 + i)}y" for i in range(20)], topics)
    assert labels[0] == "Protein design"            # 5 of 5 bearing, >= 3 papers
    assert labels[1] != "Other"                     # only 2 papers: rule not met


def test_label_tag_rule_excludes_system_and_common_tags():
    n = 60
    assign = [0] * 20 + [1] * 20 + [2] * 20
    tags = []
    for i in range(n):
        own = "protein-design" if i < 20 else ("pdf-upload" if i < 40 else "x-ray")
        tags.append(["from-references", "everywhere", own])
    labels = _label(assign, ["Some plain title"] * n, tags=tags)
    assert labels[0] == "Protein Design" and labels[2] == "X Ray"
    assert labels[1] not in ("Everywhere", "From References", "Pdf Upload")


def test_label_title_terms_bigram_and_unique():
    t0 = ["Diffusion models for protein backbones", "Protein backbone generation with diffusion"] * 6
    t1 = ["Graph neural networks for molecules", "Molecular graph neural networks"] * 6
    t2 = ["Language model reasoning chains", "Chain of thought reasoning in language models"] * 6
    titles = t0 + t1 + t2
    assign = [0] * 12 + [1] * 12 + [2] * 12
    labels = _label(assign, titles)
    assert len(set(l.lower() for l in labels)) == 3
    assert all(1 <= len(l.split()) <= 3 for l in labels)
    assert any(w in labels[0] for w in ("Protein", "Diffusion", "Backbone"))
    # same text everywhere: labels must still be unique
    dup = _label([0] * 10 + [1] * 10, ["Protein folding dynamics"] * 20)
    assert dup[0].lower() != dup[1].lower()


def test_author_list_titles_are_ignored():
    assert tm.looks_like_author_list("Rosenberg SA, and Dudley ME (2009)")
    assert tm.looks_like_author_list("Chen, M., Mao, S. & Liu, Y")
    assert tm.looks_like_author_list("Chaofan Li, Zheng Liu, Shitao Xiao, and Yingxia Shao")
    assert not tm.looks_like_author_list("Attention is all you need")
    assert not tm.looks_like_author_list("Diffusion models, flow matching and score networks in biology")


# ---- payload assembly (fake attributes, no database)

def _fake():
    ids = [f"p{i}" for i in range(40)]
    rng = np.random.default_rng(0)
    xy = rng.random((40, 2))
    layout = {"ids": ids, "x": xy[:, 0].tolist(), "y": xy[:, 1].tolist(), "n": 40, "computed_at": "2026-11-12T00:00:00+00:00",
              "seconds": 1.0}
    papers = []
    for i, pid in enumerate(ids):
        papers.append({"id": pid, "title": f"Title {i}", "tags": ["from-references"] if i % 2 else (["lib", "rare"] if i < 8 else ["lib"]),
                       "topics": ["Topic A"] if i < 5 else [], "projects": ["pB"] if i < 10 else (["pA"] if i < 15 else [])})
    papers.append({"id": "ghost", "title": "Not embedded", "tags": ["rare"], "topics": [], "projects": []})
    papers.append({"id": "lost", "title": "No info", "tags": ["from-references"], "topics": [], "projects": []})
    attrs = {"papers": papers, "projects": [{"id": "pB", "name": "B"}, {"id": "pA", "name": "A"}]}
    return layout, attrs


def test_payload_admin_and_refs_filter():
    layout, attrs = _fake()
    d = tm.derive(layout, attrs)
    assert "ghost" in d["ids"] and "lost" not in d["ids"]        # shared tag 'rare' places it; no info -> left out
    p = tm.build_payload(layout, attrs, d, set(), True)
    assert p["state"] == "ready" and p["n"] == 41
    assert [pr["id"] for pr in p["projects"]] == ["pA", "pB"]
    assert p["clusters"] and all(c["color"] in tm.CLUSTER_COLORS + [tm.MUTED_COLOR] for c in p["clusters"])
    assert sum(c["size"] for c in p["clusters"]) == 41
    assert all(0 <= pt["x"] <= 1 and 0 <= pt["y"] <= 1 for pt in p["points"])
    p0 = tm.build_payload(layout, attrs, d, set(), False)
    assert all(pt["r"] == 0 for pt in p0["points"]) and p0["n"] < p["n"]
    assert sum(c["library"] for c in p["clusters"]) == p0["n"]


def test_payload_hides_invisible_projects_and_papers():
    layout, attrs = _fake()
    d = tm.derive(layout, attrs)
    hidden = {f"p{i}" for i in range(10)}                          # all of project pB
    view = {**attrs, "visible_project_ids": {"pA"}}
    p = tm.build_payload(layout, view, d, hidden, True)
    ids = {pt["id"] for pt in p["points"]}
    assert not (ids & hidden) and p["n"] == 31
    assert [pr["name"] for pr in p["projects"]] == ["A"]
    assert all(pt["p"] in ([], [0]) for pt in p["points"])
    assert p["projects"][0]["count"] == 5
    assert [pr["id"] for pr in tm.build_payload(layout, {**attrs, "visible_project_ids": {"pA", "pB"}}, d, set(), False)["projects"]] \
        == ["pA", "pB"]
    assert tm.empty_payload("building")["points"] == []


def test_project_colors_stable_by_id():
    a = tm.project_colors(["b", "a", "c"])
    assert a["a"] == tm.CLUSTER_COLORS[3] and a["b"] == tm.CLUSTER_COLORS[4]
    assert tm.project_colors(["a", "b", "c", "d"])["a"] == a["a"]


def test_stale_detection():
    lay = {"emb_saved_at": "t1", "n": 5}
    assert not tm._is_stale(lay, {"saved_at": "t1", "n": 5})
    assert tm._is_stale(lay, {"saved_at": "t2", "n": 5})
    assert tm._is_stale(lay, {"saved_at": "t1", "n": 6})
    assert tm._is_stale(None, {"saved_at": "t1", "n": 6})
    assert not tm._is_stale(None, None)


# ---- labels: bulk of the cluster, junk, muted, privacy

def test_label_uses_bulk_not_rare_tag():
    # 100 papers about image generation; 4 carry a "computer-aided-design" tag: must not win
    t0 = ["Image generation with rectified flow", "Subject-driven image generation", "Image editing and inversion"] * 34
    tags0 = [["computer-aided-design"] if i < 4 else [] for i in range(len(t0))]
    t1 = ["Protein design with diffusion", "Protein backbone design", "Protein sequence design"] * 34
    assign = [0] * len(t0) + [1] * len(t1)
    labels = _label(assign, t0 + t1, tags=tags0 + [[] for _ in t1])
    assert "Image" in labels[0] and "Computer" not in labels[0]
    assert "Protein" in labels[1]


def test_junk_title():
    for t in ["Assran, M. et al", "Zhan, F. et al", "Chen et al.", "Hein, M. & Audibert, J.-Y",
              "François Rozet, Gérôme Andry, François Lanusse, and Gilles Louppe",
              "Competing interest statement: N.G.A. and D.V. are listed as inventors", "Umwelt-Bundesamt",
              "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L.", "", None,
              "Mandelcorn-Monson RL, Shear NH, Yau E, and DeBenedette \nMA (2003)"]:
        assert tm.junk_title(t), t
    for t in ["Attention is all you need", "Taming Rectified Flow for Inversion and Editing",
              "Diffusion models, flow matching and score networks in biology",
              "AlphaFold: protein structure prediction at atomic accuracy"]:
        assert not tm.junk_title(t), t


def test_junk_cluster_is_muted_and_skips_palette():
    good = ["Protein design with diffusion", "Protein backbone design"] * 15
    junk = ["Smith, J. et al", "Doe, A., Roe, B. & Poe, C"] * 10
    lang = ["Language model reasoning chains", "Large language model agents"] * 15
    titles = good + junk + lang
    assign = np.array([0] * 30 + [1] * 20 + [2] * 30)
    info = tm.label_clusters_info(assign, 3, titles, [[] for _ in titles], [[] for _ in titles])
    assert info["muted"] == [False, True, False] and info["labels"][1] == "Unparsed references"
    ids = [f"p{i}" for i in range(len(titles))]
    xy = np.random.default_rng(0).random((len(titles), 2))
    layout = {"ids": ids, "x": xy[:, 0].tolist(), "y": xy[:, 1].tolist(), "n": len(ids), "computed_at": "t", "seconds": 1}
    derived = {"ids": ids, "xy": xy, "assign": assign, "labels": info["labels"], "muted": info["muted"], "k": 3,
               "rec": [{"title": t, "tags": [], "topics": [], "projects": []} for t in titles]}
    p = tm.build_payload(layout, {"papers": [], "projects": []}, derived, set(), True)
    cl = p["clusters"]
    assert [c["muted"] for c in cl] == [False, True, False]
    assert cl[1]["color"] == tm.MUTED_COLOR
    assert cl[0]["color"] == tm.CLUSTER_COLORS[0] and cl[2]["color"] == tm.CLUSTER_COLORS[1]


def test_public_labels_do_not_leak_hidden_project_papers():
    n = 40
    titles = ["Receptor kinase signalling pathways"] * 20 + ["Protein design with diffusion"] * 20
    projects = [["secret"] if i < 20 else [] for i in range(n)]       # cluster 0 is entirely in a hidden project
    ids = [f"p{i}" for i in range(n)]
    xy = np.vstack([np.random.default_rng(1).normal(0, .02, (20, 2)) + .2, np.random.default_rng(2).normal(0, .02, (20, 2)) + .8])
    layout = {"ids": ids, "x": xy[:, 0].tolist(), "y": xy[:, 1].tolist(), "n": n, "computed_at": "t", "seconds": 1}
    attrs = {"papers": [{"id": i, "title": t, "tags": [], "topics": [], "projects": pr}
                        for i, t, pr in zip(ids, titles, projects)],
             "projects": [{"id": "secret", "name": "Secret"}]}
    d = tm.derive(layout, attrs)
    admin = tm.build_payload(layout, attrs, d, set(), True)
    admin_labels = " ".join(c["label"] for c in admin["clusters"])
    assert "Receptor" in admin_labels or "Kinase" in admin_labels
    hidden = {i for i, pr in zip(ids, projects) if pr}
    pub = tm.build_payload(layout, {**attrs, "visible_project_ids": set()}, d, hidden, True)
    pub_labels = " ".join(c["label"] for c in pub["clusters"])
    assert not any(w in pub_labels for w in ("Receptor", "Kinase", "Signalling")), pub_labels
    assert pub["projects"] == []


# ---- background job, debounce, cold start

import json as _json
import time as _time
from concurrent.futures import Future as _Future


class _Driver:
    """Fake Neo4j driver: serves attrs, counts queries; no hidden papers (admin path patched below)."""
    def __init__(self, attrs):
        self.attrs, self.queries = attrs, 0

    def session(self):
        drv = self

        class S:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def run(s, q, **kw):
                drv.queries += 1
                return drv.attrs["papers"] if "Paper" in q and "Project" not in q.split("RETURN")[0] else drv.attrs["projects"]
        return S()


@pytest.fixture
def world(tmp_path, monkeypatch):
    layout, attrs = _fake()
    edir = tmp_path / "emb"; edir.mkdir()
    meta = {"saved_at": "t1", "ids": layout["ids"]}
    (edir / "meta.json").write_text(_json.dumps(meta))
    layout = {**layout, "emb_saved_at": "t1", "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    mdir = tmp_path / "map"; mdir.mkdir()
    monkeypatch.setenv("TOPIC_MAP_DIR", str(mdir))
    monkeypatch.setattr(tm, "emb_dir", lambda: edir)
    monkeypatch.setattr(tm, "hidden_paper_ids", lambda d: (set(), None))
    monkeypatch.setattr(tm, "_cache", {"layout": None, "attrs": None, "attrs_ts": 0.0, "attrs_hash": None,
                                       "derived": None, "derived_key": None, "derived_loaded": False,
                                       "job": None, "job_fail_ts": 0.0, "error": None, "meta_mtime": None, "meta": None})
    jobs = []

    def submit(fn, *args):                      # deferred: the test decides when the "child" finishes
        fut = _Future()
        jobs.append((fut, fn, args))
        return fut
    monkeypatch.setattr(tm, "_submit", submit)

    def finish():
        fut, fn, args = jobs.pop(0)
        fut.set_result(fn(*args))
    return types.SimpleNamespace(layout=layout, attrs=attrs, edir=edir, mdir=mdir, jobs=jobs, finish=finish,
                                 driver=_Driver(attrs), meta=meta)


def test_request_path_never_derives(world, monkeypatch):
    (world.mdir / "layout.json").write_text(_json.dumps(world.layout))
    calls = []
    real = tm.derive
    monkeypatch.setattr(tm, "derive", lambda *a: calls.append(1) or real(*a))
    first = tm.get_topic_map(world.driver)
    assert first["state"] == "building" and not calls and len(world.jobs) == 1
    world.finish()
    assert len(calls) == 1
    ready = tm.get_topic_map(world.driver)
    assert ready["state"] == "ready" and not ready["stale"] and (world.mdir / "derived.json").exists()
    # attrs change: the old derived result is served at once, recompute is pending
    world.attrs["papers"][0]["title"] = "Brand new title"
    tm._cache["attrs_ts"] = 0.0
    t0 = _time.perf_counter()
    tm.get_topic_map(world.driver)               # starts the background attr refresh
    for _ in range(100):
        if tm._cache["attrs"]["papers"][0]["title"] == "Brand new title":
            break
        _time.sleep(0.02)
    out = tm.get_topic_map(world.driver)
    assert _time.perf_counter() - t0 < 1.0
    assert out["state"] == "ready" and out["stale"] and out["n"] == ready["n"]
    assert len(calls) == 1 and len(world.jobs) == 1
    world.finish()
    assert len(calls) == 2 and not tm.get_topic_map(world.driver)["stale"]


def test_unchanged_attrs_do_not_rederive(world):
    (world.mdir / "layout.json").write_text(_json.dumps(world.layout))
    tm.get_topic_map(world.driver); world.finish()
    key = tm._cache["derived_key"]
    h = tm._cache["attrs_hash"]
    tm._cache["attrs_ts"] = 0.0
    tm._refresh_attrs(world.driver)              # same content, reordered lists
    world.attrs["papers"].reverse()
    tm._refresh_attrs(world.driver)
    assert tm._cache["attrs_hash"] == h
    out = tm.get_topic_map(world.driver)
    assert not world.jobs and tm._cache["derived_key"] == key and not out["stale"]


def test_derived_json_serves_cold_start(world):
    (world.mdir / "layout.json").write_text(_json.dumps(world.layout))
    tm.get_topic_map(world.driver); world.finish()
    warm = tm.get_topic_map(world.driver)
    # new process: empty cache, same files
    for k in ("layout", "attrs", "attrs_hash", "derived", "derived_key"):
        tm._cache[k] = None
    tm._cache.update(attrs_ts=0.0, derived_loaded=False, meta_mtime=None, meta=None)
    cold = tm.get_topic_map(world.driver)
    assert cold["state"] == "ready" and not world.jobs and not cold["stale"]
    assert cold["clusters"] == warm["clusters"] and cold["points"] == warm["points"]


def test_rebuild_debounce_and_big_change(world, monkeypatch):
    (world.mdir / "layout.json").write_text(_json.dumps(world.layout))
    tm.get_topic_map(world.driver); world.finish()
    # embedding file rewritten with one new id (2.5 %): recent layout stays
    world.meta["saved_at"] = "t2"
    world.meta["ids"] = world.meta["ids"] + ["new1"]
    (world.edir / "meta.json").write_text(_json.dumps(world.meta))
    out = tm.get_topic_map(world.driver)
    assert not world.jobs and out["state"] == "ready" and out["stale"]
    # interval passed: rebuild allowed
    monkeypatch.setenv("TOPIC_MAP_MIN_INTERVAL", "0")
    tm.get_topic_map(world.driver)
    assert len(world.jobs) == 1 and world.jobs[0][2][3] is True
    world.jobs.clear(); tm._cache["job"] = None
    # big change beats the interval
    monkeypatch.setenv("TOPIC_MAP_MIN_INTERVAL", "99999")
    assert not tm._needs_layout(tm._cache["layout"], {"saved_at": "t3", "n": 41})
    assert tm._needs_layout(tm._cache["layout"], {"saved_at": "t3", "n": 60})
    assert tm._needs_layout(None, {"saved_at": "t3", "n": 60})


def test_pool_failure_falls_back_to_thread(monkeypatch):
    class Boom:
        def __init__(self, *a, **k): raise OSError("no fork")
    monkeypatch.setattr(tm, "ProcessPoolExecutor", Boom)
    monkeypatch.setattr(tm, "_executor", None)
    monkeypatch.setattr(tm, "_use_pool", True)
    fut = tm._submit(lambda a: a + 1, 1)
    assert fut.result(timeout=5) == 2 and tm._use_pool is False
