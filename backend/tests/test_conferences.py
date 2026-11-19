"""Conference explorer: institution normalisation, the two source parsers, counting and
ranking, area assignment, topic search and the HTTP endpoints. No network and no model:
sources are fed fixtures, and the datasets are written by hand."""
from __future__ import annotations

import json

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from services.conferences import areas, catalog, institutions, sources, store


# ── institutions ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("University of California, Berkeley", [("UC Berkeley", "A")]),
    ("Google, TUM", [("Google", "I"), ("TU Munich", "A")]),
    ("Tsinghua University, Tsinghua University", [("Tsinghua University", "A")]),
    ("Department of Computer Science, ETHZ - ETH Zurich", [("ETH Zurich", "A")]),
    ("Xi&#x27;an Jiaotong University", [("Xi'an Jiaotong University", "A")]),
    ("Institute of automation, Chinese academy of science, Chinese Academy of Sciences",
     [("Chinese Academy of Sciences", "A")]),
    ("University College London, University of London", [("University College London", "A")]),
    ("Google DeepMind", [("Google", "I")]),
    ("Meta FAIR", [("Meta", "I")]),
    ("JIUTIAN Ｒｅｓｅａｒｃｈ", [("JIUTIAN Research", "I")]),
    ("Guangdong OPPO Mobile Telecommunications Corp.,Ltd.", [("OPPO", "I")]),
    ("Independent Researcher", []),
    ("Meituan", [("Meituan", "I")]),
    ("Istituto Italiano di Tecnologia", [("Istituto Italiano di Tecnologia", "A")]),
    ("McGill University / Mila / DeepMind Montreal", [("McGill University", "A"), ("Mila", "A"), ("Google", "I")]),
    ("Tel Aviv University and Facebook AI Research", [("Tel Aviv University", "A"), ("Meta", "I")]),
    ("Texas A&amp;M University", [("Texas A&M University", "A")]),
    ("University of Science and Technology of China", [("USTC", "A")]),
    ("Norwegian University of Science and Technology", [("Norwegian University of Science and Technology", "A")]),
    ("University of Science and Technology Beijing", [("University of Science and Technology Beijing", "A")]),
    ("Robotics and AI Institute", [("Robotics and AI Institute", "A")]),
    ("Shandong Medical and Pharmaceutical University", [("Shandong Medical and Pharmaceutical University", "A")]),
    ("Liquid AI & MIT", [("Liquid AI", "I"), ("MIT", "A")]),
    ("Department of Physics and Astronomy, University College London", [("University College London", "A")]),
    ("AXXX", []),
    ("XXX", []),
    ("Anonymous Institution", []),
    ("University", []),
    ("ML", []),
    ("e)", []),
    ("HY", []),
    ("zzmc@scut.edu.cn", []),
    ("www.hebtu.edu.cn", []),
    ("https://xinchenai.com/", []),
    ("LG", [("LG", "I")]),
    ("JD.com", [("JD.com", "I")]),
    ("CAMEL-AI.org", [("CAMEL-AI.org", "I")]),
    ("Head of AI @ Squirrel AI", [("Squirrel AI", "I")]),
    ("PALMLab @ Southeast University", [("Southeast University", "A")]),
])
def test_split_and_normalise(raw, expected):
    assert institutions.split_and_normalise(raw) == expected


def test_merge_key_folds_spellings():
    assert institutions.merge_key("The Ohio State University") == institutions.merge_key("ohio state university")
    assert institutions.merge_key("Universität Zürich") == institutions.merge_key("Universitat Zurich")


# ── catalog ───────────────────────────────────────────────────────────────────

def test_catalog_resolve():
    assert catalog.resolve("NeurIPS 2026").key == "neurips2026"
    assert catalog.resolve("nips2025").key == "neurips2025"
    assert catalog.resolve("iclr").key == "iclr2026"          # bare series = latest year
    assert catalog.resolve("acl2025").source == "papercopilot"
    assert catalog.resolve("nosuchconf") is None
    keys = [e.key for e in catalog.editions()]
    assert len(keys) == len(set(keys))


# ── sources ───────────────────────────────────────────────────────────────────

