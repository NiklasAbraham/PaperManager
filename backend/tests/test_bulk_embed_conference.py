"""The conference explorer keeps its own model: CONFERENCE_EMBED_MODEL first, EMBED_MODEL only if it is unset.
Library code embeds with EMBED_MODEL, the explorer with the other, both models are cached per model id."""
from __future__ import annotations

import numpy as np
import pytest

from services.conferences import embedder, search, store
from services.vectorstore import model_config
from tests.bulk_embed_helpers import DIM, make_tiny_modernbert
from tests.test_conferences import _fake_dataset

VARS = ("EMBED_MODEL", "CONFERENCE_EMBED_MODEL", "EMBED_DIM", "EMBED_POOLING", "EMBED_QUERY_PREFIX",
        "EMBED_DOC_PREFIX", "CONFERENCE_EMBED_DIM", "CONFERENCE_EMBED_POOLING", "CONFERENCE_EMBED_QUERY_PREFIX",
        "CONFERENCE_EMBED_DOC_PREFIX")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)


# ── the settings ──────────────────────────────────────────────────────────────────────────────────

def test_with_neither_set_both_use_the_default():
    assert model_config.current_conference() == model_config.current()
    assert model_config.current_conference().model == model_config.DEFAULT_MODEL
    assert model_config.conference_dim() == 384


def test_embed_model_alone_moves_both_as_before(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    assert model_config.current_conference() == model_config.current()
    assert model_config.conference_dim() == 768
    monkeypatch.setenv("EMBED_MODEL", "example/custom-encoder")
    monkeypatch.setenv("EMBED_DIM", "512")
    monkeypatch.setenv("EMBED_POOLING", "mean")
    assert model_config.current_conference() == model_config.current() and model_config.conference_dim() == 512


def test_the_old_conference_variable_alone_still_moves_both(monkeypatch):
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    assert model_config.current().model == model_config.current_conference().model == "BAAI/bge-base-en-v1.5"
    assert model_config.legacy_model() == "BAAI/bge-base-en-v1.5"


def test_the_conference_variable_is_read_first(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "J0nasW/sciembed-full")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    lib, conf = model_config.current(), model_config.current_conference()
    assert (lib.model, lib.dim, lib.pooling) == ("J0nasW/sciembed-full", 768, "mean")
    assert (conf.model, conf.dim, conf.pooling) == ("BAAI/bge-small-en-v1.5", 384, "cls")
    assert conf.query_prefix.startswith("Represent this sentence") and conf.doc_prefix == ""
    assert model_config.dim() == 768 and model_config.conference_dim() == 384
    # EMBED_DIM and friends belong to EMBED_MODEL: the explorer's model does not inherit them
    monkeypatch.setenv("EMBED_POOLING", "cls")
    monkeypatch.setenv("EMBED_DOC_PREFIX", "doc: ")
    assert model_config.current_conference().pooling == "cls" and model_config.current_conference().doc_prefix == ""


def test_an_unlisted_conference_model_takes_its_own_settings(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "J0nasW/sciembed-full")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "example/other-encoder")
    with pytest.raises(model_config.ModelConfigError, match="CONFERENCE_EMBED_DIM"):
        model_config.current_conference()
    monkeypatch.setenv("CONFERENCE_EMBED_DIM", "256")
    monkeypatch.setenv("CONFERENCE_EMBED_POOLING", "cls")
    c = model_config.current_conference()
    assert (c.model, c.dim, c.pooling) == ("example/other-encoder", 256, "cls")


def test_the_same_model_in_both_variables_keeps_the_embed_settings(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "example/custom-encoder")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "example/custom-encoder")
    monkeypatch.setenv("EMBED_DIM", "96")
    assert model_config.current_conference() == model_config.current() and model_config.conference_dim() == 96


# ── what embeds with which model ──────────────────────────────────────────────────────────────────

