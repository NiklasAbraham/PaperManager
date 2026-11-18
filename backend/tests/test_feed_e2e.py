"""End to end with PAPER_FEED=true: patched HTTP, fake embedder, refresh, digest, thumbs, better ranking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers import feed as feed_router
from services.auth import get_current_user
from services.conferences import embedder
from services.feed import library, pipeline, ranking, sources
from services.feed.store import get_store, reset
from tests.feed_helpers import Resp, atom_page, biorxiv_page, fake_embed, iso
from tests.test_feed_pipeline import FakeDriver

NOW = datetime.now(timezone.utc)
TOPICS = 8
PER_TOPIC = 25


def synthetic_arxiv() -> list[dict]:
    """200 papers over three days: 25 for each of eight topics, interleaved by time."""
    out = []
    for i in range(TOPICS * PER_TOPIC):
        topic = i % TOPICS
        out.append({"id": f"2611.{i:05d}", "title": f"Paper {i} about topic-{topic}",
                    "summary": f"Abstract {i} topic-{topic}.", "published": iso(NOW - timedelta(minutes=20 * i)),
                    "categories": ["cs.LG"]})
    return out


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_FEED", "true")
    monkeypatch.setenv("PAPER_FEED_DIR", str(tmp_path / "feed"))
    reset()
    ranking.forget()
    requested = []

    def fake_http(url, params=None, **_):
        requested.append((url, params))
        if "arxiv.org" in url:
            data = synthetic_arxiv()
            return Resp(text=atom_page(data[params["start"]:params["start"] + params["max_results"]]))
        return Resp(data=biorxiv_page([]))

    monkeypatch.setattr(sources, "_http_get", fake_http)
    monkeypatch.setattr(sources, "_sleep", lambda s: None)
    monkeypatch.setattr(embedder, "embed", fake_embed)
    monkeypatch.setattr(library, "visible_papers", lambda driver, user: ([], True))
    monkeypatch.setattr(library, "semantic_snapshot", lambda: ([], __import__("numpy").zeros((0, 384), "float32")))
    monkeypatch.setattr(feed_router, "get_driver", lambda: object())
    app = FastAPI()
    app.include_router(feed_router.router)
    app.dependency_overrides[get_current_user] = lambda: "alice"
    yield app, requested
    ranking.forget()
    reset()


def precision_at(items: list[dict], topic: int, k: int = 10) -> float:
    return sum(f"topic-{topic}" in i["title"] for i in items[:k]) / k


async def test_refresh_rank_rate_dismiss_and_ranking_improves(world):
    app, requested = world
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 1. nothing chosen: a refresh fetches nothing at all
        assert pipeline.refresh(driver=FakeDriver({}))["fetched"] == 0
        assert requested == []

        # 2. the user picks a category; the refresh now fetches it over the (patched) network and embeds it
        await c.put("/feed/config", json={"sources": ["arxiv"], "arxiv_categories": ["cs.LG"], "digest_days": 3})
        out = pipeline.refresh(driver=FakeDriver({}))
        assert out["fetched"] == 200 and out["new"] == 200 and out["embedded"] == 200 and out["error"] is None
        assert {p["search_query"] for _, p in requested} == {"cat:cs.LG"}
        s = (await c.get("/feed/status")).json()
        assert s["candidates"] == 200 and s["embedded"] == 200 and s["last_refresh"] and s["error"] is None

        # 3. no signals yet: newest first, so topics are mixed
        first = (await c.get("/feed?limit=100")).json()
        assert first["mode"] == "newest" and first["total"] == 200
        assert [i["published"] for i in first["items"]] == sorted((i["published"] for i in first["items"]), reverse=True)
        before = precision_at(first["items"], 2)
        assert before <= 0.2

        # 4. thumbs-up on five papers of topic 2 -> similarity ranking
        topic2 = [i for i in first["items"] if "topic-2" in i["title"]]
        for it in topic2[:5]:
            assert (await c.post(f"/feed/{it['id']}/rate", json={"value": 1})).status_code == 200
        sim = (await c.get("/feed?limit=100")).json()
        assert sim["mode"] == "similarity" and sim["positives"] == 5
        assert precision_at(sim["items"], 2) == 1.0
        assert all(it["id"] not in {x["id"] for x in sim["items"]} for it in topic2[:5])      # rated ones are hidden

        # 5. a dismissed paper is gone and counts as a negative
        gone = sim["items"][0]
        await c.post(f"/feed/{gone['id']}/dismiss")
        assert gone["id"] not in {x["id"] for x in (await c.get("/feed?limit=100")).json()["items"]}

        # 6. enough thumbs-up and the classifier takes over; its top ten are all on topic
        for it in [i for i in sim["items"] if "topic-2" in i["title"]][:6]:
            await c.post(f"/feed/{it['id']}/rate", json={"value": 1})
        cls = (await c.get("/feed?limit=100")).json()
        assert cls["mode"] == "classifier" and cls["positives"] == 11
        assert precision_at(cls["items"], 2) == 1.0
        assert precision_at(cls["items"], 2) > before
        top, rest = cls["items"][:8], cls["items"][8:]
        assert min(i["score"] for i in top) > max(i["score"] for i in rest)
        assert (await c.get("/feed/status")).json()["mode"] == "classifier"

        # 7. a thumbs-down on topic 5 pushes that topic to the bottom of the other ones
        for it in [i for i in cls["items"] if "topic-5" in i["title"]][:4]:
            await c.post(f"/feed/{it['id']}/rate", json={"value": -1})
        final = [i for skip in (0, 100) for i in (await c.get(f"/feed?limit=100&skip={skip}")).json()["items"]]
        order = [int(i["title"].rsplit("topic-", 1)[1]) for i in final]
        last_on_topic_2 = max(k for k, t in enumerate(order) if t == 2)
        first_on_topic_5 = min(k for k, t in enumerate(order) if t == 5)
        assert last_on_topic_2 < first_on_topic_5

        # 8. a second refresh finds nothing new
        again = pipeline.refresh(driver=FakeDriver({}))
        assert again["new"] == 0 and again["embedded"] == 0
