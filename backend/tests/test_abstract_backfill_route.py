"""POST /backfill/abstracts: admin only (same guard as the other backfill routes), dry run by
default, bounded batch, summary without titles, one run at a time."""
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from routers import backfill as route
from services import abstract_backfill as ab
from services.auth import create_access_token
from tests.abstract_backfill_helpers import LONG, FakeDriver, FakeWeb, paper

pytestmark = pytest.mark.asyncio


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(user="someone"):
    return {"Authorization": f"Bearer {create_access_token({'sub': user})}"}


async def test_requires_login():
    async with _client() as c:
        r = await c.post("/backfill/abstracts")
    assert r.status_code == 401


async def test_non_admin_is_refused():
    with patch("db.connection.get_driver"), patch("db.queries.users.is_user_admin", return_value=False):
        async with _client() as c:
            r = await c.post("/backfill/abstracts", headers=_auth(), json={"dry_run": False})
    assert r.status_code == 403


@pytest.fixture
def admin_setup(monkeypatch):
    """An admin session, a fake library and a fake web behind the service's own Http class."""
    driver = FakeDriver([paper("p1", "10.1111/a", "Alpha scaling of toy systems"),
                         paper("p2", "10.1111/b", "Beta response of toy systems")])
    web = FakeWeb()
    web.openalex["10.1111/a"] = ("Alpha scaling of toy systems", LONG)
    web.openalex["10.1111/b"] = ("Some other paper altogether", LONG)
    monkeypatch.setattr(ab, "Http", lambda contact="": web.http(contact=contact))
    with patch.object(route, "get_driver", return_value=driver), \
            patch("db.connection.get_driver"), patch("db.queries.users.is_user_admin", return_value=True):
        yield driver, web


async def test_admin_default_is_a_dry_run_without_titles(admin_setup):
    driver, web = admin_setup
    async with _client() as c:
        r = await c.post("/backfill/abstracts", headers=_auth("boss"))
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True and driver.writes == []
    assert body["counts"]["would_apply"] == 1 and body["counts"]["title_mismatch"] == 1
    assert {s["outcome"] for s in body["sample_ids"]} == {"would_apply", "title_mismatch"}
    assert len(body["sample_ids"]) <= 50
    text = r.text
    assert "Alpha" not in text and "Some other paper" not in text and "papers" not in body


async def test_apply_writes_and_reports(admin_setup):
    driver, _ = admin_setup
    async with _client() as c:
        r = await c.post("/backfill/abstracts", headers=_auth("boss"), json={"dry_run": False, "sources": ["openalex"]})
    assert r.status_code == 200 and r.json()["counts"]["applied"] == 1
    assert driver.get("p1")["abstract_source"] == "openalex" and not driver.get("p2").get("abstract")


async def test_limit_defaults_and_is_capped(admin_setup):
    seen = {}

    def fake_run(driver, **kw):
        seen.update(kw)
        return {"dry_run": True, "counts": {}, "papers": []}

    with patch.object(ab, "run_backfill", fake_run):
        async with _client() as c:
            await c.post("/backfill/abstracts", headers=_auth("boss"))
            assert seen["limit"] == route.ABSTRACTS_ROUTE_DEFAULT_LIMIT and seen["dry_run"] is True
            await c.post("/backfill/abstracts", headers=_auth("boss"), json={"limit": 7, "include_stubs": True})
            assert seen["limit"] == 7 and seen["include_stubs"] is True
            r = await c.post("/backfill/abstracts", headers=_auth("boss"), json={"limit": route.ABSTRACTS_ROUTE_MAX_LIMIT + 1})
            assert r.status_code == 422


async def test_unknown_source_is_a_422(admin_setup):
    async with _client() as c:
        r = await c.post("/backfill/abstracts", headers=_auth("boss"), json={"sources": ["pubmed"]})
    assert r.status_code == 422


async def test_second_concurrent_run_gets_409(admin_setup):
    assert route._abstracts_lock.acquire(blocking=False)
    try:
        async with _client() as c:
            r = await c.post("/backfill/abstracts", headers=_auth("boss"))
        assert r.status_code == 409
    finally:
        route._abstracts_lock.release()
