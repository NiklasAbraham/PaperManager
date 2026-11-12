"""The MCP server's lean paths: startup imports, tool definitions, compact results,
query vectors from the backend, add_to_project, search_papers rows, list_highlights.

Each desk chat (and each subagent) starts its own `python mcp_server.py` and carries every
tool definition in its context, so these guard what that costs. Neo4j tests create and
remove their own nodes, like test_mcp_tools.py.
"""
import asyncio
import inspect
import json
import os
import subprocess
import sys
import uuid

import numpy as np
import pytest

from db.connection import get_driver
from db.queries.papers import create_paper, delete_paper
from db.queries.projects import create_project, delete_project


def _tools():
    from mcp_server import mcp
    return mcp, asyncio.run(mcp.list_tools())


def _call(mcp, name, **kw):
    res = asyncio.run(mcp.call_tool(name, kw))
    blocks = res[0] if isinstance(res, tuple) else res
    assert len(blocks) == 1, f"{name}: one text block expected, got {len(blocks)}"
    return blocks[0].text


# ── startup ───────────────────────────────────────────────────────────────────

def test_mcp_server_import_skips_heavy_sdks():
    """anthropic + openai (~2 s), torch/transformers and pypdf load only when a tool needs them."""
    code = ("import sys, mcp_server; "
            "print(','.join(m for m in ('anthropic','openai','torch','transformers','pypdf') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1:] in ([], [""]), f"imported at startup: {out.stdout}"


def test_mcp_server_points_query_embedding_at_the_backend():
    import mcp_server  # noqa: F401 — sets the default
    assert os.environ["PM_EMBED_URL"].endswith("/conferences/embed")


# ── tool definitions ─────────────────────────────────────────────────────────

def test_tool_definitions_are_tidy_and_within_budget():
    _, tools = _tools()
    assert len(tools) >= 42
    total = 0
    for t in tools:
        assert t.description and t.description == inspect.cleandoc(t.description), t.name
        assert "title" not in t.inputSchema, t.name
        for pname, prop in (t.inputSchema.get("properties") or {}).items():
            assert "title" not in prop, f"{t.name}.{pname}"
        total += len(t.description) + len(json.dumps(t.inputSchema, separators=(",", ":")))
    # 22,980 characters before the trim (Nov 2026); every chat loads all of them.
    assert total < 18500, total


def test_parameter_named_title_survives():
    _, tools = _tools()
    schema = next(t for t in tools if t.name == "add_paper_metadata").inputSchema
    assert "title" in schema["properties"] and "title" in schema["required"]


@pytest.mark.parametrize("tool, phrases", [
    ("library_lookup", ["bioRxiv", "200", "paired by index", "reference_stub"]),
    ("library_add", ["dry_run", "create_project", "papers.json", "arxiv", "same_as"]),
    ("library_search", ["Quote a phrase", "matched_in", "project"]),
    ("upload_pdf", ["HOST_IMPORT_ROOT", "arXiv", "Unpaywall", "metadata-only"]),
    ("find_in_paper", ["read_paper_text", "offsets"]),
    ("merge_papers", ["dry_run"]),
    ("delete_paper", ["confirm"]),
    ("add_to_project", ["name", "already"]),
    ("conference_topic", ["all", "library_paper_id"]),
])
def test_usage_guidance_kept(tool, phrases):
    _, tools = _tools()
    desc = next(t for t in tools if t.name == tool).description
    for p in phrases:
        assert p in desc, f"{tool}: '{p}' dropped from the description"


def test_exclude_env_hides_tools(monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from tools import paper_tools
    from tools._compact import tidy

    monkeypatch.setenv("PAPERMANAGER_MCP_EXCLUDE", "get_random_paper, rate_paper,no_such_tool")
    mcp = FastMCP("t")
    paper_tools.register(mcp)
    tidy(mcp)
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "get_random_paper" not in names and "rate_paper" not in names
    assert "search_papers" in names


def test_json_tool_sends_one_compact_block():
    from mcp.server.fastmcp import FastMCP

    from tools._compact import json_tool

    mcp = FastMCP("t")

    @json_tool(mcp)
    def thing(n: int = 2) -> dict:
        """Doc."""
        return {"n": n, "nested": {"a": [1, 2]}, "text": "äö"}

    listed = asyncio.run(mcp.list_tools())[0]
    assert listed.outputSchema is None and listed.inputSchema["properties"]["n"]["default"] == 2
    text = _call(mcp, "thing", n=3)
    assert text == '{"n":3,"nested":{"a":[1,2]},"text":"äö"}'


# ── query vectors from the backend ───────────────────────────────────────────

class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


@pytest.fixture
def embedder(monkeypatch):
    from services.conferences import embedder as e

    monkeypatch.setattr(e, "_model", None)
    monkeypatch.setenv("PM_EMBED_URL", "http://127.0.0.1:1/conferences/embed")
    local = []
    monkeypatch.setattr(e, "embed", lambda texts, **kw: local.append(texts) or np.ones((len(texts), e.DIM), np.float32))
    e._local_calls = local
    return e


def test_remote_vector_skips_the_local_model(embedder, monkeypatch):
    import httpx

    sent = {}

    def post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, auth=headers.get("Authorization", ""))
        return _Resp(200, {"model": embedder.MODEL, "dim": embedder.DIM, "vector": [0.5] * embedder.DIM})

    monkeypatch.setattr(httpx, "post", post)
    v = embedder.embed_query("diffusion guidance")
    assert v.shape == (embedder.DIM,) and float(v[0]) == 0.5
    assert embedder._local_calls == []
    assert sent["json"]["text"] == embedder.query_text("diffusion guidance")  # prefix added once, here
    assert sent["auth"].startswith("Bearer ")


@pytest.mark.parametrize("resp", [
    _Resp(404), _Resp(503),
    _Resp(200, {"model": "other/model", "dim": 384, "vector": [0.0] * 384}),
    _Resp(200, {"model": "BAAI/bge-small-en-v1.5", "dim": 384, "vector": [0.0] * 3}),
    ConnectionError("refused"),
])
def test_remote_failure_falls_back_to_local(embedder, monkeypatch, resp):
    import httpx

    def post(*a, **kw):
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(httpx, "post", post)
    v = embedder.embed_query("diffusion guidance")
    assert v.shape == (embedder.DIM,)
    assert embedder._local_calls == [[embedder.query_text("diffusion guidance")]]


def test_no_remote_without_env(embedder, monkeypatch):
    import httpx

    monkeypatch.delenv("PM_EMBED_URL")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no remote call expected"))
    embedder.embed_query("x")
    assert len(embedder._local_calls) == 1


def test_semantic_query_runs_with_remote_and_no_local_model(embedder, monkeypatch):
    from services.library_search import semantic

    monkeypatch.setattr(semantic, "_ids", ["a", "b"])
    monkeypatch.setattr(semantic, "_emb", np.array([[1.0] + [0.0] * 383, [0.0, 1.0] + [0.0] * 382], np.float32))
    monkeypatch.setattr(embedder, "embed_query", lambda q: np.array([0.0, 1.0] + [0.0] * 382, np.float32))
    assert semantic.query("x", k=2)[0][0] == "b"
    monkeypatch.delenv("PM_EMBED_URL")
    assert semantic.query("x", k=2) == []  # the backend never loads the model in a request


def test_ensure_loaded_does_not_load_the_model_with_remote(embedder, monkeypatch):
    from services.library_search import semantic

    monkeypatch.setattr(semantic, "_ids", ["a"])
    semantic.ensure_loaded()
    assert embedder._local_calls == []


async def test_embed_route(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from main import app
    from services.conferences import embedder as e

    monkeypatch.setattr(e, "_model", None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/conferences/embed", json={"text": "x"})
        assert r.status_code == 503
        monkeypatch.setattr(e, "_model", object())
        monkeypatch.setattr(e, "embed", lambda texts, **kw: np.full((len(texts), e.DIM), 0.25, np.float32))
        r = await c.post("/conferences/embed", json={"text": "Represent this: x"})
    assert r.status_code == 200
    d = r.json()
    assert d["model"] == e.MODEL and d["dim"] == e.DIM and len(d["vector"]) == e.DIM and d["vector"][0] == 0.25


# ── add_to_project, search_papers, list_highlights (Neo4j) ───────────────────

@pytest.fixture
def lib():
    from services.auth import reset_request_user, set_request_user

    token = set_request_user("niklas")  # the admin sees every project (visibility rules)
    d = get_driver()
    tag = uuid.uuid4().hex[:8]
    paper = create_paper(d, {"title": f"Lean MCP test paper {tag}", "year": 2026,
                             "summary": "S" * 3000, "abstract": "A" * 2000})
    proj = create_project(d, {"name": f"Lean MCP project {tag}"})
    with d.session() as s:
        s.run("MATCH (p:Paper {id: $id}) CREATE (p)-[:HAS_ANNOTATION]->(:Annotation "
              "{id: $aid, highlighted_text: $t, note: 'mine', page_number: 1, created_at: '2099-01-01'})",
              id=paper["id"], aid=f"ann-{tag}", t="H" * 2000).consume()
    yield {"paper": paper, "project": proj, "tag": tag}
    with d.session() as s:
        s.run("MATCH (a:Annotation {id: $aid}) DETACH DELETE a", aid=f"ann-{tag}").consume()
    delete_paper(d, paper["id"])
    delete_project(d, proj["id"])
    reset_request_user(token)


def test_add_to_project_reports_what_happened(lib):
    mcp, _ = _tools()
    pid, prj = lib["paper"]["id"], lib["project"]
    r = json.loads(_call(mcp, "add_to_project", paper_id=pid, project_id=prj["id"]))
    assert r["status"] == "ok" and r["linked"] == "linked" and r["paper_id"] == pid
    r = json.loads(_call(mcp, "add_to_project", paper_id=pid, project_id=prj["name"].upper()))
    assert r["status"] == "ok" and r["linked"] == "already" and r["project_id"] == prj["id"]
    r = json.loads(_call(mcp, "add_to_project", paper_id=pid, project_id="no-such-project-" + lib["tag"]))
    assert r["status"] == "error" and "Project not found" in r["error"]
    r = json.loads(_call(mcp, "add_to_project", paper_id="no-such-paper", project_id=prj["id"]))
    assert r["status"] == "error" and "Paper not found" in r["error"]


def test_add_to_project_respects_project_membership(lib):
    from services.auth import reset_request_user, set_request_user

    mcp, _ = _tools()
    token = set_request_user("someone-else")
    try:
        r = json.loads(_call(mcp, "add_to_project", paper_id=lib["paper"]["id"], project_id=lib["project"]["id"]))
    finally:
        reset_request_user(token)
    assert r["status"] == "error"


def test_search_papers_rows_are_short(lib):
    mcp, _ = _tools()
    rows = json.loads(_call(mcp, "search_papers", query=f"Lean MCP test paper {lib['tag']}", limit=5))
    row = next(r for r in rows if r["id"] == lib["paper"]["id"])
    assert row["title"].startswith("Lean MCP test paper") and row["year"] == 2026
    assert row["url"].endswith("/paper/" + lib["paper"]["id"])
    assert "summary" not in row and "abstract" not in row
    assert len(rows) <= 5


def test_list_highlights_cuts_long_texts(lib):
    mcp, _ = _tools()
    r = json.loads(_call(mcp, "list_highlights", paper_id=lib["paper"]["id"]))
    h = r["highlights"][0]
    assert r["count"] == 1 and h["truncated"] is True and len(h["text"]) == 801
    ctx = json.loads(_call(mcp, "get_paper_context", paper_id=lib["paper"]["id"]))
    assert len(ctx["highlights"][0]["text"]) == 2000  # full text where one paper is read


def test_read_tools_return_compact_json_with_the_keys_the_desk_reads(lib):
    mcp, _ = _tools()
    pid = lib["paper"]["id"]
    for name, kw, keys in [
        ("get_paper_context", {"paper_id": pid}, {"paper_id", "title", "url", "text_chars", "highlights", "note"}),
        ("read_paper_text", {"paper_id": pid}, {"paper_id", "title", "url", "offset", "end", "total_chars"}),
        ("find_in_paper", {"paper_id": pid, "query": "x"}, {"paper_id", "title", "url", "total_chars", "hits"}),
        ("get_paper_detail", {"paper_id": pid}, {"id", "title", "year"}),
        ("list_notes", {}, {"count", "notes"}),
    ]:
        text = _call(mcp, name, **kw)
        assert "\n  " not in text, f"{name} is indented"
        assert keys <= set(json.loads(text)), name