def _event(name, insts, decision="Accept (poster)", eventtype="Poster", session="Poster Session 1", **kw):
    return {
        "name": name, "decision": decision, "eventtype": eventtype, "session": session,
        "abstract": kw.get("abstract", ""), "virtualsite_url": f"/virtual/2026/poster/{abs(hash(name)) % 1000}",
        "paper_url": kw.get("paper_url", ""), "topic": kw.get("topic"), "keywords": [],
        "authors": [{"fullname": f"Author {i}", "institution": inst} for i, inst in enumerate(insts)],
    }


def test_miniconf_merges_oral_and_poster(monkeypatch):
    feed = {"count": 3, "next": None, "results": [
        _event("Paper A", ["MIT", "Google"], abstract="About A.", paper_url="https://openreview.net/forum?id=same"),
        _event("Paper A", ["MIT", "Google"], decision=None, eventtype="Oral", session="Oral 2"),
        _event("Paper B", ["Stanford University"], paper_url="https://openreview.net/forum?id=same"),
    ]}
    monkeypatch.setattr(sources, "_get_json", lambda url, timeout=0: feed)
    rows, info = sources.fetch(catalog.get_edition("neurips2026"))
    assert [r["title"] for r in rows] == ["Paper A", "Paper B"]   # shared paper_url does not merge B into A
    a = rows[0]
    assert a["decision"] == "Oral" and a["abstract"] == "About A."
    assert a["session"] == "Poster Session 1 · Oral 2"
    assert a["url"].startswith("https://neurips.cc/virtual/2026/")
    assert info == {"expected": 3, "partial": False, "events": 3}


def test_papercopilot_drops_rejected_and_reads_affiliations(monkeypatch):
    data = [
        {"title": "Kept", "status": "Spotlight", "track": "main", "author": "X;Y",
         "aff_unique_norm": "Princeton University;NVIDIA", "aff_unique_index": "0;1+0", "aff": "",
         "abstract": "abs", "site": "https://openreview.net/forum?id=1", "keywords": "a;b"},
        {"title": "Gone", "status": "Reject", "author": "Z", "aff_unique_norm": "", "aff_unique_index": "", "aff": ""},
        {"title": "Withdrawn", "status": "Withdraw", "author": "Z"},
    ]
    monkeypatch.setattr(sources, "_get_json", lambda url, timeout=0: data)
    rows, _ = sources.fetch(catalog.get_edition("acl2025"))
    assert [r["title"] for r in rows] == ["Kept"]
    r = rows[0]
    assert r["decision"] == "Spotlight"
    assert r["authors"] == [{"name": "X", "insts": ["Princeton University"]},
                            {"name": "Y", "insts": ["NVIDIA", "Princeton University"]}]
    assert r["forum"] == "https://openreview.net/forum?id=1" and r["keywords"] == ["a", "b"]


# ── areas ─────────────────────────────────────────────────────────────────────

def test_area_assignment_follows_prototypes():
    rng = np.random.default_rng(0)
    protos = np.eye(len(areas.AREAS), 32, dtype=np.float32)
    truth = rng.integers(0, len(areas.AREAS), 400)
    emb = protos[truth] + 0.05 * rng.standard_normal((400, 32)).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    assert (areas.assign(emb, protos) == truth).mean() > 0.95


# ── store: a hand-made dataset ────────────────────────────────────────────────

def _fake_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_data_dir", tmp_path)
    store._cache.clear()
    ds = {
        "key": "corl2025", "name": "CoRL 2025", "series": "CoRL", "slug": "corl", "field": "Robotics",
        "year": 2025, "source": "papercopilot", "source_url": "https://example.org/corl2025.json",
        "fetched_at": "2026-10-25T00:00:00+00:00", "partial": False, "expected": 3, "areas_ready": True,
        "insts": [{"n": "MIT", "s": "A"}, {"n": "NVIDIA", "s": "I"}, {"n": "Stanford University", "s": "A"}],
        "papers": [
            {"id": "p1", "t": "Diffusion policies for robot manipulation", "a": "We grasp things.", "au": ["A", "B"],
             "ai": [[0], [1]], "i": [0, 1], "ar": 7, "d": "Oral", "tr": "", "s": "", "u": "https://x/1", "f": "", "nt": "", "kw": []},
            {"id": "p2", "t": "Legged locomotion with reinforcement learning", "a": "", "au": ["C"],
             "ai": [[0, 2]], "i": [0, 2], "ar": 6, "d": "Poster", "tr": "", "s": "", "u": "", "f": "", "nt": "", "kw": []},
            {"id": "p3", "t": "Tactile sensing for dexterous hands", "a": "", "au": ["D", "E"],
             "ai": [[2], []], "i": [2], "ar": 7, "d": "Poster", "tr": "", "s": "", "u": "", "f": "", "nt": "", "kw": []},
        ],
    }
    store._finalise(ds)
    (tmp_path / "corl2025").mkdir()
    (tmp_path / "corl2025" / "dataset.json").write_text(json.dumps(ds))
    emb = np.eye(3, 384, dtype=np.float32)
    np.save(tmp_path / "corl2025" / "emb.npy", emb.astype(np.float16))
    store._set_status("corl2025", "ready", papers=3, institutions=3)
    return ds


