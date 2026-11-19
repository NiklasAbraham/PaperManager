"""The MCP tools find_similar_papers and papers_like: compact JSON, follower stores, clear errors."""
from __future__ import annotations

import asyncio
import json

import pytest

from tests.feed_helpers import topic_vec
from tests.similar_helpers import FakeLibraryDriver, patch_embedder

TEXT = "A title about topic one.\n" + "A paragraph of an abstract that is long enough to count. " * 3


def _mcp():
    from mcp_server import mcp
    return mcp


def call(name: str, **kw) -> str:
    res = asyncio.run(_mcp().call_tool(name, kw))
    blocks = res[0] if isinstance(res, tuple) else res
    assert len(blocks) == 1, f"{name}: one text block expected"
    return blocks[0].text


@pytest.fixture
def drv(monkeypatch):
    import db.connection
    from tools import similarity_tools

    d = FakeLibraryDriver()
    d.members = {"alpha": {"alice"}}
    monkeypatch.setattr(db.connection, "get_driver", lambda: d)
    monkeypatch.setattr(similarity_tools, "_user", lambda: "alice")
    patch_embedder(monkeypatch, topic=1)
    return d


def test_the_tools_are_registered_with_their_signatures():
    tools = {t.name: t for t in asyncio.run(_mcp().list_tools())}
    a, b = tools["find_similar_papers"], tools["papers_like"]
    props = a.inputSchema["properties"]
    assert list(props) == ["text", "scope", "k", "since", "min_score"] and a.inputSchema["required"] == ["text"]
    assert props["scope"]["default"] == "both" and props["k"]["default"] == 10
    assert props["since"]["default"] == "" and props["min_score"]["default"] == 0.0
    assert list(b.inputSchema["properties"]) == ["paper_id", "scope", "k"] and b.inputSchema["required"] == ["paper_id"]
    assert b.inputSchema["properties"]["scope"]["default"] == "both"
    for t in (a, b):
        assert "title" not in t.inputSchema and t.description == t.description.strip()
    assert "abstract" in a.description and "not keywords" in a.description and "hypothetical" in a.description


def test_find_similar_papers_returns_compact_json(drv):
    for i in range(3):
        drv.add(f"a{i}", 1, title=f"Paper {i}", authors=("Ada Example", "Bo Sample", "Cy Test", "Di Case"),
                abstract="z" * 400)
    drv.add("b0", 4)
    text = call("find_similar_papers", text=TEXT, scope="library", k=2)
    res = json.loads(text)
    assert text == json.dumps(res, separators=(",", ":"), ensure_ascii=False)         # no whitespace, no indent
    assert res["available"] is True and res["total"] == 2 and res["scope"] == "library" and res["mode"] == "document"
    h = res["hits"][0]
    assert h["url"].endswith("/paper/" + h["id"]) and h["source"] == "library" and h["in_library"] is True
    assert isinstance(h["score"], float) and h["authors"] == "Ada Example, Bo Sample, Cy Test et al."
    assert len(h["snippet"]) == 301 and h["snippet"].endswith("…")
    assert set(h) <= {"title", "url", "score", "source", "in_library", "id", "authors", "year", "snippet", "venue",
                      "reading_status"}
    assert "abstract" not in h and None not in h.values()


def test_papers_like_and_the_visibility_of_the_caller(drv):
    drv.add("a0", 1)
    drv.add("a1", 1)
    drv.add("hidden", 1, project="beta")
    res = json.loads(call("papers_like", paper_id="a0", scope="library", k=5))
    assert res["mode"] == "paper" and [h["id"] for h in res["hits"]] == ["a1"]
    err = json.loads(call("papers_like", paper_id="hidden"))
    assert err == {"error": "Paper not found"}
    assert json.loads(call("find_similar_papers", text=TEXT, scope="library"))["total"] == 2   # a0 and a1, not hidden


