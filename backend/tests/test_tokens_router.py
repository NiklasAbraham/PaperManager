"""GET /tokens/summary, /tokens/calls, /tokens/prices (routers/tokens.py)."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from config import settings
from routers import tokens
from services.auth import get_current_user
from services.usage import ledger, pricing


def make_app(user="alice"):
    app = FastAPI()
    app.include_router(tokens.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return app


def client(user="alice"):
    return httpx.AsyncClient(transport=ASGITransport(app=make_app(user)), base_url="http://test")


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "usage_db_path", str(tmp_path / "usage.sqlite"))
    monkeypatch.setattr(settings, "usage_ledger_enabled", True)
    monkeypatch.setattr(tokens, "_is_admin", lambda username: username == "root")
    monkeypatch.setattr(tokens, "_paper_titles", lambda ids: {i: f"Title of {i}" for i in ids if i != "gone"})
    ledger.close()
    now = datetime.now(timezone.utc)
    for username, cost, paper, feature, provider in [
        ("alice", 0.5, "p1", "summary", "anthropic"),
        ("alice", 0.25, "gone", "topics", "anthropic"),
        ("bob", 2.0, "p2", "summary", "anthropic"),
        ("bob", 1.0, None, "knowledge-chat", "claude-code"),
        (None, 0.1, None, "claims", "litellm"),
    ]:
        ledger.record({"ts": now.isoformat(), "feature": feature, "provider": provider, "model": "claude-opus-4-6",
                       "input_tokens": 10, "output_tokens": 5, "cost_usd": cost, "price_known": 1,
                       "username": username, "paper_id": paper, "latency_ms": 100})
    ledger.record({"ts": (now - timedelta(days=2)).isoformat(), "feature": "summary", "provider": "anthropic",
                   "model": "weird", "cost_usd": None, "price_known": 0, "username": "alice", "ok": 0,
                   "error": "ValueError: x"})
    yield
    ledger.close()


async def get(path, user="alice"):
    async with client(user) as c:
        return await c.get(path)


async def test_summary_for_regular_user_is_scoped_to_self():
    r = await get("/tokens/summary?days=7&user=bob")  # the user filter is ignored
    assert r.status_code == 200
    d = r.json()
    assert d["scope"] == {"user": "alice", "is_admin": False}
    assert d["totals"]["calls"] == 3 and d["totals"]["errors"] == 1
    assert d["totals"]["cost_usd"] == pytest.approx(0.75)
    assert d["by_user"] == []
    assert len(d["by_day"]) == 7 and d["range"]["days"] == 7
    assert d["prices_as_of"] == pricing.PRICES_AS_OF
    assert d["unknown_models"] == ["weird"]
    assert d["today"]["calls"] == 2


async def test_summary_for_admin_sees_everyone_and_can_filter():
    d = (await get("/tokens/summary?days=30", "root")).json()
    assert d["scope"] == {"user": None, "is_admin": True}
    assert d["totals"]["calls"] == 6
    assert d["totals"]["subscription_usd"] == pytest.approx(1.0)
    assert d["totals"]["billed_usd"] == pytest.approx(d["totals"]["cost_usd"] - 1.0)
    users = {u["user"]: u["calls"] for u in d["by_user"]}
    assert users == {"alice": 3, "bob": 2, "(system)": 1}
    assert d["by_user"][0]["user"] == "bob"  # costliest first

    d = (await get("/tokens/summary?user=bob&feature=summary", "root")).json()
    assert d["scope"]["user"] == "bob" and d["totals"]["calls"] == 1
    d = (await get("/tokens/summary?user=(system)", "root")).json()
    assert d["totals"]["calls"] == 1 and d["by_feature"][0]["feature"] == "claims"


async def test_summary_top_papers_get_titles():
    d = (await get("/tokens/summary", "root")).json()
    titles = {p["paper_id"]: p["title"] for p in d["top_papers"]}
    assert titles == {"p1": "Title of p1", "gone": None, "p2": "Title of p2"}
    assert d["top_papers"][0]["paper_id"] == "p2"
    assert d["top_calls"][0]["cost_usd"] == pytest.approx(2.0) and d["top_calls"][0]["user"] == "bob"


async def test_summary_validates_days():
    assert (await get("/tokens/summary?days=0")).status_code == 422
    assert (await get("/tokens/summary?days=9999")).status_code == 422


async def test_calls_list_is_scoped_filtered_and_paged():
    d = (await get("/tokens/calls?limit=2")).json()
    assert d["total"] == 3 and len(d["calls"]) == 2
    row = d["calls"][0]
    assert set(row) == {"id", "ts", "feature", "label", "provider", "model", "input_tokens", "output_tokens",
                        "cache_read_tokens", "cache_write_tokens", "cost_usd", "price_known", "user", "paper_id",
                        "ok", "error", "latency_ms", "streamed", "estimated"}
    assert isinstance(row["ok"], bool) and isinstance(row["price_known"], bool)
    assert {c["user"] for c in (await get("/tokens/calls?user=bob")).json()["calls"]} == {"alice"}

    d = (await get("/tokens/calls?ok=false")).json()
    assert d["total"] == 1 and d["calls"][0]["error"] == "ValueError: x"
    d = (await get("/tokens/calls?user=bob&provider=claude-code", "root")).json()
    assert d["total"] == 1 and d["calls"][0]["feature"] == "knowledge-chat"
    d = (await get("/tokens/calls?paper_id=p2&days=1", "root")).json()
    assert d["total"] == 1
    assert (await get("/tokens/calls?limit=501")).status_code == 422
    assert (await get("/tokens/calls?model=weird")).json()["total"] == 1


async def test_prices():
    d = (await get("/tokens/prices")).json()
    assert d["as_of"] == pricing.PRICES_AS_OF and d["litellm_free"] is True
    haiku = next(m for m in d["models"] if m["prefix"] == "claude-haiku-4-5")
    assert haiku == {"prefix": "claude-haiku-4-5", "input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.1}


async def test_requires_a_session():
    app = FastAPI()
    app.include_router(tokens.router)  # no dependency override
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/tokens/summary")).status_code == 401


def test_is_admin_false_when_check_fails(monkeypatch):
    monkeypatch.undo()
    import db.queries.users as users

    def boom(driver, name):
        raise RuntimeError("no neo4j")

    monkeypatch.setattr(users, "is_user_admin", boom)
    assert tokens._is_admin("alice") is False
