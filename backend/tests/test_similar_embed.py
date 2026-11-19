"""How a "find similar" text is embedded: a long text as a document, a short phrase as a query, here
or by the backend (POST /conferences/embed with ``document``)."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.conferences import embedder as e

LONG = " ".join(f"word{i}" for i in range(60))
SHORT = "protein structure prediction"


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


@pytest.fixture
def local(monkeypatch):
    """A process without the model: ``embed`` is recorded, ``PM_EMBED_URL`` points at a backend."""
    calls: list[dict] = []

    def fake_embed(texts, **kw):
        calls.append({"texts": list(texts), **kw})
        return np.ones((len(texts), e.DIM), np.float32) / np.sqrt(e.DIM)

    monkeypatch.setattr(e, "ready", lambda role="library": False)
    monkeypatch.setattr(e, "embed", fake_embed)
    monkeypatch.setenv("PM_EMBED_URL", "http://127.0.0.1:1/conferences/embed")
    return calls


def test_the_short_query_limit():
    assert e.is_short_query(" ".join(["w"] * 24)) and not e.is_short_query(" ".join(["w"] * 25))
    assert e.QUERY_MAX_WORDS == 24


def test_a_long_text_is_embedded_as_a_document_without_the_retrieval_instruction(local, monkeypatch):
    monkeypatch.delenv("PM_EMBED_URL")
    v, mode = e.embed_search_text("  " + LONG + "\n")
    assert mode == "document" and v.shape == (e.DIM,)
    (call,) = local
    assert call["texts"] == [LONG]                       # stripped, nothing prepended
    assert call["doc"] is True and call["max_length"] == e.DOC_MAX_LENGTH
    assert "Represent this sentence" not in call["texts"][0]


def test_a_short_phrase_keeps_the_query_behaviour(local, monkeypatch):
    monkeypatch.delenv("PM_EMBED_URL")
    v, mode = e.embed_search_text(SHORT)
    assert mode == "query"
    (call,) = local
    assert call["texts"] == [e.query_text(SHORT)] and call["max_length"] == 512
    if e._QUERY_PREFIX:
        assert call["texts"][0].startswith(e._QUERY_PREFIX)


def test_a_process_without_the_model_asks_the_backend_for_a_document_vector(local, monkeypatch):
    import httpx

    sent = {}

    def post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json)
        return _Resp(200, {"model": e.MODEL, "dim": e.DIM, "vector": [0.5] * e.DIM})

    monkeypatch.setattr(httpx, "post", post)
    v, mode = e.embed_search_text(LONG)
    assert mode == "document" and float(v[0]) == 0.5 and local == []
    assert sent["json"] == {"text": LONG, "document": True}
    v, mode = e.embed_search_text(SHORT)
    assert mode == "query" and sent["json"] == {"text": e.query_text(SHORT)}      # the old request, unchanged


@pytest.mark.parametrize("resp", [_Resp(404), _Resp(503), ConnectionError("refused"),
                                  _Resp(200, {"model": "other/model", "dim": 384, "vector": [0.0] * 384})])
def test_a_backend_that_cannot_answer_falls_back_to_the_local_model(local, monkeypatch, resp):
    import httpx

    def post(*a, **kw):
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(httpx, "post", post)
    v, mode = e.embed_search_text(LONG)
    assert mode == "document" and v.shape == (e.DIM,)
    assert local and local[0]["texts"] == [LONG] and local[0]["doc"] is True


def test_a_loaded_model_is_never_bypassed(local, monkeypatch):
    import httpx

    monkeypatch.setattr(e, "ready", lambda role="library": True)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no remote call expected"))
    e.embed_search_text(LONG)
    assert len(local) == 1


@pytest.fixture
async def client():
    from routers.conferences import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_embed_route_document_flag(client, monkeypatch):
    seen = []

    def fake_embed(texts, **kw):
        seen.append((list(texts), kw))
        return np.ones((1, e.DIM), np.float32) / np.sqrt(e.DIM)

    monkeypatch.setattr(e, "ready", lambda: True)
    monkeypatch.setattr(e, "embed", fake_embed)
    r = await client.post("/conferences/embed", json={"text": LONG, "document": True})
    assert r.status_code == 200 and r.json()["dim"] == e.DIM and len(r.json()["vector"]) == e.DIM
    assert seen[-1][1]["max_length"] == e.DOC_MAX_LENGTH
    r = await client.post("/conferences/embed", json={"text": e.query_text(SHORT)})          # as before
    assert r.status_code == 200 and seen[-1][1]["max_length"] == 512
    r = await client.post("/conferences/embed", json={"text": "x", "document": False})
    assert seen[-1][1]["max_length"] == 512


async def test_embed_route_not_ready(client, monkeypatch):
    monkeypatch.setattr(e, "ready", lambda: False)
    r = await client.post("/conferences/embed", json={"text": LONG, "document": True})
    assert r.status_code == 503