def test_counts_fractional_and_rank(tmp_path, monkeypatch):
    ds = _fake_dataset(tmp_path, monkeypatch)
    by = {r["n"]: r for r in ds["insts"]}
    assert by["MIT"]["p"] == 2 and by["Stanford University"]["p"] == 2 and by["NVIDIA"]["p"] == 1
    # MIT: 1/2 of p1 + half of the single author of p2 = 1.0; Stanford: 0.5 (p2) + 0.5 (p3)
    assert by["MIT"]["f"] == 1.0 and by["Stanford University"]["f"] == 1.0 and by["NVIDIA"]["f"] == 0.5
    assert by["MIT"]["r"] == by["Stanford University"]["r"] == 1 and by["NVIDIA"]["r"] == 3
    assert by["MIT"]["a"][7] == 1 and by["MIT"]["a"][6] == 1


def test_search_institutions_and_detail(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)
    ds = store.load("corl2025")
    assert ds.areas_ready
    res = store.search_institutions(ds, q="stanf")
    assert [r["name"] for r in res["rows"]] == ["Stanford University"]
    ind = store.search_institutions(ds, sector="I")
    assert [r["name"] for r in ind["rows"]] == ["NVIDIA"]
    robo = store.search_institutions(ds, area=7)
    assert {r["name"]: r["count"] for r in robo["rows"]} == {"MIT": 1, "NVIDIA": 1, "Stanford University": 1}
    d = store.institution_detail(ds, "mit", library={"diffusionpoliciesforrobotmanipulation": "lib-1"})
    assert d["papers"] == 2 and d["paper_list"][0]["decision"] == "Oral"
    assert d["paper_list"][0]["library_id"] == "lib-1"
    assert {c["name"] for c in d["collaborators"]} == {"NVIDIA", "Stanford University"}


def test_topic_semantic_and_keyword(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)
    ds = store.load("corl2025")
    from services.conferences import embedder

    monkeypatch.setattr(embedder, "conference_embed_query", lambda text: np.eye(3, 384, dtype=np.float32)[1])
    res = store.topic(ds, "legged robots", k=10)
    assert res["mode"] == "semantic" and res["papers"][0]["id"] == "p2"
    assert {x["name"] for x in res["academia"]} == {"MIT", "Stanford University"}
    ds.emb = None                       # not indexed yet: keyword fallback
    res = store.topic(ds, "tactile hands", k=10)
    assert res["mode"] == "keyword" and [p["id"] for p in res["papers"]] == ["p3"]