def test_library_code_embeds_with_a_and_the_explorer_with_b(monkeypatch, tmp_path):
    a = make_tiny_modernbert(tmp_path / "model-a", seed=0)
    b = make_tiny_modernbert(tmp_path / "model-b", seed=1)
    monkeypatch.setenv("EMBED_MODEL", a)
    monkeypatch.setenv("EMBED_DIM", str(DIM))
    monkeypatch.setenv("EMBED_POOLING", "mean")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", b)
    monkeypatch.setenv("CONFERENCE_EMBED_DIM", str(DIM))
    monkeypatch.setenv("CONFERENCE_EMBED_POOLING", "cls")                 # another pooling too, to tell them apart
    monkeypatch.setenv("CONFERENCE_DATA_DIR", str(tmp_path / "conf"))
    monkeypatch.setattr(store, "_data_dir", None)
    monkeypatch.setattr(embedder, "_models", {})
    loaded = []
    real = embedder._load
    monkeypatch.setattr(embedder, "_load", lambda sp=None: loaded.append((sp or embedder.spec()).model) or real(sp))

    texts = ["attention is all you need", "protein folding with diffusion"]
    lib = embedder.embed(texts)
    conf = embedder.conference_embed(texts)
    assert loaded == [a, b]
    assert set(embedder._models) == {a, b}                                # one cached model per id, both held
    # reference: each model run directly
    import torch
    for path, pooling, got in ((a, "mean", lib), (b, "cls", conf)):
        tok, m = embedder._models[path]
        enc = tok(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        with torch.inference_mode():
            h = m(**enc).last_hidden_state
            pooled = h[:, 0] if pooling == "cls" else (h * enc["attention_mask"].unsqueeze(-1)).sum(1) / enc["attention_mask"].sum(1, keepdim=True)
        want = torch.nn.functional.normalize(pooled, dim=-1).numpy()
        assert np.abs(got - want).max() < 1e-5
    assert np.abs(lib - conf).max() > 1e-3                                 # really two different embeddings
    # queries follow the same split; a second call loads nothing
    assert np.abs(embedder.embed_query("graph networks") - embedder.conference_embed_query("graph networks")).max() > 1e-3
    assert loaded == [a, b, a, b] and embedder.ready() and embedder.conference_ready()
    assert embedder.spec().model == a and embedder.spec("conference").model == b


def test_the_two_roles_share_one_model_when_they_name_the_same(monkeypatch, tmp_path):
    a = make_tiny_modernbert(tmp_path / "model-a")
    monkeypatch.setenv("EMBED_MODEL", a)
    monkeypatch.setenv("EMBED_DIM", str(DIM))
    monkeypatch.setenv("CONFERENCE_DATA_DIR", str(tmp_path / "conf"))
    monkeypatch.setattr(store, "_data_dir", None)
    monkeypatch.setattr(embedder, "_models", {})
    x = embedder.embed(["alpha beta"])
    assert embedder.conference_ready() and len(embedder._models) == 1
    assert np.abs(x - embedder.conference_embed(["alpha beta"])).max() == 0


def test_library_search_uses_the_library_model_and_the_explorer_the_conference_model(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    seen = []

    def fake_load(sp=None):
        seen.append((sp or embedder.spec()).model)
        raise RuntimeError("stop here")

    monkeypatch.setattr(embedder, "_load", fake_load)
    for fn in (embedder.embed_query, embedder.embed_document, lambda t: embedder.embed([t])[0]):
        with pytest.raises(RuntimeError):
            fn("some text")
    for fn in (embedder.conference_embed_query, lambda t: embedder.conference_embed([t])[0]):
        with pytest.raises(RuntimeError):
            fn("some text")
    assert seen == ["BAAI/bge-base-en-v1.5"] * 3 + ["BAAI/bge-small-en-v1.5"] * 2


# ── the explorer's saved vectors stay usable ──────────────────────────────────────────────────────

def test_the_explorers_vectors_survive_a_library_model_switch_when_its_model_is_set(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)                               # 384-dim vectors of the default model
    assert store.load("corl2025").emb is not None
    monkeypatch.setenv("EMBED_MODEL", "J0nasW/sciembed-full")          # the library moves to 768 dims ...
    store._cache.clear()
    assert store.load("corl2025").emb is None                          # ... and, as before, takes the explorer along
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    store._cache.clear()
    assert store.load("corl2025").emb is not None and store.load("corl2025").emb.shape == (3, 384)


def test_topic_search_embeds_the_query_with_the_conference_model(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)
    monkeypatch.setenv("EMBED_MODEL", "J0nasW/sciembed-full")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    store._cache.clear()
    asked = []
    monkeypatch.setattr(embedder, "embed_query", lambda t: pytest.fail("the library model must not be used here"))
    monkeypatch.setattr(embedder, "conference_embed_query", lambda t: asked.append(t) or np.eye(3, 384, dtype=np.float32)[1])
    res = store.topic(store.load("corl2025"), "legged robots", k=10)
    assert res["mode"] == "semantic" and res["papers"][0]["id"] == "p2" and asked == ["legged robots"]
    assert search._embed("Legged Robots") is not None and asked[-1] == "legged robots"


# ── the MCP server asks the backend per role ──────────────────────────────────────────────────────

class _Resp:
    def __init__(self, body):
        self.status_code, self._body = 200, body

    def json(self):
        return self._body


def test_the_remote_request_names_the_role_and_the_answer_must_be_that_models(monkeypatch):
    import httpx

    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("PM_EMBED_URL", "http://127.0.0.1:1/conferences/embed")
    monkeypatch.setattr(embedder, "ready", lambda role="library": False)
    sent = []

    def post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        model, dim = ("BAAI/bge-small-en-v1.5", 384) if json.get("role") == "conference" else ("BAAI/bge-base-en-v1.5", 768)
        return _Resp({"model": model, "dim": dim, "vector": [0.5] * dim})

    monkeypatch.setattr(httpx, "post", post)
    v = embedder.conference_embed_query("legged robots")
    assert v.shape == (384,) and sent[-1]["role"] == "conference"
    v = embedder.embed_query("legged robots")
    assert v.shape == (768,) and "role" not in sent[-1]                   # the library request is the old one, unchanged

    def old_backend(url, json=None, headers=None, timeout=None):        # an older backend ignores the role
        return _Resp({"model": "BAAI/bge-base-en-v1.5", "dim": 768, "vector": [0.5] * 768})

    monkeypatch.setattr(httpx, "post", old_backend)
    monkeypatch.setattr(embedder, "conference_embed", lambda texts, **kw: np.ones((len(texts), 384), np.float32))
    assert embedder.conference_embed_query("x").shape == (384,)           # refused, embedded locally instead


async def test_the_embed_route_serves_either_role(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from main import app

    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setattr(embedder, "ready", lambda role="library": role == "library")
    monkeypatch.setattr(embedder, "embed", lambda texts, **kw: np.full((len(texts), 768), 0.1, np.float32))
    monkeypatch.setattr(embedder, "conference_embed", lambda texts, **kw: np.full((len(texts), 384), 0.2, np.float32))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/conferences/embed", json={"text": "x"})
        assert r.status_code == 200 and r.json()["model"] == "BAAI/bge-base-en-v1.5" and r.json()["dim"] == 768
        r = await c.post("/conferences/embed", json={"text": "x", "role": "conference"})
        assert r.status_code == 503                                       # that model is not loaded yet
        monkeypatch.setattr(embedder, "ready", lambda role="library": True)
        r = await c.post("/conferences/embed", json={"text": "x", "role": "conference"})
    assert r.status_code == 200 and r.json()["model"] == "BAAI/bge-small-en-v1.5" and r.json()["dim"] == 384
    assert r.json()["vector"][0] == 0.2
