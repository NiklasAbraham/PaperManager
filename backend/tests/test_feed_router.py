"""The /feed API with the feed on: ranking, labels, config, add, refresh. Synthetic data, no network, no database."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from routers import feed as feed_router
from services.auth import get_current_user
from services.feed import config, library, pipeline, ranking
from services.feed.store import Candidate, get_store, reset
from tests.feed_helpers import topic_vec

NOW = datetime.now(timezone.utc)


def when(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


class Lib:
    """The synthetic library the patched query layer serves."""

    def __init__(self):
        self.rows: list[dict] = []
        self.vecs: dict[str, np.ndarray] = {}
        self.single_user = True

    def add(self, pid: str, topic: int, *, title: str | None = None, doi=None, rating=None, bookmarked=False,
            status="unread", highlights=0, mine=False, created="2026-01-01T00:00:00") -> None:
        self.rows.append({"id": pid, "title": title or f"Library paper {pid} topic-{topic}", "doi": doi,
                          "rating": rating, "bookmarked": bookmarked, "status": status, "highlights": highlights,
                          "created_at": created, "mine": mine})
        self.vecs[pid] = topic_vec(topic, pid)


@pytest.fixture
def lib(monkeypatch):
    lib = Lib()

    def visible(driver, user):
        return [dict(r) for r in lib.rows], lib.single_user

    def snapshot():
        ids = list(lib.vecs)
        return ids, (np.vstack([lib.vecs[i] for i in ids]) if ids else np.zeros((0, 384), np.float32))

    monkeypatch.setattr(library, "visible_papers", visible)
    monkeypatch.setattr(library, "semantic_snapshot", snapshot)
    monkeypatch.setattr(feed_router, "get_driver", lambda: object())
    return lib


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_FEED", "true")
    monkeypatch.setenv("PAPER_FEED_DIR", str(tmp_path / "feed"))
    reset()
    ranking.forget()
    yield get_store()
    ranking.forget()
    reset()


@pytest.fixture
def app(st, lib):
    app = FastAPI()
    app.include_router(feed_router.router)
    app.state.user = "alice"
    app.dependency_overrides[get_current_user] = lambda: app.state.user
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def put(st, n: int, topic: int, *, hours=5.0, cats=("cs.LG",), source="arxiv", doi=None, title=None) -> str:
    ext = f"2611.{n:05d}" if source == "arxiv" else f"10.0000/b{n}"
    c = Candidate(id=f"{source}:{ext}", source=source, ext_id=ext, title=title or f"Candidate {n} topic-{topic}",
                  abstract="abstract", published=when(hours), categories=list(cats), doi=doi,
                  authors=["Ada Example"], url=f"https://example.invalid/{n}")
    st.upsert_candidates([c])
    st.set_embeddings({c.id: topic_vec(topic, c.id)})
    return c.id


async def choose(client, cats=("cs.LG",), **extra):
    r = await client.put("/feed/config", json={"sources": ["arxiv"], "arxiv_categories": list(cats), **extra})
    assert r.status_code == 200, r.text


# ── status and config ─────────────────────────────────────────────────────────

async def test_status_when_enabled(client, st):
    r = (await client.get("/feed/status")).json()
    assert r["enabled"] is True and r["state"] == "idle"
    assert r["candidates"] == 0 and r["last_refresh"] is None and r["next_refresh"] is None
    assert r["mode"] is None and r["quality"] is None and r["error"] is None
    rid = st.start_run()
    st.finish_run(rid, source="arxiv", fetched=3, new=3, embedded=3, error="arxiv cs.LG: HTTP 503")
    r = (await client.get("/feed/status")).json()
    assert r["last_refresh"] and r["next_refresh"] and r["error"] == "arxiv cs.LG: HTTP 503"


async def test_config_defaults_and_roundtrip(client):
    d = (await client.get("/feed/config")).json()
    assert d == {"sources": ["arxiv"], "arxiv_categories": [], "digest_days": 3, "min_score": 0.0}
    body = {"sources": ["arxiv", "biorxiv", "arxiv"], "arxiv_categories": ["cs.LG", "q-bio.BM", "cs.LG"],
            "digest_days": 7, "min_score": 0.4}
    r = await client.put("/feed/config", json=body)
    assert r.json() == {"sources": ["arxiv", "biorxiv"], "arxiv_categories": ["cs.LG", "q-bio.BM"],
                        "digest_days": 7, "min_score": 0.4}
    assert (await client.get("/feed/config")).json() == r.json()


@pytest.mark.parametrize("body", [
    {"arxiv_categories": ["CS.LG"]}, {"arxiv_categories": ["cs."]}, {"arxiv_categories": ["../etc"]},
    {"arxiv_categories": [f"cat{chr(97 + i % 26)}" for i in range(31)]}, {"arxiv_categories": ["x" * 41]},
    {"digest_days": 0}, {"digest_days": 15}, {"min_score": 1.5}, {"min_score": -0.1}, {"sources": ["pubmed"]},
])
async def test_config_validation(client, body):
    assert (await client.put("/feed/config", json=body)).status_code == 422


async def test_config_is_per_user(client, app):
    await choose(client, ["cs.LG"])
    app.state.user = "bob"
    assert (await client.get("/feed/config")).json()["arxiv_categories"] == []
    await choose(client, ["cs.CV"])
    app.state.user = "alice"
    assert (await client.get("/feed/config")).json()["arxiv_categories"] == ["cs.LG"]


# ── the digest ────────────────────────────────────────────────────────────────

async def test_empty_library_ranks_newest_first(client, st):
    ids = [put(st, i, i % 8, hours=h) for i, h in enumerate([30, 2, 10, 20], start=1)]
    await choose(client)
    r = (await client.get("/feed")).json()
    assert r["mode"] == "newest" and r["configured"] is True and r["total"] == 4
    assert [i["id"] for i in r["items"]] == [ids[1], ids[2], ids[3], ids[0]]
    item = r["items"][0]
    assert set(item) == {"id", "source", "title", "authors", "abstract", "published", "url", "doi", "categories",
                         "score", "neighbours", "in_library", "library_paper_id", "my_label"}
    assert item["score"] is None and item["neighbours"] == [] and item["in_library"] is False
    assert item["my_label"] is None and item["source"] == "arxiv" and item["authors"] == ["Ada Example"]


async def test_unconfigured_user_gets_an_empty_digest_and_the_flag(client, st):
    put(st, 1, 0)
    r = (await client.get("/feed")).json()
    assert r["configured"] is False and r["items"] == []


async def test_few_positives_rank_by_similarity_and_name_the_mode(client, st, lib):
    for i in range(3):
        lib.add(f"p{i}", 2, rating=5)
    near = [put(st, i, 2, hours=40 + i) for i in range(5)]      # old but on topic
    far = [put(st, 50 + i, 5, hours=1 + i) for i in range(5)]   # new but off topic
    await choose(client)
    r = (await client.get("/feed")).json()
    assert r["mode"] == "similarity" and r["positives"] == 3
    assert {i["id"] for i in r["items"][:5]} == set(near)
    assert min(i["score"] for i in r["items"][:5]) > max(i["score"] for i in r["items"][5:])


async def test_enough_positives_use_the_classifier(client, st, lib):
    for i in range(12):
        lib.add(f"p{i}", 3, rating=5)
    for i in range(6):
        lib.add(f"n{i}", 6, rating=1)
    on = [put(st, i, 3) for i in range(6)]
    off = [put(st, 50 + i, t) for i, t in enumerate([0, 1, 2, 4, 5, 7] * 3)]
    await choose(client)
    r = (await client.get("/feed")).json()
    assert r["mode"] == "classifier" and r["positives"] == 12 and r["quality"] is None
    assert {i["id"] for i in r["items"][:6]} == set(on)
    assert all(0 <= i["score"] <= 1 for i in r["items"])
    s = (await client.get("/feed/status")).json()
    assert s["mode"] == "classifier" and s["positives"] == 12


async def test_quality_auc_is_reported_from_thirty_positives(client, st, lib):
    for i in range(36):
        lib.add(f"p{i}", 3, rating=5, created=f"2026-02-{i % 28 + 1:02d}")
    for i in range(40):
        put(st, i, i % 8)
    await choose(client)
    r = (await client.get("/feed")).json()
    assert r["quality"]["positives"] == 36 and r["quality"]["held_out"] == 7 and r["quality"]["auc"] > 0.9
    assert (await client.get("/feed/status")).json()["quality"]["auc"] == r["quality"]["auc"]


async def test_model_is_cached_until_the_signals_change(client, st, lib, monkeypatch):
    for i in range(12):
        lib.add(f"p{i}", 3, rating=5)
    for i in range(10):
        put(st, i, i % 8)
    await choose(client)
    from services.feed import model
    fits = []
    real = model.fit_model
    monkeypatch.setattr(model, "fit_model", lambda ts, **k: (fits.append(1), real(ts, **k))[1])
    await client.get("/feed")
    await client.get("/feed")
    assert len(fits) == 1
    lib.add("p99", 3, rating=5)
    await client.get("/feed")
    assert len(fits) == 2


async def test_large_training_set_serves_similarity_and_fits_in_the_background(client, st, lib, monkeypatch):
    for i in range(12):
        lib.add(f"p{i}", 3, rating=5)
    for i in range(30):
        put(st, i, i % 8)
    await choose(client)
    from services.feed import model
    monkeypatch.setattr(model, "FIT_MAX_ROWS", 10)
    r = (await client.get("/feed")).json()
    assert r["mode"] == "similarity"
    for _ in range(100):                      # the background fit lands
        with ranking._lock:
            if "alice" in ranking._models:
                break
        import asyncio
        await asyncio.sleep(0.05)
    assert (await client.get("/feed")).json()["mode"] == "classifier"


async def test_other_users_ratings_do_not_leak_on_a_multi_user_instance(client, st, lib):
    lib.single_user = False
    for i in range(12):
        lib.add(f"x{i}", 3, rating=5, mine=False)             # somebody else's ratings
    for i in range(4):
        lib.add(f"m{i}", 1, rating=5, mine=True)
    for i in range(5):
        put(st, i, 3)
    await choose(client)
    r = (await client.get("/feed")).json()
    assert r["mode"] == "similarity" and r["positives"] == 4          # only the four of mine count


async def test_filters_categories_sources_days_min_score(client, st, lib):
    a = put(st, 1, 0, cats=("cs.LG",), hours=5)
    b = put(st, 2, 0, cats=("cs.CV", "cs.LG"), hours=5)
    c = put(st, 3, 0, cats=("cs.CV",), hours=5)
    d = put(st, 4, 0, cats=("cs.LG",), hours=24 * 6)
    e = put(st, 5, 0, source="biorxiv", cats=("neuroscience",), hours=5)
    await choose(client, ["cs.LG"], digest_days=3)
    ids = lambda r: {i["id"] for i in r["items"]}
    assert ids((await client.get("/feed")).json()) == {a, b}
    assert ids((await client.get("/feed?days=7")).json()) == {a, b, d}
    await client.put("/feed/config", json={"sources": ["arxiv", "biorxiv"], "arxiv_categories": ["cs.LG"], "digest_days": 3})
    assert ids((await client.get("/feed")).json()) == {a, b, e}
    assert ids((await client.get("/feed?source=biorxiv")).json()) == {e}
    assert ids((await client.get("/feed?source=arxiv")).json()) == {a, b}
    await client.put("/feed/config", json={"sources": ["biorxiv"], "arxiv_categories": [], "digest_days": 3})
    assert ids((await client.get("/feed")).json()) == {e}
    assert c not in ids((await client.get("/feed")).json())
    lib.add("p0", 0, rating=5)
    await choose(client, ["cs.LG"], min_score=0.99)
    assert (await client.get("/feed")).json()["total"] == 0


async def test_paging_and_param_validation(client, st):
    for i in range(7):
        put(st, i, 0, hours=1 + i)
    await choose(client)
    full = [i["id"] for i in (await client.get("/feed?limit=100")).json()["items"]]
    page = (await client.get("/feed?skip=2&limit=3")).json()
    assert page["total"] == 7 and [i["id"] for i in page["items"]] == full[2:5]
    for q in ("limit=0", "limit=101", "skip=-1", "days=0", "days=15", "source=pubmed"):
        assert (await client.get(f"/feed?{q}")).status_code == 422


async def test_papers_already_in_the_library_are_flagged_and_last(client, st, lib):
    by_arxiv = put(st, 1, 0, hours=1)
    by_doi = put(st, 2, 0, hours=2, doi="10.0000/journal.2")
    by_title = put(st, 3, 0, hours=3, title="A Distinctive Title About Sparse Things")
    fresh = put(st, 4, 0, hours=30)
    lib.add("L1", 5, doi="10.48550/arXiv.2611.00001")
    lib.add("L2", 5, doi="https://doi.org/10.0000/JOURNAL.2")
    lib.add("L3", 5, title="a distinctive title about sparse things!")
    await choose(client)
    items = (await client.get("/feed")).json()["items"]
    assert [i["id"] for i in items][0] == fresh and items[0]["in_library"] is False
    got = {i["id"]: (i["in_library"], i["library_paper_id"]) for i in items}
    assert got[by_arxiv] == (True, "L1") and got[by_doi] == (True, "L2") and got[by_title] == (True, "L3")


async def test_neighbours_are_the_three_nearest_visible_library_papers(client, st, lib):
    lib.add("a", 2, title="Alpha topic-2")
    lib.add("b", 2, title="Beta topic-2")
    lib.add("c", 2, title="Gamma topic-2")
    lib.add("d", 2, title="Delta topic-2")
    lib.add("z", 6, title="Zeta topic-6")
    lib.vecs["hidden"] = topic_vec(2, "cand")          # in the index but not visible to this user
    put(st, 1, 2)
    await choose(client)
    [item] = (await client.get("/feed")).json()["items"]
    n = item["neighbours"]
    assert len(n) == 3 and {x["paper_id"] for x in n} <= {"a", "b", "c", "d"}
    assert all(x["title"].endswith("topic-2") and 0.5 < x["similarity"] <= 1 for x in n)
    assert [x["similarity"] for x in n] == sorted((x["similarity"] for x in n), reverse=True)
    assert "hidden" not in {x["paper_id"] for x in n}


# ── labels ────────────────────────────────────────────────────────────────────

async def test_rate_and_dismiss_hide_the_item_and_are_per_user(client, st, app):
    a, b, c = put(st, 1, 0, hours=1), put(st, 2, 0, hours=2), put(st, 3, 0, hours=3)
    await choose(client)
    assert (await client.post(f"/feed/{a}/rate", json={"value": 1})).json() == {"id": a, "my_label": 1}
    assert (await client.post(f"/feed/{b}/dismiss")).json() == {"id": b, "my_label": 0}
    assert [i["id"] for i in (await client.get("/feed")).json()["items"]] == [c]
    shown = {i["id"]: i["my_label"] for i in (await client.get("/feed?include_rated=true")).json()["items"]}
    assert shown == {a: 1, b: 0, c: None}
    # another user sees everything and none of alice's labels
    app.state.user = "bob"
    await choose(client)
    items = (await client.get("/feed")).json()["items"]
    assert len(items) == 3 and all(i["my_label"] is None for i in items)
    await client.post(f"/feed/{a}/rate", json={"value": -1})
    assert st.labels("bob")[a][0] == -1 and st.labels("alice")[a][0] == 1
    # clearing
    app.state.user = "alice"
    assert (await client.delete(f"/feed/{a}/label")).json() == {"id": a, "my_label": None}
    assert len((await client.get("/feed")).json()["items"]) == 2


async def test_rate_switches_between_up_and_down(client, st):
    a = put(st, 1, 0)
    await client.post(f"/feed/{a}/rate", json={"value": 1})
    await client.post(f"/feed/{a}/rate", json={"value": -1})
    assert st.labels("alice")[a][0] == -1


async def test_ids_with_slashes_work_raw_and_url_encoded(client, st):
    bio = put(st, 7, 0, source="biorxiv", cats=("neuroscience",))
    assert bio == "biorxiv:10.0000/b7"
    for path in (f"/feed/{bio}/rate", "/feed/biorxiv:10.0000%2Fb7/rate"):
        r = await client.post(path, json={"value": 1})
        assert r.status_code == 200 and r.json()["id"] == bio
    old = Candidate(id="arxiv:hep-th/9901001", source="arxiv", ext_id="hep-th/9901001", title="Old", published=when(1))
    st.upsert_candidates([old])
    assert (await client.post("/feed/arxiv:hep-th%2F9901001/dismiss")).status_code == 200
    assert st.labels("alice")["arxiv:hep-th/9901001"][0] == 0


async def test_unknown_candidate_and_bad_value(client, st):
    assert (await client.post("/feed/arxiv:0000.00000/rate", json={"value": 1})).status_code == 404
    assert (await client.post("/feed/arxiv:0000.00000/dismiss")).status_code == 404
    assert (await client.post("/feed/arxiv:0000.00000/add", json={})).status_code == 404
    a = put(st, 1, 0)
    for body in ({"value": 0}, {"value": 2}, {}, {"value": "up"}):
        assert (await client.post(f"/feed/{a}/rate", json=body)).status_code == 422
    assert st.labels("alice") == {}


# ── add to the library ────────────────────────────────────────────────────────

async def test_add_ingests_by_url_links_the_project_and_counts_as_thumbs_up(client, st, monkeypatch):
    a = put(st, 1, 0)
    seen = {}

    def fake_ingest(body, x_user_name=None):
        seen.update(url=body.url, project=body.project_id, user=x_user_name)
        return {"id": "new-paper-id", "title": "x"}

    monkeypatch.setattr("routers.papers.ingest_from_url", fake_ingest)
    monkeypatch.setattr("db.queries.visibility.can_see_project", lambda driver, pid: pid == "proj-1")
    r = await client.post(f"/feed/{a}/add", json={"project_id": "proj-1"})
    assert r.status_code == 200 and r.json() == {"id": a, "my_label": 1, "paper_id": "new-paper-id"}
    assert seen == {"url": "https://example.invalid/1", "project": "proj-1", "user": "alice"}
    assert st.labels("alice")[a][0] == 1
    b = put(st, 2, 0)
    assert (await client.post(f"/feed/{b}/add", json={})).status_code == 200
    assert seen["project"] is None
    assert (await client.post(f"/feed/{put(st, 3, 0)}/add")).status_code == 200      # no body at all


async def test_add_refuses_a_project_the_user_cannot_see_and_keeps_the_label_clean(client, st, monkeypatch):
    a = put(st, 1, 0)
    monkeypatch.setattr("db.queries.visibility.can_see_project", lambda driver, pid: False)
    monkeypatch.setattr("routers.papers.ingest_from_url", lambda *a, **k: pytest.fail("must not ingest"))
    assert (await client.post(f"/feed/{a}/add", json={"project_id": "secret"})).status_code == 404
    assert st.labels("alice") == {}


async def test_add_failure_leaves_no_label(client, st, monkeypatch):
    a = put(st, 1, 0)

    def failing(body, x_user_name=None):
        raise HTTPException(status_code=422, detail="Could not resolve metadata")

    monkeypatch.setattr("routers.papers.ingest_from_url", failing)
    assert (await client.post(f"/feed/{a}/add", json={})).status_code == 422
    assert st.labels("alice") == {}


# ── refresh ───────────────────────────────────────────────────────────────────

async def test_refresh_starts_and_conflicts(client, monkeypatch):
    monkeypatch.setattr(feed_router, "_may_refresh", lambda user: True)
    started = []
    monkeypatch.setattr(pipeline, "start_refresh_async", lambda: (started.append(1), len(started) == 1)[1])
    assert (await client.post("/feed/refresh")).status_code == 202
    assert (await client.post("/feed/refresh")).status_code == 409


async def test_refresh_needs_admin_or_a_single_user(client, monkeypatch):
    from db.queries import users as users_q
    monkeypatch.setattr(feed_router, "get_driver", lambda: object())
    monkeypatch.setattr(pipeline, "start_refresh_async", lambda: True)
    monkeypatch.setattr(users_q, "is_user_admin", lambda d, name: name == "root")
    monkeypatch.setattr(users_q, "list_users", lambda d: [{"name": "alice"}, {"name": "bob"}])
    assert (await client.post("/feed/refresh")).status_code == 403
    monkeypatch.setattr(users_q, "list_users", lambda d: [{"name": "alice"}])
    assert (await client.post("/feed/refresh")).status_code == 202


async def test_status_shows_refreshing(client, monkeypatch):
    monkeypatch.setattr(pipeline, "is_running", lambda: True)
    assert (await client.get("/feed/status")).json()["state"] == "refreshing"
