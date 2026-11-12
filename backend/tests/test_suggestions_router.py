"""Suggestions API (.specs/015_suggestions.md) against an in-memory stand-in for the query layer."""
from __future__ import annotations

import itertools

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from db.queries import suggestions as sq
from routers import suggestions as router_mod
from services import suggestions as svc
from services.auth import get_current_user


class FakeStore:
    """The functions of db.queries.suggestions over a dict."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self._clock = itertools.count(1)

    def _ts(self) -> str:
        return f"2026-11-12T10:00:{next(self._clock):02d}+00:00"

    def create_suggestion(self, driver, *, text, source, created_by, detail="", context="", conversation_id=None):
        sid = f"s{next(self._ids)}"
        ts = self._ts()
        self.rows[sid] = {
            "id": sid, "text": text, "detail": detail, "source": source, "status": "open",
            "created_by": created_by, "created_at": ts, "updated_at": ts,
            "voters": [created_by] if created_by else [], "context": context,
            "conversation_id": conversation_id, "seen": 1,
        }
        return dict(self.rows[sid])

    def list_suggestions(self, driver, status=None, source=None):
        return [dict(r) for r in self.rows.values()
                if (not status or r["status"] == status) and (not source or r["source"] == source)]

    def counts(self, driver):
        out = {s: 0 for s in sq.STATUSES}
        for r in self.rows.values():
            out[r["status"]] += 1
        return out

    def get_suggestion(self, driver, sid):
        return dict(self.rows[sid]) if sid in self.rows else None

    def update_suggestion(self, driver, sid, fields):
        if sid not in self.rows:
            return None
        self.rows[sid].update({k: v for k, v in fields.items() if k in ("status", "text", "detail")},
                              updated_at=self._ts())
        return dict(self.rows[sid])

    def toggle_vote(self, driver, sid, user):
        if sid not in self.rows:
            return None
        voters = self.rows[sid]["voters"]
        voters.remove(user) if user in voters else voters.append(user)
        return dict(self.rows[sid])

    def add_seen(self, driver, sid, user):
        if sid not in self.rows:
            return None
        row = self.rows[sid]
        row["seen"] += 1
        if user and user not in row["voters"]:
            row["voters"].append(user)
        return dict(row)

    def delete_suggestion(self, driver, sid):
        return self.rows.pop(sid, None) is not None

    def find_similar(self, driver, statuses=("open", "planned")):
        return [dict(r) for r in self.rows.values() if r["status"] in statuses]


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    for name in ("create_suggestion", "list_suggestions", "counts", "get_suggestion", "update_suggestion",
                 "toggle_vote", "add_seen", "delete_suggestion", "find_similar"):
        monkeypatch.setattr(sq, name, getattr(fake, name))
    monkeypatch.setattr(router_mod, "get_driver", lambda: object())
    monkeypatch.setattr(svc, "get_driver", lambda: object())
    return fake


@pytest.fixture
def admins(monkeypatch):
    names: set[str] = set()
    monkeypatch.setattr(router_mod, "_is_admin", lambda username: username in names)
    return names


@pytest.fixture
def app(store, admins):
    app = FastAPI()
    app.include_router(router_mod.router)
    app.state.user = "alice"
    app.dependency_overrides[get_current_user] = lambda: app.state.user
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def create(client, text="Add a dark mode", **extra):
    r = await client.post("/suggestions", json={"text": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_returns_the_documented_shape(client):
    body = await create(client, "  Add a dark mode  ", detail="At night the reader is too bright.")
    assert set(body) == {"id", "text", "detail", "source", "status", "created_by", "created_at",
                         "updated_at", "votes", "voted", "context", "conversation_id", "seen"}
    assert body["text"] == "Add a dark mode"
    assert body["source"] == "user" and body["status"] == "open"
    assert body["created_by"] == "alice" and body["votes"] == 1 and body["voted"] is True
    assert body["seen"] == 1 and body["conversation_id"] is None


@pytest.mark.parametrize("payload", [
    {"text": "ab"}, {"text": "   "}, {"text": "x" * 281}, {"text": "fine text", "detail": "d" * 2001}, {},
])
async def test_create_validates_lengths(client, payload):
    assert (await client.post("/suggestions", json=payload)).status_code == 422


async def test_list_filters_and_default_sort(client, app, admins):
    a = await create(client, "First idea")
    b = await create(client, "Second idea")
    app.state.user = "bob"
    await client.post(f"/suggestions/{b['id']}/vote")      # b: 2 votes
    c = await create(client, "Third idea")                  # newest, 1 vote
    admins.add("bob")
    await client.patch(f"/suggestions/{a['id']}", json={"status": "done"})

    rows = (await client.get("/suggestions")).json()
    assert [r["id"] for r in rows] == [b["id"], c["id"], a["id"]]  # open by votes, done last
    assert rows[0]["voted"] is True                               # bob voted for b
    assert [r["id"] for r in (await client.get("/suggestions?sort=new")).json()] == [c["id"], b["id"], a["id"]]
    assert [r["id"] for r in (await client.get("/suggestions?status=done")).json()] == [a["id"]]
    assert (await client.get("/suggestions?source=chat")).json() == []
    assert (await client.get("/suggestions?status=bogus")).status_code == 422


async def test_counts_has_all_four_statuses(client, admins):
    a = await create(client, "First idea")
    await create(client, "Second idea")
    admins.add("alice")
    await client.patch(f"/suggestions/{a['id']}", json={"status": "planned"})
    assert (await client.get("/suggestions/counts")).json() == {"open": 1, "planned": 1, "done": 0, "dismissed": 0}


async def test_vote_toggles(client, app):
    s = await create(client)
    app.state.user = "bob"
    r = (await client.post(f"/suggestions/{s['id']}/vote")).json()
    assert (r["votes"], r["voted"]) == (2, True)
    r = (await client.post(f"/suggestions/{s['id']}/vote")).json()
    assert (r["votes"], r["voted"]) == (1, False)
    assert (await client.post("/suggestions/nope/vote")).status_code == 404


async def test_status_change_is_admin_only(client, app, admins):
    s = await create(client)
    r = await client.patch(f"/suggestions/{s['id']}", json={"status": "planned"})
    assert r.status_code == 403                      # even the author may not
    admins.add("alice")
    r = await client.patch(f"/suggestions/{s['id']}", json={"status": "planned"})
    assert r.status_code == 200 and r.json()["status"] == "planned"
    assert (await client.patch(f"/suggestions/{s['id']}", json={"status": "nonsense"})).status_code == 422


async def test_text_and_detail_edits_need_author_or_admin(client, app, admins):
    s = await create(client)
    r = await client.patch(f"/suggestions/{s['id']}", json={"text": "Better wording", "detail": "More"})
    assert r.status_code == 200 and r.json()["text"] == "Better wording" and r.json()["detail"] == "More"

    app.state.user = "bob"
    assert (await client.patch(f"/suggestions/{s['id']}", json={"text": "Hijacked"})).status_code == 403
    admins.add("bob")
    assert (await client.patch(f"/suggestions/{s['id']}", json={"text": "Edited by admin"})).status_code == 200
    assert (await client.patch("/suggestions/missing", json={"text": "Whatever"})).status_code == 404


async def test_delete_needs_author_or_admin(client, app, admins):
    s = await create(client)
    app.state.user = "bob"
    assert (await client.delete(f"/suggestions/{s['id']}")).status_code == 403
    admins.add("bob")
    assert (await client.delete(f"/suggestions/{s['id']}")).status_code == 204
    assert (await client.delete(f"/suggestions/{s['id']}")).status_code == 404
    app.state.user = "alice"
    own = await create(client, "My own idea")
    assert (await client.delete(f"/suggestions/{own['id']}")).status_code == 204
    assert (await client.get("/suggestions")).json() == []


async def test_requires_a_session():
    app = FastAPI()
    app.include_router(router_mod.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/suggestions")).status_code == 401


# ── recording from the chat ───────────────────────────────────────────────────

def test_chat_suggestion_is_created_with_context(store):
    out = svc.record_chat_suggestion("Let me pin papers to the top.", user="alice",
                                     context="How do I pin?", conversation_id="c1")
    assert out["source"] == "chat" and out["votes"] == 1 and out["voted"] is True
    assert out["context"] == "How do I pin?" and out["conversation_id"] == "c1"
    assert len(store.rows) == 1


def test_chat_suggestion_dedupes_into_a_vote(store):
    first = svc.record_chat_suggestion("Add a dark mode to the reader", user="alice")
    again = svc.record_chat_suggestion("add a DARK mode to the reader!", user="bob")
    near = svc.record_chat_suggestion("Add dark mode to the reader", user="carol")
    assert len(store.rows) == 1
    assert again["id"] == first["id"] == near["id"]
    assert near["seen"] == 3 and near["votes"] == 3 and near["voted"] is True


def test_dedupe_ignores_done_and_dismissed(store):
    first = svc.record_chat_suggestion("Add a dark mode to the reader", user="alice")
    store.rows[first["id"]]["status"] = "done"
    second = svc.record_chat_suggestion("Add a dark mode to the reader", user="alice")
    assert second["id"] != first["id"] and len(store.rows) == 2


def test_chat_suggestion_is_trimmed_and_too_short_ones_dropped(store):
    assert svc.record_chat_suggestion("ok", user="alice") is None
    out = svc.record_chat_suggestion("word " * 100, user="alice", context="q" * 500)
    assert len(out["text"]) <= svc.TEXT_MAX and len(out["context"]) <= svc.CONTEXT_MAX
