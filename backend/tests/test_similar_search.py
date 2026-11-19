"""services/similar_search.py: ranking, scope, visibility, stubs, over-fetch, availability, validation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from services import similar_search as ss
from services import vectorstore
from services.feed import ranking
from services.feed.store import Candidate, get_store, reset
from tests.feed_helpers import topic_vec
from tests.similar_helpers import FakeLibraryDriver, patch_embedder, query_vec

TEXT = "A title about topic one.\n" + "A paragraph of an abstract that is long enough to count. " * 4
NOW = datetime.now(timezone.utc)


@pytest.fixture
def drv():
    d = FakeLibraryDriver()
    d.members = {"alpha": {"alice"}, "beta": {"bob"}}
    return d


@pytest.fixture
def feed(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_FEED", "true")
    monkeypatch.setenv("PAPER_FEED_DIR", str(tmp_path / "feed"))
    reset()
    ranking.forget()
    yield get_store()
    ranking.forget()
    reset()


def put(st, n: int, topic: int, *, days_ago: float = 1.0, doi=None, title=None, abstract="Candidate abstract.", source="arxiv"):
    ext = f"2611.{n:05d}" if source == "arxiv" else f"10.0000/b{n}"
    c = Candidate(id=f"{source}:{ext}", source=source, ext_id=ext, title=title or f"Candidate {n} topic-{topic}",
                  abstract=abstract, published=(NOW - timedelta(days=days_ago)).isoformat(timespec="seconds"),
                  categories=["cs.LG"], doi=doi, authors=["Bo Sample"], url=f"https://example.invalid/{n}")
    st.upsert_candidates([c])
    st.set_embeddings({c.id: topic_vec(topic, c.id)})
    return c.id


def search(drv, **kw):
    kw.setdefault("k", 5)
    return ss.search_by_text("alice", TEXT, driver=drv, **kw)


# ── ranking ───────────────────────────────────────────────────────────────────

def test_hits_are_ranked_by_cosine_and_come_from_the_nearest_cluster(drv, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    for t in range(3):
        for i in range(6):
            drv.add(f"t{t}-{i}", t)
    res = search(drv, k=6, scope="library")
    assert res["available"] is True and res["total"] == 6 and res["mode"] == "document" and res["scope"] == "library"
    scores = [h["score"] for h in res["hits"]]
    assert scores == sorted(scores, reverse=True)
    assert all(h["id"].startswith("t1-") for h in res["hits"])
    q = query_vec(1)
    for h in res["hits"]:
        assert h["score"] == pytest.approx(float(q @ topic_vec(1, h["id"])), abs=1e-4)
    # a different topic ranks a different cluster first
    patch_embedder(monkeypatch, topic=2)
    assert search(drv, k=3, scope="library")["hits"][0]["id"].startswith("t2-")


def test_a_hit_has_the_fields_the_page_and_the_tools_need(drv, monkeypatch):
    patch_embedder(monkeypatch)
    drv.add("p1", 1, title="Sparse attention", abstract="x" * 500, authors=("Ada Example", "Bo Sample"), year=2023,
            doi="10.0000/x")
    h = search(drv, scope="library", k=1)["hits"][0]
    assert h["source"] == "library" and h["id"] == "p1" and h["title"] == "Sparse attention"
    assert h["authors"] == ["Ada Example", "Bo Sample"] and h["year"] == 2023 and h["venue"] == "Synthetic Venue"
    assert h["doi"] == "10.0000/x" and h["url"].endswith("/paper/p1")
    assert h["in_library"] is True and h["library_paper_id"] == "p1" and h["my_label"] is None
    assert h["snippet"] == "x" * 300 + "…" and "abstract" not in h
    full = search(drv, scope="library", k=1, full_text=True)["hits"][0]
    assert full["abstract"] == "x" * 500


def test_the_summary_stands_in_for_a_missing_abstract(drv, monkeypatch):
    patch_embedder(monkeypatch)
    drv.add("p1", 1, abstract="", summary="Summary text of the paper.")
    assert search(drv, scope="library", k=1)["hits"][0]["snippet"] == "Summary text of the paper."


def test_min_score_cuts_the_list(drv, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    for i in range(4):
        drv.add(f"near{i}", 1)
        drv.add(f"far{i}", 5)
    res = search(drv, scope="library", k=10, min_score=0.5)
    assert {h["id"][:4] for h in res["hits"]} == {"near"} and res["total"] == 4
    assert search(drv, scope="library", k=10, min_score=0.999)["hits"] == []
    assert search(drv, scope="library", k=10, min_score=-1.0)["total"] == 8


# ── scope ─────────────────────────────────────────────────────────────────────

def test_feed_scope_is_refused_when_the_feed_is_off_and_both_means_library(drv, monkeypatch, tmp_path):
    monkeypatch.delenv("PAPER_FEED", raising=False)
    monkeypatch.setenv("PAPER_FEED_DIR", str(tmp_path / "never-created"))
    patch_embedder(monkeypatch)
    drv.add("p1", 1)
    with pytest.raises(ss.FeedDisabled):
        search(drv, scope="feed")
    res = search(drv, scope="both")
    assert res["available"] and res["scope"] == "library" and [h["id"] for h in res["hits"]] == ["p1"]
    assert not (tmp_path / "never-created").exists()                     # the feed was never touched
    assert vectorstore.get_store("feed", create=False) is None


def test_both_merges_library_and_feed_by_score(drv, feed, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    for i in range(3):
        drv.add(f"lib{i}", 1)
        drv.add(f"other{i}", 4)
    for i in range(3):
        put(feed, i, 1)
        put(feed, 10 + i, 6)
    res = search(drv, scope="both", k=6)
    assert res["scope"] == "both" and res["total"] == 6
    assert {h["source"] for h in res["hits"]} == {"library", "feed"}
    assert [h["score"] for h in res["hits"]] == sorted((h["score"] for h in res["hits"]), reverse=True)
    assert all(h["id"].startswith("lib") or "arxiv:2611.0000" in h["id"] for h in res["hits"])
    only_feed = search(drv, scope="feed", k=5, min_score=-1.0)
    assert {h["source"] for h in only_feed["hits"]} == {"feed"} and len(only_feed["hits"]) == 5
    only_lib = search(drv, scope="library", k=5)
    assert {h["source"] for h in only_lib["hits"]} == {"library"}
    f = next(h for h in res["hits"] if h["source"] == "feed")
    assert f["url"].startswith("https://example.invalid/") and f["feed_source"] == "arxiv" and f["year"] == NOW.year
    assert f["authors"] == ["Bo Sample"] and f["snippet"] == "Candidate abstract." and f["categories"] == ["cs.LG"]


def test_since_limits_feed_by_publication_date_and_library_by_year(drv, feed, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    drv.add("old", 1, year=2019)
    drv.add("new", 1, year=2026)
    drv.add("undated", 1, year=None)
    old = put(feed, 1, 1, days_ago=40)
    new = put(feed, 2, 1, days_ago=2)
    since = (NOW - timedelta(days=10)).date().isoformat()
    res = search(drv, scope="both", k=10, since=since)
    ids = {h["id"] for h in res["hits"]}
    assert ids == {"new", new}
    assert {h["id"] for h in search(drv, scope="both", k=10)["hits"]} == {"old", "new", "undated", old, new}
    assert {h["id"] for h in search(drv, scope="both", k=10, since="2026-01-01T00:00:00Z")["hits"]} >= {"new", new}


# ── visibility ────────────────────────────────────────────────────────────────

def test_two_users_see_only_their_papers(drv, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    drv.add("shared", 1)
    drv.add("alice-only", 1, project="alpha")
    drv.add("bob-only", 1, project="beta")
    seen = {u: {h["id"] for h in ss.search_by_text(u, TEXT, k=10, scope="library", driver=drv)["hits"]}
            for u in ("alice", "bob", "carol")}
    assert seen == {"alice": {"shared", "alice-only"}, "bob": {"shared", "bob-only"}, "carol": {"shared"}}
    for q, params in drv.queries:                                          # the app's clause, bound to the caller
        if "p.id IN $ids" in q:
            assert "IN_PROJECT" in q and "$vis_user" in q and params["vis_user"] in ("alice", "bob", "carol")


def test_over_fetch_keeps_k_results_after_the_visibility_filter(drv, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    for i in range(60):                       # the 60 nearest papers are in bob's project: invisible to alice
        drv.add(f"hidden{i}", 1, project="beta")
    for i in range(30):
        drv.add(f"open{i}", 2)               # visible, but farther away
    res = ss.search_by_text("alice", TEXT, k=10, scope="library", min_score=-1.0, driver=drv)
    assert res["total"] == 10 and all(h["id"].startswith("open") for h in res["hits"])
    assert max(len(p["ids"]) for q, p in drv.queries if "ids" in p) > 50 + 10      # it read past 5 x k
    # nothing visible at all: terminates, empty
    for pid in list(drv.papers):
        drv.papers[pid]["project"] = "beta"
    assert ss.search_by_text("alice", TEXT, k=5, scope="library", min_score=-1.0, driver=drv)["hits"] == []


def test_feed_hits_never_carry_another_users_label_or_library_match(drv, feed, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    drv.add("secret", 1, title="A very particular title of the hidden paper", doi="10.0000/hidden", project="beta")
    mine = drv.add("mine", 1, title="Another particular title of my paper", doi="10.0000/mine", project="alpha")
    a = put(feed, 1, 1, doi="10.0000/hidden", title="A very particular title of the hidden paper")
    b = put(feed, 2, 1, doi="10.0000/mine", title="Another particular title of my paper")
    c = put(feed, 3, 1, title="Something not in any library")
    feed.set_label("bob", a, 1)
    feed.set_label("alice", c, -1)
    feed.set_label("alice", b, 1)
    res = {h["id"]: h for h in search(drv, scope="feed", k=10)["hits"]}
    assert res[a]["in_library"] is False and res[a]["library_paper_id"] is None and res[a]["my_label"] is None
    assert res[b]["in_library"] is True and res[b]["library_paper_id"] == mine and res[b]["my_label"] == 1
    assert res[c]["in_library"] is False and res[c]["my_label"] == -1
    bob = {h["id"]: h for h in ss.search_by_text("bob", TEXT, k=10, scope="feed", driver=drv)["hits"]}
    assert bob[a]["in_library"] is True and bob[a]["library_paper_id"] == "secret" and bob[a]["my_label"] == 1
    assert bob[b]["in_library"] is False and bob[b]["my_label"] is None and bob[c]["my_label"] is None


def test_title_match_flags_a_feed_paper_that_is_already_in_the_library(drv, feed, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    drv.add("lib", 1, title="Diffusion guidance on synthetic graphs of many kinds")
    cid = put(feed, 1, 1, title="Diffusion guidance on synthetic graphs of many kinds")
    hit = next(h for h in search(drv, scope="feed")["hits"] if h["id"] == cid)
    assert hit["in_library"] and hit["library_paper_id"] == "lib"


# ── stubs ─────────────────────────────────────────────────────────────────────

def test_reference_stubs_are_left_out_unless_asked_for(drv, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    drv.add("real", 1)
    drv.add("stub", 1, stub=True)
    assert [h["id"] for h in search(drv, scope="library")["hits"]] == ["real"]
    with_stubs = search(drv, scope="library", include_stubs=True)["hits"]
    assert {h["id"] for h in with_stubs} == {"real", "stub"}
    assert {h["id"]: h["reference_stub"] for h in with_stubs} == {"real": False, "stub": True}


# ── availability ──────────────────────────────────────────────────────────────

def test_no_index_yet(drv, monkeypatch):
    patch_embedder(monkeypatch)
    res = search(drv, scope="library")
    assert res["available"] is False and "not been built" in res["reason"] and res["hits"] == [] and res["total"] == 0


def test_an_empty_index_is_still_building(drv, monkeypatch):
    patch_embedder(monkeypatch)
    vectorstore.get_store("library")
    res = search(drv, scope="library")
    assert res["available"] is False and "being built" in res["reason"]


def test_a_stale_index_is_reported_not_raised(drv, monkeypatch):
    patch_embedder(monkeypatch)
    drv.add("p1", 1)
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    res = search(drv, scope="library")
    assert res["available"] is False and "model was changed" in res["reason"]


def test_semantic_search_switched_off(drv, monkeypatch):
    patch_embedder(monkeypatch)
    drv.add("p1", 1)
    monkeypatch.setenv("LIBRARY_SEMANTIC", "false")
    res = search(drv, scope="library")
    assert res["available"] is False and "switched off" in res["reason"]


def test_embedding_model_not_loaded_in_the_backend(drv, monkeypatch):
    from services.conferences import embedder
    drv.add("p1", 1)
    monkeypatch.setattr(embedder, "ready", lambda: False)
    monkeypatch.setattr(embedder, "remote_url", lambda: "")
    res = search(drv, scope="library")
    assert res["available"] is False and "still loading" in res["reason"]


def test_a_failing_embedder_is_an_answer_not_an_exception(drv, monkeypatch):
    from services.conferences import embedder
    drv.add("p1", 1)
    monkeypatch.setattr(embedder, "ready", lambda: True)

    def boom(text):
        raise OSError("no such model")
    monkeypatch.setattr(embedder, "embed_search_text", boom)
    res = search(drv, scope="library")
    assert res["available"] is False and "could not be embedded" in res["reason"] and "OSError" in res["reason"]


def test_one_namespace_down_the_other_answers(drv, feed, monkeypatch):
    patch_embedder(monkeypatch, topic=1)
    put(feed, 1, 1)
    res = search(drv, scope="both")                       # no library index at all
    assert res["available"] is True and {h["source"] for h in res["hits"]} == {"feed"}
    assert "library" in res["skipped"] and "not been built" in res["skipped"]["library"]
    drv.add("p1", 1)
    feed_vs = vectorstore.get_store("feed")
    feed_vs.delete(feed_vs.ids())
    res = search(drv, scope="both")
    assert res["available"] and {h["source"] for h in res["hits"]} == {"library"} and "feed" in res["skipped"]
    only_feed = search(drv, scope="feed")
    assert only_feed["available"] is False and "no feed papers" in only_feed["reason"]


def test_a_stale_feed_namespace(drv, feed, monkeypatch):
    patch_embedder(monkeypatch)
    put(feed, 1, 1)
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    res = search(drv, scope="feed")
    assert res["available"] is False and "model was changed" in res["reason"]


# ── validation ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw, fragment", [
    ({"text": "too short"}, "at least 20"),
    ({"text": "   " + "x" * 10 + "   "}, "at least 20"),
    ({"text": "x" * 20001}, "at most 20000"),
    ({"k": 0}, "k must"), ({"k": 51}, "k must"), ({"k": True}, "k must"),
    ({"scope": "everything"}, "scope"),
    ({"since": "last week"}, "since"), ({"since": "2026-13-45"}, "since"),
    ({"min_score": 1.5}, "min_score"),
])
def test_bad_arguments_are_rejected(drv, monkeypatch, kw, fragment):
    patch_embedder(monkeypatch)
    args = {"text": TEXT, "k": 5, "scope": "library", **kw}
    with pytest.raises(ss.InvalidRequest, match=fragment):
        ss.search_by_text("alice", args.pop("text"), driver=drv, **args)


def test_the_limits_themselves_are_accepted(drv, monkeypatch):
    patch_embedder(monkeypatch)
    drv.add("p1", 1)
    for text in ("x" * 20, "word " * 4000):
        assert ss.search_by_text("alice", text[:20000], k=50, scope="library", driver=drv)["available"]
    assert ss.search_by_text("alice", TEXT, k=1, scope="library", driver=drv)["total"] == 1


def test_the_text_is_embedded_once_stripped(drv, monkeypatch):
    calls: list = []
    patch_embedder(monkeypatch, calls=calls)
    drv.add("p1", 1)
    search(drv, scope="library")
    assert calls == [TEXT.strip()]


# ── more like this paper ──────────────────────────────────────────────────────

def test_paper_search_uses_the_stored_vector_and_leaves_the_paper_out(drv, monkeypatch):
    from services.conferences import embedder
    monkeypatch.setattr(embedder, "ready", lambda: False)             # no embedder needed: the vector is stored
    monkeypatch.setattr(embedder, "remote_url", lambda: "")
    for i in range(5):
        drv.add(f"a{i}", 1)
        drv.add(f"b{i}", 2)
    res = ss.search_by_paper("alice", "a0", k=4, scope="library", driver=drv)
    assert res["available"] and res["mode"] == "paper"
    assert "a0" not in [h["id"] for h in res["hits"]] and all(h["id"].startswith("a") for h in res["hits"])
    assert res["total"] == 4


def test_paper_search_embeds_a_paper_that_is_not_indexed_yet(drv, monkeypatch):
    calls: list = []
    patch_embedder(monkeypatch, topic=1, calls=calls)
    drv.add("indexed", 1)
    drv.add("new", 1, title="Brand new title", abstract="Brand new abstract.", vec=False)
    res = ss.search_by_paper("alice", "new", k=3, scope="library", driver=drv)
    assert [h["id"] for h in res["hits"]] == ["indexed"] and calls == ["Brand new title\nBrand new abstract."]


def test_paper_search_hides_papers_the_user_may_not_see(drv, monkeypatch):
    patch_embedder(monkeypatch)
    drv.add("secret", 1, project="beta")
    drv.add("open", 1)
    with pytest.raises(ss.PaperNotFound):
        ss.search_by_paper("alice", "secret", driver=drv)
    with pytest.raises(ss.PaperNotFound):
        ss.search_by_paper("alice", "does-not-exist", driver=drv)
    assert ss.search_by_paper("bob", "secret", scope="library", driver=drv)["available"]


def test_paper_search_drops_the_feed_copy_of_the_same_paper(drv, feed, monkeypatch):
    patch_embedder(monkeypatch)
    drv.add("lib", 1, title="Diffusion guidance on synthetic graphs of many kinds")
    drv.add("lib2", 1)
    copy = put(feed, 1, 1, title="Diffusion guidance on synthetic graphs of many kinds")
    other = put(feed, 2, 1)
    res = ss.search_by_paper("alice", "lib", k=10, scope="both", driver=drv)
    ids = {h["id"] for h in res["hits"]}
    assert copy not in ids and other in ids and "lib" not in ids and "lib2" in ids


# ── the feed helpers added for it ─────────────────────────────────────────────

def test_feed_store_by_ids(feed):
    a, b = put(feed, 1, 1), put(feed, 2, 2)
    got = feed.by_ids([a, "arxiv:none", b, a])
    assert set(got) == {a, b} and got[a].title.startswith("Candidate 1") and got[a].emb is None
    assert feed.by_ids([]) == {}
    many = [f"arxiv:x{i}" for i in range(1200)] + [a]               # more ids than one SQL statement takes
    assert set(feed.by_ids(many)) == {a}


def test_match_candidate_prefers_arxiv_id_then_doi_then_title():
    from services.feed import library as feed_library
    from services.library_lookup import build_index

    index = build_index([["p-arxiv", "10.48550/arXiv.2611.00001", "Unrelated title one"],
                         ["p-doi", "10.1234/abc", "Unrelated title two"],
                         ["p-title", None, "A long distinctive title for matching by its words"]])
    cand = lambda **kw: Candidate(id="x", source=kw.pop("source", "arxiv"), ext_id=kw.pop("ext_id", "9999.00000"),  # noqa: E731
                                  title=kw.pop("title", "No match"), published="2026-11-01", **kw)
    assert feed_library.match_candidate(index, cand(ext_id="2611.00001")) == "p-arxiv"
    assert feed_library.match_candidate(index, cand(source="biorxiv", ext_id="10.1234/abc", doi="10.1234/abc")) == "p-doi"
    assert feed_library.match_candidate(index, cand(title="A long distinctive title for matching by its words")) == "p-title"
    assert feed_library.match_candidate(index, cand()) is None
