"""refresh(): what is fetched for whom, what is stored, how failures are isolated."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from services.feed import config, library, pipeline, sources
from services.feed.store import Candidate, get_store, reset
from tests.feed_helpers import fake_embed, topic_vec

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_FEED", "true")
    monkeypatch.setenv("PAPER_FEED_DIR", str(tmp_path / "feed"))
    reset()
    s = get_store()
    yield s
    reset()


class FakeDriver:
    def __init__(self, papers):
        self.papers = papers

    def session(self):
        outer = self

        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, query, **params):
                return [dict(id=pid, title=t, abstract=a, summary=None) for pid, (t, a) in outer.papers.items()]

        return S()


def arx(n: int, topic: int = 0, cats=("cs.LG",), when=NOW - timedelta(hours=3)) -> Candidate:
    ext = f"2611.{n:05d}"
    return Candidate(id=f"arxiv:{ext}", source="arxiv", ext_id=ext, title=f"Paper {n} topic-{topic}",
                     abstract="abstract", published=when.isoformat(), categories=list(cats),
                     url=f"https://arxiv.org/abs/{ext}")


def bio(n: int, server="biorxiv") -> Candidate:
    doi = f"10.0000/b{n}"
    return Candidate(id=f"{server}:{doi}", source=server, ext_id=doi, title=f"Preprint {n} topic-3",
                     published=NOW.isoformat(), doi=doi, url=f"https://example.invalid/{n}")


@pytest.fixture
def calls(monkeypatch):
    rec = {"arxiv": [], "biorxiv": []}
    data = {"arxiv": {"cs.LG": [arx(1), arx(2, 1)], "cs.CV": [arx(3, 2, cats=("cs.CV",))]}, "biorxiv": [bio(1)],
            "medrxiv": [bio(2, "medrxiv")]}

    def fetch_arxiv(cats, since, cap=None, get=None):
        rec["arxiv"].append((tuple(cats), since, cap))
        return list(data["arxiv"].get(cats[0], [])), None

    def fetch_biorxiv(server, since, until, cap=None, get=None):
        rec["biorxiv"].append((server, since, until))
        return list(data[server]), None

    monkeypatch.setattr(sources, "fetch_arxiv", fetch_arxiv)
    monkeypatch.setattr(sources, "fetch_biorxiv", fetch_biorxiv)
    rec["data"] = data
    return rec


def run(st, **kw):
    return pipeline.refresh(driver=kw.pop("driver", FakeDriver({})), embed=kw.pop("embed", fake_embed),
                            now=kw.pop("now", NOW), **kw)


def test_nothing_chosen_fetches_nothing(st, calls):
    out = run(st)
    assert out["fetched"] == 0 and out["error"] is None
    assert calls["arxiv"] == [] and calls["biorxiv"] == []
    assert st.counts() == {"candidates": 0, "embedded": 0}
    assert st.last_run()["finished_at"]


def test_plan_is_the_union_over_users():
    p = pipeline.plan({
        "a": config.FeedConfig(sources=["arxiv"], arxiv_categories=["cs.LG", "cs.CV"], digest_days=2),
        "b": config.FeedConfig(sources=["arxiv", "biorxiv"], arxiv_categories=["cs.LG", "stat.ML"], digest_days=7),
        "c": config.FeedConfig(sources=["biorxiv"], arxiv_categories=["math.CO"]),   # not on arXiv: ignored
        "d": config.FeedConfig(sources=["medrxiv"]),
    })
    assert p == {"arxiv": ["cs.CV", "cs.LG", "stat.ML"], "biorxiv": True, "medrxiv": True, "days": 7}


def test_refresh_fetches_union_stores_and_embeds(st, calls):
    st.set_config("alice", config.FeedConfig(arxiv_categories=["cs.LG"]))
    st.set_config("bob", config.FeedConfig(sources=["arxiv", "biorxiv"], arxiv_categories=["cs.CV"], digest_days=5))
    out = run(st)
    assert out == {"fetched": 4, "new": 4, "embedded": 4, "error": None}
    assert [c[0] for c in calls["arxiv"]] == [("cs.CV",), ("cs.LG",)]
    assert [b[0] for b in calls["biorxiv"]] == ["biorxiv"]
    assert st.counts() == {"candidates": 4, "embedded": 4}
    # first fetch reaches back as far as the longest digest window
    assert calls["arxiv"][0][1] == NOW - timedelta(days=5)
    # the embedding is by the text: the fake embedder reads the topic tag
    np.testing.assert_allclose(st.get("arxiv:2611.00003").emb, topic_vec(2, "Paper 3 topic-2\nabstract"))


def test_second_refresh_overlaps_by_a_day_and_does_not_duplicate(st, calls):
    st.set_config("alice", config.FeedConfig(arxiv_categories=["cs.LG"]))
    run(st)
    later = NOW + timedelta(hours=6)
    out = run(st, now=later)
    assert out["new"] == 0 and out["embedded"] == 0
    assert calls["arxiv"][1][1] == NOW - pipeline.OVERLAP
    assert st.counts()["candidates"] == 2


def test_new_category_later_reaches_back_by_the_digest_window(st, calls):
    st.set_config("alice", config.FeedConfig(arxiv_categories=["cs.LG"], digest_days=3))
    run(st)
    st.set_config("alice", config.FeedConfig(arxiv_categories=["cs.LG", "cs.CV"], digest_days=3))
    run(st, now=NOW + timedelta(hours=6))
    by_cat = {c[0][0]: c[1] for c in calls["arxiv"][-2:]}
    assert by_cat["cs.CV"] == NOW + timedelta(hours=6) - timedelta(days=3)
    assert by_cat["cs.LG"] == NOW - pipeline.OVERLAP


def test_a_failing_source_is_recorded_and_the_other_still_runs(st, calls, monkeypatch):
    st.set_config("alice", config.FeedConfig(sources=["arxiv", "biorxiv"], arxiv_categories=["cs.LG", "cs.CV"]))

    def broken(cats, since, cap=None, get=None):
        if cats == ["cs.LG"]:
            raise RuntimeError("kaput")
        return calls["data"]["arxiv"]["cs.CV"], None

    monkeypatch.setattr(sources, "fetch_arxiv", broken)
    out = run(st)
    assert "cs.LG" in out["error"] and "kaput" in out["error"]
    assert out["fetched"] == 2                                      # cs.CV and bioRxiv still came in
    assert st.get_since("arxiv:cs.LG") is None                      # not advanced: it will be retried
    assert st.get_since("arxiv:cs.CV") and st.get_since("biorxiv")
    assert st.last_run()["error"] == out["error"]


def test_error_text_from_a_source_is_kept_and_since_not_advanced(st, calls, monkeypatch):
    st.set_config("alice", config.FeedConfig(sources=["biorxiv"]))
    monkeypatch.setattr(sources, "fetch_biorxiv", lambda *a, **k: ([bio(9)], "biorxiv: HTTP 502"))
    out = run(st)
    assert out["error"] == "biorxiv: HTTP 502" and out["fetched"] == 1
    assert st.get_since("biorxiv") is None


def test_embedder_failure_is_recorded_and_retried_next_time(st, calls):
    st.set_config("alice", config.FeedConfig(arxiv_categories=["cs.LG"]))

    def broken(texts, **_):
        raise RuntimeError("model missing")

    out = run(st, embed=broken)
    assert "model missing" in out["error"] and st.counts() == {"candidates": 2, "embedded": 0}
    out = run(st, now=NOW + timedelta(hours=1))
    assert out["embedded"] == 2 and out["error"] is None


def test_refresh_never_runs_twice_at_once(st, calls):
    st.set_config("alice", config.FeedConfig(arxiv_categories=["cs.LG"]))
    gate, inside = threading.Event(), threading.Event()

    def slow_embed(texts, **kw):
        inside.set()
        gate.wait(5)
        return fake_embed(texts)

    t = threading.Thread(target=lambda: run(st, embed=slow_embed))
    t.start()
    assert inside.wait(5)
    assert pipeline.is_running() is True
    assert pipeline.refresh() == {"skipped": True}
    assert pipeline.start_refresh_async() is False
    gate.set()
    t.join(5)
    assert pipeline.is_running() is False


def test_refresh_purges_old_unrated_candidates(st, calls, monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
    st.upsert_candidates([Candidate(id="arxiv:old", source="arxiv", ext_id="old", title="Old", published="2026-01-01",
                                    fetched_at=old),
                          Candidate(id="arxiv:oldrated", source="arxiv", ext_id="oldrated", title="Old", published="2026-01-01",
                                    fetched_at=old)])
    st.set_label("alice", "arxiv:oldrated", 1)
    run(st)
    assert st.known_ids(["arxiv:old", "arxiv:oldrated"]) == {"arxiv:oldrated"}


def test_start_background_when_enabled_starts_one_daemon_thread(st, monkeypatch):
    started = []
    monkeypatch.setattr(pipeline, "_loop", lambda interval: started.append(interval))
    monkeypatch.setattr(pipeline, "_thread", None)
    monkeypatch.setenv("PAPER_FEED_INTERVAL", "900")
    pipeline.start_background()
    pipeline._thread.join(2)
    assert started == [900.0]
    assert pipeline._thread.daemon is True
    monkeypatch.setattr(pipeline, "_thread", None)


# ── library embeddings cache ──────────────────────────────────────────────────

def test_sync_missing_library_embeddings_skips_what_the_search_index_has(st, monkeypatch):
    drv = FakeDriver({"p1": ("A topic-1", "x"), "p2": ("B topic-2", "y"), "p3": ("C topic-3", "z")})
    monkeypatch.setattr(library, "semantic_snapshot", lambda: (["p1"], np.vstack([topic_vec(1, "p1")])))
    n = library.sync_missing_embeddings(drv, st, fake_embed)
    assert n == 2 and set(st.library_hashes()) == {"p2", "p3"}
    assert library.sync_missing_embeddings(drv, st, fake_embed) == 0              # cached
    drv.papers["p2"] = ("B topic-2 changed", "y")
    drv.papers.pop("p3")
    assert library.sync_missing_embeddings(drv, st, fake_embed) == 1
    assert set(st.library_hashes()) == {"p2"}


def test_vectors_merge_index_and_cache(st, monkeypatch):
    monkeypatch.setattr(library, "semantic_snapshot", lambda: (["p1", "p2"], np.vstack([topic_vec(1, "a"), topic_vec(2, "b")])))
    st.set_library_embeddings({"p2": ("h", topic_vec(5, "dup")), "p3": ("h", topic_vec(3, "c"))})
    ids, mat = library.vectors(st)
    assert ids == ["p1", "p2", "p3"] and mat.shape == (3, 384)
    np.testing.assert_allclose(mat[1], topic_vec(2, "b"))                          # the index wins
    ids, mat = library.vectors(st, {"p3"})
    assert ids == ["p3"] and mat.shape == (1, 384)
    assert library.vectors(st, set())[1].shape == (0, 384)