def test_feed_hits_in_the_tool_result(drv, tmp_path, monkeypatch):
    from services.feed.store import Candidate, get_store, reset

    monkeypatch.setenv("PAPER_FEED", "true")
    monkeypatch.setenv("PAPER_FEED_DIR", str(tmp_path / "feed"))
    reset()
    try:
        st = get_store()
        c = Candidate(id="arxiv:2611.00001", source="arxiv", ext_id="2611.00001", title="A feed paper", abstract="Feed abstract.",
                      published="2026-11-17T10:00:00+00:00", categories=["cs.LG"], authors=["Bo Sample"],
                      url="https://example.invalid/1")
        st.upsert_candidates([c])
        st.set_embeddings({c.id: topic_vec(1, c.id)})
        st.set_label("alice", c.id, 1)
        drv.add("a0", 1)
        res = json.loads(call("find_similar_papers", text=TEXT, scope="both", since="2026-11-01"))
        feed_hit = next(h for h in res["hits"] if h["source"] == "feed")
        assert feed_hit["url"] == "https://example.invalid/1" and feed_hit["in_library"] is False
        assert feed_hit["my_label"] == 1 and feed_hit["published"].startswith("2026-11-17")
        assert [h["id"] for h in res["hits"] if h["source"] == "library"] == []     # a0 is from 2024: before 'since'
    finally:
        reset()


def test_clear_messages_instead_of_stack_traces(drv, monkeypatch):
    assert json.loads(call("find_similar_papers", text="short")) == {
        "error": "text must have at least 20 characters: a title and a paragraph work best"}
    assert "scope must be" in json.loads(call("find_similar_papers", text=TEXT, scope="nowhere"))["error"]
    assert "since must be" in json.loads(call("find_similar_papers", text=TEXT, since="soon"))["error"]
    # nothing indexed yet
    res = json.loads(call("find_similar_papers", text=TEXT, scope="library"))
    assert res["available"] is False and "not been built" in res["reason"] and res["hits"] == []
    # the feed asked for on an instance without it
    monkeypatch.delenv("PAPER_FEED", raising=False)
    assert "not enabled" in json.loads(call("find_similar_papers", text=TEXT, scope="feed"))["error"]
    # a database that is down
    import db.connection
    drv.add("a0", 1)

    def down():
        raise ConnectionError("connection refused")
    monkeypatch.setattr(db.connection, "get_driver", down)
    out = json.loads(call("find_similar_papers", text=TEXT, scope="library"))
    assert out["error"].startswith("similarity search failed (ConnectionError)") and "Traceback" not in json.dumps(out)


def test_the_embedder_being_unavailable_is_reported(drv, monkeypatch):
    from services.conferences import embedder

    drv.add("a0", 1)
    monkeypatch.setattr(embedder, "ready", lambda: False)
    monkeypatch.setattr(embedder, "remote_url", lambda: "")
    res = json.loads(call("find_similar_papers", text=TEXT, scope="library"))
    assert res["available"] is False and "still loading" in res["reason"]


def test_arguments_are_clamped(drv):
    for i in range(3):
        drv.add(f"a{i}", 1)
    assert json.loads(call("find_similar_papers", text=TEXT, scope=" LIBRARY ", k=500))["total"] == 3
    assert json.loads(call("find_similar_papers", text=TEXT, scope="library", k=-4))["total"] == 1
    assert json.loads(call("find_similar_papers", text=TEXT, scope="library", min_score=5))["total"] == 0


def test_the_tools_read_the_stores_in_follow_mode(drv, monkeypatch):
    """The MCP server never writes: the tool must open the namespaces read-only."""
    from services import similar_search as ss

    drv.add("a0", 1)
    seen = {}
    real = ss._library_store

    def spy(follow):
        seen["follow"] = follow
        st, why = real(follow)
        seen["readonly"] = getattr(st, "_follow", None)
        return st, why

    monkeypatch.setattr(ss, "_library_store", spy)
    assert json.loads(call("find_similar_papers", text=TEXT, scope="library"))["available"] is True
    assert seen == {"follow": True, "readonly": True}


def test_the_default_user_is_the_mcp_user(monkeypatch):
    from config import settings
    from services.auth import set_request_user, reset_request_user
    from tools import similarity_tools

    tok = set_request_user(None)
    try:
        assert similarity_tools._user() == settings.default_user_name
    finally:
        reset_request_user(tok)
