"""Reports HTTP API: ownership, creation, listing, export, cancel, delete. The query layer is an
in-memory fake and the job starter is replaced, so nothing runs the pipeline."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers import reports as router_mod
from services.auth import get_current_user
from services.reports import jobs, llm, retrieval
from tests.test_reports_pipeline import FakeReports

pytestmark = pytest.mark.asyncio

MARKDOWN = (
    "# Diffusion in the library\n\nThe answer first.\n\n## Introduction\n\nText [[1]](/paper/p1).\n\n"
    "## References\n\n1. A (2021). *Title of p1*. Venue X. [Open in library](/paper/p1)\n"
)


@pytest.fixture
def store(monkeypatch):
    fake = FakeReports().install(monkeypatch)
    fake.papers = {"p1": {"title": "Title of p1", "year": 2021}}
    monkeypatch.setattr(router_mod, "get_driver", lambda: object())
    monkeypatch.setattr(router_mod, "_is_admin", lambda user: user == "root")
    monkeypatch.setattr(llm, "available_models", lambda username=None: [
        {"id": "fast", "label": "Claude Haiku 4.5", "available": True},
        {"id": "claude", "label": "Claude Sonnet 4.6", "available": True},
        {"id": "claude-work", "label": "Claude Sonnet 4.6 (work)", "available": False},
    ])
    monkeypatch.setattr(llm, "model_label", lambda model: "Claude Haiku 4.5")
    monkeypatch.setattr(retrieval, "project_info", lambda d, pid, user: (
        {"id": pid, "name": "Thesis"} if pid == "proj" else None))
    fake.started, fake.cancelled = [], []
    monkeypatch.setattr(jobs, "start", lambda rid: fake.started.append(rid))
    monkeypatch.setattr(jobs, "cancel", lambda rid: fake.cancelled.append(rid) or True)
    return fake


def client(user: str = "alice") -> AsyncClient:
    app = FastAPI()
    app.include_router(router_mod.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def finished(store, owner="alice", title="Diffusion in the library") -> str:
    rid = store.create_report(None, {"owner": owner, "question": "q", "title": title, "model": "fast"})["id"]
    store.finish_report(None, rid, title=title, markdown=MARKDOWN, word_count=12, cited=[{"id": "p1", "n": 1}])
    return rid


async def test_options(store):
    async with client() as c:
        r = await c.get("/reports/options")
    assert r.status_code == 200
    body = r.json()
    assert body["default_model"] == "fast" and body["lengths"] == ["short", "standard", "long"]
    assert body["models"][0] == {"id": "fast", "label": "Claude Haiku 4.5", "available": True}
    assert body["models"][2]["available"] is False


async def test_create_returns_202_summary_and_starts_the_job(store):
    async with client() as c:
        r = await c.post("/reports", json={"question": "  How do diffusion models work?  ", "length": "short"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and body["owner"] == "alice" and body["length"] == "short"
    assert body["model"] == "fast" and body["question"] == "How do diffusion models work?"
    assert set(body) == set("id title question project_id project_name status stage progress model length owner "
                            "created_at updated_at finished_at paper_count word_count error".split())
    assert store.started == [body["id"]]
    assert "markdown" not in body


async def test_create_with_project_and_papers(store):
    async with client() as c:
        r = await c.post("/reports", json={"project_id": "proj", "paper_ids": ["p1", "p2"], "model": "claude"})
    assert r.status_code == 202
    body = r.json()
    assert body["project_id"] == "proj" and body["project_name"] == "Thesis" and body["model"] == "claude"
    assert json.loads(store.rows[body["id"]]["paper_ids_json"]) == ["p1", "p2"]


@pytest.mark.parametrize("payload,code", [
    ({}, 422),
    ({"question": "   "}, 422),
    ({"paper_ids": ["p1"]}, 422),
    ({"question": "q", "length": "huge"}, 422),
    ({"question": "q", "model": "gpt"}, 422),
    ({"question": "q", "model": "claude-work"}, 422),   # not available for this user
    ({"project_id": "unknown"}, 404),
])
async def test_create_rejects_bad_requests(store, payload, code):
    async with client() as c:
        r = await c.post("/reports", json=payload)
    assert r.status_code == code
    assert store.started == [] and store.rows == {}


async def test_list_is_own_reports_newest_first_without_markdown(store):
    a = finished(store, "alice", "First")
    b = finished(store, "alice", "Second")
    finished(store, "bob", "Bobs")
    async with client("alice") as c:
        r = await c.get("/reports")
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [b, a]
    assert all("markdown" not in x for x in r.json())


async def test_list_all_is_for_admins_only(store):
    finished(store, "alice")
    finished(store, "bob")
    async with client("root") as c:
        assert len((await c.get("/reports?all=true")).json()) == 2
        assert (await c.get("/reports")).json() == []
    async with client("alice") as c:
        assert len((await c.get("/reports?all=true")).json()) == 1


async def test_detail_has_markdown_steps_and_papers(store):
    rid = finished(store)
    async with client() as c:
        r = await c.get(f"/reports/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["markdown"] == MARKDOWN and body["status"] == "done" and body["progress"] == 100
    assert [s["message"] for s in body["steps"]] == ["Queued", "Report saved"]
    assert set(body["steps"][0]) == {"ts", "message"}
    assert body["papers"] == [{"id": "p1", "title": "Title of p1", "year": 2021, "n": 1}]


async def test_other_users_get_404_but_admins_may_read(store):
    rid = finished(store, "alice")
    async with client("bob") as c:
        for call in (c.get(f"/reports/{rid}"), c.get(f"/reports/{rid}/export"), c.post(f"/reports/{rid}/cancel"),
                     c.delete(f"/reports/{rid}")):
            assert (await call).status_code == 404
    assert rid in store.rows
    async with client("root") as c:
        assert (await c.get(f"/reports/{rid}")).status_code == 200
    async with client("alice") as c:
        assert (await c.get("/reports/does-not-exist")).status_code == 404


async def test_export_markdown_and_html(store):
    rid = finished(store)
    async with client() as c:
        md = await c.get(f"/reports/{rid}/export")
        md2 = await c.get(f"/reports/{rid}/export?format=md")
        html = await c.get(f"/reports/{rid}/export?format=html")
        bad = await c.get(f"/reports/{rid}/export?format=pdf")
    assert md.status_code == 200 and md.text == MARKDOWN == md2.text
    assert md.headers["content-type"] == "text/markdown; charset=utf-8"
    assert md.headers["content-disposition"] == 'attachment; filename="diffusion-in-the-library.md"'
    assert html.status_code == 200 and html.headers["content-type"] == "text/html; charset=utf-8"
    assert html.headers["content-disposition"] == 'attachment; filename="diffusion-in-the-library.html"'
    assert "<h1>Diffusion in the library</h1>" in html.text and "Written by an AI (Claude Haiku 4.5)" in html.text
    assert "http://localhost:5173/paper/p1" in html.text  # frontend_url default makes links absolute
    assert bad.status_code == 422


async def test_export_of_an_unfinished_report_is_409(store):
    rid = store.create_report(None, {"owner": "alice", "question": "q"})["id"]
    async with client() as c:
        r = await c.get(f"/reports/{rid}/export?format=html")
    assert r.status_code == 409


async def test_cancel_running_report(store):
    rid = store.create_report(None, {"owner": "alice", "question": "q"})["id"]
    store.update_progress(None, rid, status="running", stage="evidence", progress=30)
    async with client() as c:
        r = await c.post(f"/reports/{rid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert store.cancelled == [rid] and store.rows[rid]["status"] == "cancelled"


async def test_cancel_finished_report_changes_nothing(store):
    rid = finished(store)
    async with client() as c:
        r = await c.post(f"/reports/{rid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "done" and store.cancelled == []


async def test_delete_removes_the_report_and_cancels_a_running_job(store):
    done = finished(store)
    running = store.create_report(None, {"owner": "alice", "question": "q"})["id"]
    async with client() as c:
        assert (await c.delete(f"/reports/{done}")).status_code == 204
        assert (await c.delete(f"/reports/{running}")).status_code == 204
        assert (await c.get(f"/reports/{done}")).status_code == 404
    assert store.rows == {} and store.cancelled == [running]
