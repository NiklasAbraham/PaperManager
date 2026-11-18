"""With PAPER_FEED off (the default) the feed does nothing: no thread, no directory, no model, no network."""
from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers import feed as feed_router
from services.auth import get_current_user
from services.feed import config, pipeline, sources, store


@pytest.fixture(params=[None, "false", "0", "off", ""])
def off(request, monkeypatch, tmp_path):
    if request.param is None:
        monkeypatch.delenv("PAPER_FEED", raising=False)
    else:
        monkeypatch.setenv("PAPER_FEED", request.param)
    target = tmp_path / "feed-dir"
    monkeypatch.setenv("PAPER_FEED_DIR", str(target))
    store.reset()
    return target


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(feed_router.router)
    app.dependency_overrides[get_current_user] = lambda: "alice"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_enabled_is_false_by_default(off):
    assert config.enabled() is False


async def test_status_says_disabled_and_nothing_else(off, client):
    r = await client.get("/feed/status")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}
    assert not off.exists()


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/feed", None),
    ("GET", "/feed?days=2", None),
    ("GET", "/feed/config", None),
    ("PUT", "/feed/config", {"sources": ["arxiv"], "arxiv_categories": ["cs.LG"], "digest_days": 3, "min_score": 0}),
    ("POST", "/feed/refresh", None),
    ("POST", "/feed/arxiv:2401.00001/rate", {"value": 1}),
    ("POST", "/feed/arxiv:2401.00001/dismiss", None),
    ("POST", "/feed/arxiv:2401.00001/add", {}),
    ("DELETE", "/feed/arxiv:2401.00001/label", None),
])
async def test_every_other_route_is_404(off, client, method, path, body):
    r = await client.request(method, path, json=body)
    assert r.status_code == 404
    assert not off.exists()


def test_start_background_starts_no_thread(off, monkeypatch):
    before = {t.name for t in threading.enumerate()}
    pipeline.start_background()
    assert pipeline._thread is None
    assert {t.name for t in threading.enumerate()} == before
    assert not off.exists()


def test_start_background_never_touches_sources_store_or_model(off, monkeypatch):
    from services.conferences import embedder

    def boom(*a, **k):
        raise AssertionError("the feed touched something while disabled")

    monkeypatch.setattr(sources, "fetch_arxiv", boom)
    monkeypatch.setattr(sources, "fetch_biorxiv", boom)
    monkeypatch.setattr(sources, "_http_get", boom)
    monkeypatch.setattr(store, "get_store", boom)
    monkeypatch.setattr(pipeline, "get_store", boom)
    monkeypatch.setattr(embedder, "_load", boom)
    monkeypatch.setattr(embedder, "embed", boom)
    pipeline.start_background()
    assert not off.exists()


def test_importing_the_feed_modules_creates_nothing(tmp_path):
    """A fresh interpreter, feed off: importing everything starts no thread and makes no directory."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    target = tmp_path / "feed-dir"
    code = (
        "import threading\n"
        "before = {t.name for t in threading.enumerate()}\n"
        "import services.feed, services.feed.config, services.feed.store, services.feed.pipeline\n"
        "import services.feed.ranking, services.feed.library, services.feed.sources, routers.feed\n"
        "from services.feed import pipeline\n"
        "pipeline.start_background()\n"
        "assert {t.name for t in threading.enumerate()} == before\n"
        "print('ok')\n"
    )
    env = {**os.environ, "PAPER_FEED_DIR": str(target)}
    env.pop("PAPER_FEED", None)
    backend = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code], cwd=backend, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.strip().endswith("ok")
    assert not target.exists()


def test_main_mounts_the_router_and_guards_the_thread_by_the_flag():
    """main.py mounts /feed (so /feed/status can answer) and starts the thread only when enabled."""
    import inspect

    import main

    assert any(getattr(r, "path", "") == "/feed/status" for r in main.app.routes)
    src = inspect.getsource(main.lifespan)
    assert "feed_config.enabled()" in src and "start_feed()" in src
