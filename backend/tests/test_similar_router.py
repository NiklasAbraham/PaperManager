"""POST /search/similar and GET /search/similar/{paper_id}."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers import similar as similar_router
from services.auth import get_current_user
from tests.feed_helpers import topic_vec
from tests.similar_helpers import FakeLibraryDriver, patch_embedder

TEXT = "A title about topic one.\n" + "A paragraph of an abstract that is long enough to count. " * 3


@pytest.fixture
def drv(monkeypatch):
    d = FakeLibraryDriver()
    d.members = {"alpha": {"alice"}}
    monkeypatch.setattr(similar_router, "get_driver", lambda: d)
    patch_embedder(monkeypatch, topic=1)
    return d


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(similar_router.router)
    app.state.user = "alice"
    app.dependency_overrides[get_current_user] = lambda: app.state.user
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_post_returns_ranked_hits_with_abstracts(client, drv):
    for i in range(4):
        drv.add(f"a{i}", 1, abstract=f"Abstract {i}. " + "y" * 400)
        drv.add(f"b{i}", 3)
    r = await client.post("/search/similar", json={"text": TEXT, "k": 3, "scope": "library"})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and body["total"] == 3 and body["mode"] == "document" and body["scope"] == "library"
    assert [h["id"][0] for h in body["hits"]] == ["a", "a", "a"]
    h = body["hits"][0]
    assert set(h) >= {"source", "id", "title", "authors", "year", "url", "score", "snippet", "abstract",
                      "in_library", "library_paper_id", "my_label"}
    assert len(h["snippet"]) <= 301 and h["abstract"].startswith("Abstract") and len(h["abstract"]) > 300


async def test_post_defaults(client, drv):
    drv.add("a0", 1)
    r = await client.post("/search/similar", json={"text": TEXT})
    assert r.status_code == 200 and r.json()["scope"] == "library"        # the feed is off: both means library


@pytest.mark.parametrize("body", [
    {"text": "short"}, {"text": "   short   "}, {"text": "x" * 20001}, {"text": TEXT, "k": 0}, {"text": TEXT, "k": 51},
    {"text": TEXT, "scope": "nowhere"}, {"text": TEXT, "since": "yesterday"}, {"text": TEXT, "min_score": 2},
    {"k": 5}, {},
])
async def test_post_validation_is_422(client, drv, body):
    r = await client.post("/search/similar", json=body)
    assert r.status_code == 422, r.text


async def test_feed_scope_is_404_when_the_feed_is_off(client, drv, monkeypatch):
    monkeypatch.delenv("PAPER_FEED", raising=False)
    r = await client.post("/search/similar", json={"text": TEXT, "scope": "feed"})
    assert r.status_code == 404 and "feed" in r.json()["detail"]
    r = await client.get("/search/similar/x", params={"scope": "feed"})
    assert r.status_code == 404


async def test_unavailable_is_a_200_with_a_reason(client, drv):
    r = await client.post("/search/similar", json={"text": TEXT, "scope": "library"})     # nothing indexed
    assert r.status_code == 200
    assert r.json()["available"] is False and r.json()["reason"] and r.json()["hits"] == []


async def test_post_respects_the_users_visibility(client, app, drv):
    drv.add("mine", 1, project="alpha")
    drv.add("shared", 1)
    ids = lambda r: {h["id"] for h in r.json()["hits"]}      # noqa: E731
    r = await client.post("/search/similar", json={"text": TEXT, "scope": "library"})
    assert ids(r) == {"mine", "shared"}
    app.state.user = "bob"
    r = await client.post("/search/similar", json={"text": TEXT, "scope": "library"})
    assert ids(r) == {"shared"}


async def test_since_and_stub_options_reach_the_search(client, drv):
    drv.add("old", 1, year=2018)
    drv.add("stub", 1, stub=True, year=2024)
    drv.add("new", 1, year=2025)
    r = await client.post("/search/similar", json={"text": TEXT, "scope": "library", "since": "2024-06-01"})
    assert {h["id"] for h in r.json()["hits"]} == {"new"}
    r = await client.post("/search/similar", json={"text": TEXT, "scope": "library", "include_stubs": True})
    assert {h["id"] for h in r.json()["hits"]} == {"old", "stub", "new"}


async def test_more_like_this_paper(client, app, drv):
    for i in range(3):
        drv.add(f"a{i}", 1)
    drv.add("b0", 2)
    drv.add("hidden", 1, project="beta")                       # alice is no member of beta
    r = await client.get("/search/similar/a0", params={"k": 5, "scope": "library"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "paper" and {h["id"] for h in body["hits"]} == {"a1", "a2"}
    assert (await client.get("/search/similar/hidden")).status_code == 404         # exists, but not visible
    assert (await client.get("/search/similar/none-such")).status_code == 404
    app.state.user = "bob"
    assert (await client.get("/search/similar/hidden")).status_code == 404         # nobody is a member of beta
    assert (await client.get("/search/similar/a0", params={"k": 0})).status_code == 422
    assert (await client.get("/search/similar/a0", params={"scope": "x"})).status_code == 422


async def test_login_is_required(monkeypatch):
    from config import settings
    from main import app as real_app

    monkeypatch.setattr(settings, "require_login", True)
    async with AsyncClient(transport=ASGITransport(app=real_app), base_url="http://test") as c:
        assert (await c.post("/search/similar", json={"text": TEXT})).status_code == 401
        assert (await c.get("/search/similar/abc")).status_code == 401