@pytest.mark.asyncio
async def test_endpoints(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)
    from main import app
    from routers import conferences as router

    monkeypatch.setattr(router, "library_titles", lambda: {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cat = (await client.get("/conferences/catalog")).json()
        row = next(c for c in cat["conferences"] if c["key"] == "corl2025")
        assert row["state"] == "ready" and len(cat["areas"]) == len(areas.AREAS)
        ov = (await client.get("/conferences/CoRL 2025/overview")).json()
        assert ov["papers"] == 3 and ov["top_industry"][0]["name"] == "NVIDIA"
        inst = (await client.get("/conferences/corl2025/institutions", params={"sector": "A"})).json()
        assert inst["total"] == 2
        assert (await client.get("/conferences/corl2025/institutions/nvidia")).json()["papers"] == 1
        assert (await client.get("/conferences/corl2025/papers/p1")).json()["author_list"][1]["institutions"] == ["NVIDIA"]
        assert (await client.get("/conferences/icml2023/overview")).status_code == 409   # known, not loaded
        assert (await client.get("/conferences/nosuch/overview")).status_code == 404


def test_hong_kong_universities_stay_apart():
    assert institutions.split_and_normalise("City University of Hong Kong") == [("City University of Hong Kong", "A")]
    assert institutions.split_and_normalise("The University of Hong Kong") == [("University of Hong Kong", "A")]
    assert institutions.split_and_normalise("The Chinese University of Hong Kong") == [("CUHK", "A")]


# ── search across conferences ─────────────────────────────────────────────────

def _e(i: int, sign: float = 1.0) -> np.ndarray:
    v = np.zeros(384, dtype=np.float32)
    v[i] = sign
    return v


def _write_conf(tmp_path, key, papers, insts, emb, temb=None):
    ed = catalog.get_edition(key)
    ds = {
        "key": key, "name": ed.name, "series": ed.series.name, "slug": ed.series.slug, "field": ed.series.field,
        "year": ed.year, "source": ed.source, "source_url": "https://example.org", "fetched_at": "2026-10-25T00:00:00+00:00",
        "partial": False, "expected": len(papers), "areas_ready": True, "insts": insts, "papers": papers,
    }
    store._finalise(ds)
    (tmp_path / key).mkdir()
    (tmp_path / key / "dataset.json").write_text(json.dumps(ds))
    np.save(tmp_path / key / "emb.npy", np.stack(emb).astype(np.float16))
    if temb is not None:
        np.save(tmp_path / key / "emb_title.npy", np.stack(temb).astype(np.float16))
    store._set_status(key, "ready", papers=len(papers), institutions=len(insts))


def _paper(pid, title, authors, ai, abstract="", area=0):
    return {"id": pid, "t": title, "a": abstract, "au": authors, "ai": ai,
            "i": sorted({i for ids in ai for i in ids}), "ar": area, "d": "Poster", "tr": "", "s": "",
            "u": f"https://x/{pid}", "f": "", "nt": "", "kw": []}


@pytest.fixture()
def three_confs(tmp_path, monkeypatch):
    """NeurIPS 2025 (abstracts, title vectors built), NeurIPS 2026 (titles only, so its
    vectors are title vectors) and ICLR 2026 (abstracts, title vectors not built yet).
    Query vector e0: a1 and b1 score 1, fillers -0.01 ... -0.12, everything else -1."""
    from services.conferences import search

    monkeypatch.setattr(store, "_data_dir", tmp_path)
    store._cache.clear()
    with store._status_lock:
        store._status.clear()
    search._index = None
    queued: list[str] = []
    monkeypatch.setattr(store, "request_title_embeddings", lambda key: queued.append(key))
    insts25 = [{"n": "University of Oxford", "s": "A"}, {"n": "Google", "s": "I"},
               {"n": "Tsinghua University", "s": "A"}, {"n": "Stanford University", "s": "A"}]
    p25 = [
        _paper("a1", "Protein structure diffusion", ["Charlotte Deane", "Alice Smith"], [[0], [1]], "abs"),
        _paper("a2", "Video generation at scale", ["Bob Lee"], [[1]], "abs", area=9),
        _paper("a3", "Graph neural networks", ["Wei Wang"], [[2]], "abs"),
        _paper("a4", "Another graph paper", ["Wei Wang"], [[3]], "abs"),
    ]
    v25 = [_e(0), _e(0, -1), _e(0, -1), _e(0, -1)]
    _write_conf(tmp_path, "neurips2025", p25, insts25, v25, temb=v25)
    insts26 = [{"n": "University of Oxford", "s": "A"}, {"n": "Google", "s": "I"}]
    p26 = [
        _paper("b1", "Diffusion models for protein design", ["Charlotte Deane", "Alice Smith"], [[0], []]),
        _paper("b2", "Video diffusion", ["Bob Lee"], [[1]], area=9),
    ] + [_paper(f"f{n}", f"Filler title number {n}", [], []) for n in range(12)]
    v26 = [_e(0), _e(0, -1)]
    for n in range(12):
        v = _e(5) - 0.01 * (n + 1) * _e(0)
        v26.append(v / np.linalg.norm(v))
    _write_conf(tmp_path, "neurips2026", p26, insts26, v26)
    _write_conf(tmp_path, "iclr2026", [_paper("c1", "Protein folding", ["Zed"], [[]], "abs")], [], [_e(0)])
    from services.conferences import embedder

    monkeypatch.setattr(embedder, "conference_embed_query", lambda text: _e(0))
    return queued


def test_title_embedding_needed_and_backfilled(three_confs, tmp_path, monkeypatch):
    from services.conferences import embedder

    assert store.needs_title_embedding([{"t": "x", "a": "abstract"}])
    assert not store.needs_title_embedding([{"t": "x", "a": "", "kw": []}])
    assert store.load("neurips2026").temb is store.load("neurips2026").emb      # titles only: same vectors
    assert store.load("iclr2026").temb is None
    monkeypatch.setattr(embedder, "conference_embed", lambda texts, max_length=256: np.stack([_e(1)] * len(texts)))
    assert store.build_title_embeddings("iclr2026") is True
    assert store.load("iclr2026").temb is not None
    assert store.build_title_embeddings("iclr2026") is False                      # already there


def test_search_papers_by_title(three_confs):
    from services.conferences import search

    res = search.search_papers("protein structure diffusion", limit=5)
    assert res["title"][0]["id"] == "a1" and res["title"][0]["title_match"] == "exact"
    assert res["title"][0]["conf_key"] == "neurips2025" and res["title"][0]["conf_year"] == 2025
    assert "a1" not in {p["id"] for p in res["semantic"]}                          # not listed twice
    assert res["title"][1]["id"] == "b1" and res["title"][1]["title_match"] == "most words"
    # Closest by meaning among the rest: c1, through ICLR's title + abstract vectors (its
    # title vectors are not built yet, which paper search tolerates and topic counts do not).
    assert res["semantic"][0]["id"] == "c1"
    typo = search.search_papers("difusion", limit=10, semantic=False)
    assert {p["id"] for p in typo["title"]} == {"a1", "b1", "b2"}
    pre = search.search_papers("video gen", limit=5, semantic=False)
    assert pre["title"][0]["id"] == "a2" and pre["title"][0]["title_match"] == "prefix"
    only26 = search.search_papers("diffusion", year_min=2026, semantic=False)
    assert {p["conf_key"] for p in only26["title"]} == {"neurips2026"}
    assert {c["key"] for c in search.search_papers("x", series="iclr")["conferences"]} == {"iclr2026"}


def test_search_authors(three_confs):
    from services.conferences import search

    for q in ("deane", "Charlotte Deane", "Deane, Charlotte", "c deane", "Charlote Deane", "charlotte dea"):
        res = search.search_authors(q)
        assert [a["name"] for a in res["authors"]] == ["Charlotte Deane"], q
    a = search.search_authors("Charlotte Deane")["authors"][0]
    assert a["score"] == 100 and a["papers"] == 2 and a["conference_count"] == 2 and a["coauthors"] == 1
    assert a["institutions"] == [{"name": "University of Oxford", "sector": "A", "papers": 2}]
    assert [c["key"] for c in a["conferences"]] == ["neurips2026", "neurips2025"]     # newest first
    assert a["conferences"][0]["papers_by_author"][0]["author_institutions"] == ["University of Oxford"]
    assert a["identities"] == []                                                     # one person
    wang = search.search_authors("wei wang")["authors"][0]
    assert wang["papers"] == 2 and len(wang["identities"]) == 2                     # Tsinghua vs Stanford
    assert search.search_authors("nobody here")["authors"] == []
    assert search.search_authors("deane", year_max=2025)["authors"][0]["papers"] == 1


def test_search_suggests_a_kind(three_confs):
    from services.conferences import search

    assert search.search("Charlotte Deane")["suggested"] == "author"
    assert search.search("video diffusion")["suggested"] == "paper"
    assert search.search(" ".join(["word"] * 20))["suggested"] == "topic"


def test_topic_across_conferences(three_confs):
    from services.conferences import search

    res = search.topic("protein diffusion", k=10)
    assert res["k"] == 10 and res["total"] == 18                    # ICLR 2026 skipped: no title vectors
    assert [s["key"] for s in res["skipped"]] == ["iclr2026"] and three_confs == ["iclr2026"]
    by = {c["key"]: c for c in res["conferences"]}
    assert by["neurips2025"]["count"] == 1 and by["neurips2025"]["per_1k"] == 250.0
    assert by["neurips2026"]["count"] == 9 and by["neurips2026"]["per_1k"] == round(9000 / 14, 2)
    assert res["trend"][0]["series"] == "NeurIPS" and [p["year"] for p in res["trend"][0]["points"]] == [2025, 2026]
    assert {p["id"] for p in res["papers"][:2]} == {"a1", "b1"}
    oxford = res["academia"][0]
    assert oxford["name"] == "University of Oxford" and oxford["count"] == 2      # merged over both years
    assert {c["key"]: c["count"] for c in oxford["conferences"]} == {"neurips2025": 1, "neurips2026": 1}
    assert oxford["papers"] == 2 and oxford["of_own"] == 1.0
    assert [x["name"] for x in res["industry"]] == ["Google"]
    assert res["with_institution"] == 2
    only = search.topic("protein diffusion", k=10, series="neurips", year_min=2026)
    assert [c["key"] for c in only["conferences"]] == ["neurips2026"] and only["trend"] == []


@pytest.mark.asyncio
async def test_search_endpoints(three_confs, monkeypatch):
    from main import app
    from routers import conferences as router

    monkeypatch.setattr(router, "library_titles", lambda: {"proteinstructurediffusion": "lib-9"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = (await client.get("/conferences/search/query", params={"q": "deane"})).json()
        assert r["suggested"] == "author" and r["authors"]["authors"][0]["papers"] == 2
        assert r["authors"]["authors"][0]["conferences"][1]["papers_by_author"][0]["library_id"] == "lib-9"
        r = (await client.get("/conferences/search/query", params={"q": "protein", "kind": "paper"})).json()
        assert "authors" not in r and {p["id"] for p in r["papers"]["title"]} == {"a1", "b1", "c1"}
        assert (await client.get("/conferences/search/query", params={"q": "x", "kind": "nope"})).status_code == 422
        t = await client.post("/conferences/search/topic", json={"query": "protein", "k": 10})
        assert t.status_code == 200 and t.json()["k"] == 10
        assert (await client.post("/conferences/search/topic", json={"query": "  "})).status_code == 422


@pytest.mark.parametrize("raw, name", [
    ("ENS", "ENS Paris"), ("Ecole Normale Supérieure de Paris", "ENS Paris"), ("ENS Lyon", "ENS Lyon"),
    ("U. Montreal", "Université de Montréal"), ("Technical University Munich", "TU Munich"),
])
def test_more_aliases(raw, name):
    assert institutions.split_and_normalise(raw) == [(name, "A")]


def test_search_ignores_case(three_confs, monkeypatch):
    """Caps and small letters are irrelevant: the same results for papers, authors and topics."""
    from services.conferences import embedder, search

    seen: list[str] = []

    def embed(text):
        seen.append(text)
        return _e(0)

    monkeypatch.setattr(embedder, "conference_embed_query", embed)

    def strip(res):
        """Drop the echoed query and the timing, at every level."""
        if isinstance(res, dict):
            return {k: strip(v) for k, v in res.items() if k not in ("query", "ms")}
        if isinstance(res, list):
            return [strip(v) for v in res]
        return res

    variants = ["protein structure diffusion", "PROTEIN STRUCTURE DIFFUSION", "Protein Structure Diffusion"]
    papers = [strip(search.search_papers(v)) for v in variants]
    assert papers[0] == papers[1] == papers[2] and papers[0]["title"]
    names = ["charlotte deane", "CHARLOTTE DEANE", "Charlotte Deane", "cHARLOTTE dEANE"]
    authors = [strip(search.search_authors(v)) for v in names]
    assert all(a == authors[0] for a in authors) and authors[0]["total"] == 1
    topics = [strip(search.topic(v, k=10)) for v in variants]
    assert topics[0] == topics[1] == topics[2]
    assert set(seen) == {"protein structure diffusion"}            # the model only ever sees lower case
    both = [strip(search.search(v)) for v in ("Charlotte Deane", "charlotte deane")]
    assert both[0] == both[1]


def test_search_highlight_and_correction(three_confs):
    from services.conferences import search

    res = search.search_papers("difusion vid", semantic=False)
    assert "diffusion" in res["highlight"]["words"] and res["highlight"]["prefixes"] == ["vid"]
    assert res["corrected"] == "diffusion vid"
    assert search.search_papers("diffusion")["corrected"] is None
    a = search.search_authors("Charlote Deane")
    assert a["corrected"] == "Charlotte Deane" and "charlotte" in a["highlight"]["words"]
    assert search.search_authors("charlotte deane")["corrected"] is None
