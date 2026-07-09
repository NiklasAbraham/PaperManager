"""Tests for the Ideogram proxy router.

The router forwards to the inference manager over httpx. We construct the test
client first (a real httpx client over the ASGI transport), then patch
``httpx.AsyncClient`` only for the duration of each request so the router's
*outbound* calls hit a fake — the already-built test client is unaffected.
"""
import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from main import app
from config import settings
from services.auth import get_current_user
import routers.ideogram as ig


class FakeResp:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = text

    def json(self):
        return self._json


class FakeClient:
    """Async-context httpx stand-in; matches responses by method + path suffix."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _match(self, method, url):
        for (m, suffix), resp in self.responses.items():
            if m == method and url.endswith(suffix):
                return resp
        raise AssertionError(f"unexpected {method} {url}")

    async def post(self, url, json=None, **k):
        self.calls.append(("POST", url, json))
        return self._match("POST", url)

    async def get(self, url, **k):
        self.calls.append(("GET", url, None))
        return self._match("GET", url)

    async def delete(self, url, **k):
        self.calls.append(("DELETE", url, None))
        return self._match("DELETE", url)


@pytest.fixture(autouse=True)
def _setup():
    settings.inference_manager_url = "http://mgr"
    ig._current_job_id = None
    app.dependency_overrides[get_current_user] = lambda: "tester"
    yield
    app.dependency_overrides.clear()
    ig._current_job_id = None


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest.mark.asyncio
async def test_start_session_starts_when_free(client):
    fake = FakeClient({("POST", "/ideogram"): FakeResp(200, {"job_id": "ig1", "status": "starting"})})
    with patch("httpx.AsyncClient", return_value=fake):
        resp = await client.post("/ideogram/session/start")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "ig1"
    assert ig._current_job_id == "ig1"


@pytest.mark.asyncio
async def test_start_session_conflict_returns_409(client):
    fake = FakeClient({("POST", "/ideogram"): FakeResp(409, {"detail": "GPU 2 is busy with docling-serve"})})
    with patch("httpx.AsyncClient", return_value=fake):
        resp = await client.post("/ideogram/session/start")
    assert resp.status_code == 409
    assert "busy" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_status_stopped_when_no_job(client):
    resp = await client.get("/ideogram/session/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


@pytest.mark.asyncio
async def test_generate_forwards_result(client):
    fake = FakeClient({
        ("POST", "/ideogram/generate"): FakeResp(200, {"image_base64": "abc", "seed": 5, "caption": {"x": 1}}),
    })
    with patch("httpx.AsyncClient", return_value=fake):
        resp = await client.post("/ideogram/generate", json={"caption_json": {"x": 1}, "seed": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["seed"] == 5
    assert body["image_base64"] == "abc"


@pytest.mark.asyncio
async def test_generate_unwraps_proxy_error(client):
    fake = FakeClient({
        ("POST", "/ideogram/generate"): FakeResp(
            200, {"_proxy_error": True, "upstream_status": 502, "detail": "boom"}
        ),
    })
    with patch("httpx.AsyncClient", return_value=fake):
        resp = await client.post("/ideogram/generate", json={"prompt": "x"})
    assert resp.status_code == 502
    assert "boom" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_requires_auth(client):
    app.dependency_overrides.clear()  # remove the auth bypass
    resp = await client.post("/ideogram/session/start")
    assert resp.status_code in (401, 403)
