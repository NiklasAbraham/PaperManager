"""Knowledge Chat tool trace: one streamed model round, richer steps, persisted
trace, Stop, Retry, and small molecules for the structure cards.

No database, model or network is used: the Anthropic client is a script, the query
layer is patched, and the structure fetch is replaced.
"""
import json
import sys
import threading
import time
import types
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import db.queries.conversations as conv_q
import routers.knowledge_chat as kc
import services.ai as ai
import services.structures as st
from main import app
from services.auth import get_current_user

P1 = "11111111-1111-4111-8111-111111111111"
P2 = "22222222-2222-4222-8222-222222222222"


# ── A scripted Anthropic client ──────────────────────────────────────────────

def text_msg(text):
    return SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


def tool_msg(text, name, tool_input, tool_id="tu1"):
    blocks = ([SimpleNamespace(type="text", text=text)] if text else []) + [
        SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)
    ]
    return SimpleNamespace(stop_reason="tool_use", content=blocks, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class FakeClient:
    """``messages.stream`` hands out the scripted rounds in order and records its arguments."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):  # the old non-streaming path must not be used any more
        raise AssertionError("messages.create must not be called")

    @contextmanager
    def stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        message = self.rounds.pop(0)
        texts = [b.text for b in message.content if b.type == "text"]
        yield SimpleNamespace(text_stream=iter(texts), get_final_message=lambda: message)


@pytest.fixture
def fake_client(monkeypatch):
    def install(rounds):
        client = FakeClient(rounds)
        monkeypatch.setattr(ai, "_personal_client", lambda: client)
        return client
    return install


def run_chat(driver=object(), **kwargs):
    return list(ai.knowledge_chat_stream(
        question="Q?", history=[], papers=[], model="claude", use_web=False, driver=driver, **kwargs))


# ── _stream_round / knowledge_chat_stream ────────────────────────────────────

def test_stream_round_yields_text_then_the_final_message():
    client = FakeClient([text_msg("Hello")])
    out = list(ai._stream_round(client, model="m", system="s", messages=[], tools=[]))
    assert out[0] == ("text", "Hello") and out[1][0] == "message" and out[1][1].stop_reason == "end_turn"
    assert "tools" in client.calls[0]


def test_one_request_and_tokens_when_no_tool_is_called(fake_client):
    client = fake_client([text_msg("The answer.")])
    events = run_chat()
    assert [e for e in events if e["type"] == "token"] == [{"type": "token", "text": "The answer."}]
    assert all(e["type"] != "interim" for e in events)
    assert len(client.calls) == 1  # no second request to stream what was already computed


def test_tool_round_streams_prose_then_interim_step_and_final_answer(fake_client, monkeypatch):
    rows = [{"id": P1, "title": "Attention", "year": 2017}]
    monkeypatch.setattr(ai, "_run_cypher_safe", lambda d, q: rows)
    client = fake_client([
        tool_msg("Let me check the graph.", "run_cypher", {"query": "MATCH (p:Paper) RETURN p.id AS id, p.title AS title",
                                                           "description": "Find papers"}),
        text_msg("Final answer."),
    ])
    events = run_chat()
    types_ = [e["type"] for e in events]
    assert types_ == ["token", "interim", "step", "token"]
    assert events[0]["text"] == "Let me check the graph." and events[3]["text"] == "Final answer."
    step = events[2]
    assert step["kind"] == "cypher" and step["tool"] == "run_cypher" and step["is_error"] is False
    assert step["input"]["description"] == "Find papers"
    assert step["result"] == json.dumps(rows)
    assert step["papers"] == [{"id": P1, "title": "Attention", "year": 2017}]
    assert step["count"] == 1 and step["cypher"].startswith("MATCH")
    # The second request carries the assistant turn and the tool result.
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-1]["content"][0]["tool_use_id"] == "tu1"


def test_no_interim_when_the_tool_round_streamed_no_text(fake_client, monkeypatch):
    monkeypatch.setattr(ai, "_run_cypher_safe", lambda d, q: [])
    fake_client([tool_msg("", "run_cypher", {"query": "RETURN 1", "description": "d"}), text_msg("Done.")])
    assert [e["type"] for e in run_chat()] == ["step", "token"]


def test_unknown_tool_breaks_the_loop(fake_client):
    client = fake_client([tool_msg("", "nonsense", {}), text_msg("never reached")])
    events = run_chat()
    assert events == [] and len(client.calls) == 1


def test_rounds_are_capped_and_the_last_round_takes_no_tools(fake_client, monkeypatch):
    monkeypatch.setattr(ai, "_run_cypher_safe", lambda d, q: [])
    rounds = [tool_msg("", "run_cypher", {"query": "RETURN 1", "description": "d"}, tool_id=f"t{i}")
              for i in range(ai.MAX_TOOL_ROUNDS - 1)] + [text_msg("Out of rounds.")]
    client = fake_client(rounds)
    events = run_chat()
    assert len(client.calls) == ai.MAX_TOOL_ROUNDS
    assert client.calls[-1]["tool_choice"] == {"type": "none"}
    assert client.calls[0]["tool_choice"] is ai.anthropic.NOT_GIVEN
    assert events[-1] == {"type": "token", "text": "Out of rounds."}


def test_without_a_driver_no_tools_are_offered(fake_client):
    client = fake_client([text_msg("hi")])
    run_chat(driver=None)
    assert client.calls[0]["tools"] is ai.anthropic.NOT_GIVEN


def test_web_presearch_is_a_step_with_links(fake_client, monkeypatch):
    monkeypatch.setattr(ai, "_web_presearch", lambda q, h: (
        "1. **A**\n   URL: https://a.example/x", ["https://a.example/x", "https://b.example"], ["query one"]))
    fake_client([text_msg("ok")])
    events = list(ai.knowledge_chat_stream("Q?", [], [], model="claude", use_web=True, driver=None))
    step = next(e for e in events if e["type"] == "step")
    assert step["kind"] == "web" and step["tool"] == "web_presearch"
    assert step["input"] == {"queries": ["query one"]} and step["links"] == ["https://a.example/x", "https://b.example"]
    assert step["is_error"] is False and step["papers"] == []


def test_web_presearch_collects_urls_and_fetch_web_context_still_works(monkeypatch):
    import services.web_search as ws
    monkeypatch.setattr(ai, "_generate_search_queries", lambda q, h: ["a", "b"])
    monkeypatch.setattr(ws, "search_web", lambda query, max_results=5: [
        {"title": "T", "url": "https://x.example/1", "snippet": "s"},
        {"title": "T2", "url": "https://x.example/1", "snippet": ""}])
    text, urls, queries = ai._web_presearch("q", [])
    assert urls == ["https://x.example/1"] and queries == ["a", "b"] and "T" in text
    assert ai._fetch_web_context("q", []) == text


# ── execute_library_tool ─────────────────────────────────────────────────────

def test_run_cypher_attributes_papers_from_the_row_shapes(monkeypatch):
    rows = [
        {"id": P1, "title": "One", "year": 2020},
        {"p.id": P2, "p.title": "Two", "p.year": 2021},
        {"paper_id": P1, "title": "One again"},
        {"p": {"id": "33333333-3333-4333-8333-333333333333", "title": "Node", "year": 1999, "abstract": "x"}},
        {"id": "not-a-uuid", "title": "Dropped"},
        {"id": "44444444-4444-4444-8444-444444444444", "name": "Person, no title"},
    ]
    monkeypatch.setattr(ai, "_run_cypher_safe", lambda d, q: rows)
    step, content = ai.execute_library_tool("run_cypher", {"query": "MATCH (p) RETURN p", "description": "d"}, object())
    assert [p["id"] for p in step["papers"]] == [P1, P2, "33333333-3333-4333-8333-333333333333"]
    assert step["papers"][1] == {"id": P2, "title": "Two", "year": 2021}
    assert step["papers"][2]["year"] == 1999
    assert json.loads(content) == rows


def test_run_cypher_caps_papers_at_thirty(monkeypatch):
    rows = [{"id": f"{i:08d}-0000-4000-8000-000000000000", "title": f"T{i}"} for i in range(45)]
    monkeypatch.setattr(ai, "_run_cypher_safe", lambda d, q: rows)
    step, _ = ai.execute_library_tool("run_cypher", {"query": "q", "description": "d"}, object())
    assert len(step["papers"]) == 30


def test_run_cypher_result_is_truncated_with_a_note(monkeypatch):
    rows = [{"x": "a" * 100} for _ in range(100)]
    monkeypatch.setattr(ai, "_run_cypher_safe", lambda d, q: rows)
    step, content = ai.execute_library_tool("run_cypher", {"query": "q", "description": "d"}, object())
    assert step["result"].startswith(content[:4000])
    assert step["result"].endswith(f"\n… ({len(content) - 4000} more characters)")
    assert len(step["result"]) < len(content)


def test_run_cypher_error_row_and_missing_driver_are_errors(monkeypatch):
    monkeypatch.setattr(ai, "_run_cypher_safe", lambda d, q: [{"error": "bad syntax"}])
    step, _ = ai.execute_library_tool("run_cypher", {"query": "q", "description": "d"}, object())
    assert step["is_error"] is True and step["count"] is None and step["papers"] == []
    step, content = ai.execute_library_tool("run_cypher", {"query": "q", "description": "d"}, None)
    assert step["is_error"] is True and "No DB driver" in content


def test_unknown_tool_is_none():
    assert ai.execute_library_tool("web_fetch", {}, object()) is None


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        rows = self.rows
        return SimpleNamespace(single=lambda: rows.pop(0) if rows else None)


class FakeDriver:
    def __init__(self, rows):
        self.session_ = FakeSession(rows)

    def session(self):
        return self.session_


def test_load_full_text_names_the_paper(monkeypatch):
    driver = FakeDriver([{"raw_text": "full text", "title": "Attention", "year": 2017}])
    step, content = ai.execute_library_tool("load_full_text", {"paper_id": P1, "reason": "r"}, driver)
    assert content == "full text"
    assert step["papers"] == [{"id": P1, "title": "Attention", "year": 2017}]
    assert step["tool"] == "load_full_text" and step["is_error"] is False


def test_load_full_text_keeps_the_id_when_the_lookup_fails():
    step, _ = ai.execute_library_tool("load_full_text", {"paper_id": P1, "reason": "r"}, FakeDriver([None]))
    assert step["papers"] == [{"id": P1, "title": None, "year": None}]
    step, _ = ai.execute_library_tool("load_full_text", {"paper_id": P1, "reason": "r"}, None)
    assert step["is_error"] is True and step["papers"][0]["id"] == P1


def test_list_figures_reports_figures_and_the_paper(monkeypatch):
    import db.queries.figures as figs
    monkeypatch.setattr(figs, "list_figures", lambda d, pid: [
        {"id": "f1", "figure_number": 3, "page_number": 4, "caption": "A curve", "drive_file_id": "d1"},
        {"id": "f2", "figure_number": 4, "page_number": 5, "caption": "No file", "drive_file_id": None},
    ])
    driver = FakeDriver([{"title": "Attention", "year": 2017}])
    step, content = ai.execute_library_tool("list_figures", {"paper_id": P1}, driver)
    assert step["figures"] == [{"image_url": f"/papers/{P1}/figures/f1/image", "caption": "A curve", "figure_number": 3}]
    assert step["papers"] == [{"id": P1, "title": "Attention", "year": 2017}]
    assert step["count"] == 1 and step["kind"] == "figures" and step["is_error"] is False
    assert json.loads(content)[0]["page"] == 4


def test_semantic_search_papers_come_from_the_rows(monkeypatch):
    import services.embeddings as emb
    monkeypatch.setattr(emb, "embed_text", lambda q: [0.1])
    rows = [SimpleNamespace(items=lambda: [("id", P1), ("title", "One"), ("year", 2020), ("score", 0.9)])]
    driver = FakeDriver([])
    driver.session_.run = lambda *a, **k: rows
    step, _ = ai.execute_library_tool("semantic_search", {"query": "attention", "description": "d"}, driver)
    assert step["papers"] == [{"id": P1, "title": "One", "year": 2020}] and step["tool"] == "semantic_search"


# ── Claude Code path: interim and WebSearch ──────────────────────────────────

def _fake_sdk(script):
    """A stand-in for claude_agent_sdk whose ``query`` replays *script*."""
    class Box:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class StreamEvent(Box): pass
    class ToolUseBlock(Box): pass
    class ToolResultBlock(Box): pass
    class AssistantMessage(Box): pass
    class UserMessage(Box): pass
    class ResultMessage(Box): pass

    async def query(prompt, options):
        for make in script:
            yield make(locals_ns)

    locals_ns = SimpleNamespace(
        StreamEvent=StreamEvent, ToolUseBlock=ToolUseBlock, ToolResultBlock=ToolResultBlock,
        AssistantMessage=AssistantMessage, UserMessage=UserMessage, ResultMessage=ResultMessage)
    mod = types.ModuleType("claude_agent_sdk")
    mod.ClaudeAgentOptions = Box
    mod.create_sdk_mcp_server = lambda **kw: None
    mod.query = query
    for name in ("StreamEvent", "ToolUseBlock", "ToolResultBlock", "AssistantMessage", "UserMessage", "ResultMessage"):
        setattr(mod, name, getattr(locals_ns, name))
    return mod


def _start(kind):
    return lambda ns: ns.StreamEvent(event={"type": "content_block_start", "content_block": {"type": kind}})


def _delta(text):
    return lambda ns: ns.StreamEvent(event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})


def test_claude_code_interim_websearch_step_and_text_separators(monkeypatch):
    import asyncio
    import services.claude_code_chat as cc

    search_result = (
        'Web search results for query: "foo"\n\nLinks: [{"title": "A", "url": "https://a.example/page"},'
        ' {"title": "B", "url": "https://b.example/x?y=1"}, {"title": "A again", "url": "https://a.example/page"}]'
    )
    script = [
        _start("text"), _delta("Look"), _delta(" first."),
        _start("text"), _delta("Second block."),            # two text blocks, no tool: blank line between
        _start("tool_use"),                                  # interim: the prose so far preceded a tool
        lambda ns: ns.AssistantMessage(content=[ns.ToolUseBlock(id="w1", name="WebSearch", input={"query": "foo"})]),
        lambda ns: ns.UserMessage(content=[ns.ToolResultBlock(
            tool_use_id="w1", content=[{"type": "text", "text": search_result}], is_error=False)]),
        _start("text"), _delta("The answer."),               # after a tool: no separator
    ]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", _fake_sdk(script))
    events = []
    asyncio.run(cc._run("sys", "prompt", events.append, True, []))
    assert [e["type"] for e in events] == ["token", "token", "token", "token", "interim", "step", "token"]
    assert "".join(e["text"] for e in events[:4]) == "Look first.\n\nSecond block."
    step = events[5]
    assert step["kind"] == "web" and step["tool"] == "WebSearch" and step["input"] == {"query": "foo"}
    assert step["links"] == ["https://a.example/page", "https://b.example/x?y=1"]
    assert "Links:" in step["result"] and step["is_error"] is False and step["papers"] == []
    assert events[6]["text"] == "The answer."


def test_claude_code_search_without_result_is_flushed_at_the_end(monkeypatch):
    import asyncio
    import services.claude_code_chat as cc

    script = [lambda ns: ns.AssistantMessage(content=[ns.ToolUseBlock(id="w1", name="WebSearch", input={"query": "q"})])]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", _fake_sdk(script))
    events = []
    asyncio.run(cc._run("sys", "prompt", events.append, True, []))
    assert len(events) == 1 and events[0]["tool"] == "WebSearch" and events[0]["links"] == []


def test_claude_code_urls_are_deduplicated_and_capped():
    import services.claude_code_chat as cc
    text = " ".join(f"https://x.example/{i}" for i in range(20)) + " https://x.example/0"
    links = cc._urls_in(text)
    assert len(links) == 12 and len(set(links)) == 12


# ── Router: persisted trace, interim, Stop, Retry ────────────────────────────

class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, *a, **k):
        return []


class _Driver:
    def session(self):
        return _Session()


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[get_current_user] = lambda: "tester"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def db(monkeypatch):
    """The router's query layer, patched: records what is saved."""
    saved = SimpleNamespace(messages=[], errors=[], deleted=[], delete_result=True)

    def add_message(driver, conv_id, role, content, paper_ids, tokens_used=0, steps=None, stopped=False):
        row = {"id": f"{role}-{len(saved.messages)}", "role": role, "content": content, "steps": steps, "stopped": stopped}
        saved.messages.append(row)
        return row

    def delete_last_turn(driver, conv_id, mid):
        saved.deleted.append((conv_id, mid))
        return saved.delete_result

    monkeypatch.setattr(kc, "get_driver", lambda: _Driver())
    monkeypatch.setattr(kc, "create_conversation", lambda d, title: {"id": "c1"})
    monkeypatch.setattr(kc, "add_message", add_message)
    monkeypatch.setattr(kc, "delete_last_turn", delete_last_turn)
    monkeypatch.setattr(kc, "set_branch_label_if_empty", lambda *a: None)
    monkeypatch.setattr(kc, "set_message_error", lambda d, mid, err: saved.errors.append((mid, err)))
    monkeypatch.setattr(kc, "get_paper_context_snippets", lambda d, pid: {})
    monkeypatch.setattr(kc, "_fallback_all_papers", lambda session, question="": [
        {"id": P1, "title": "Scope paper", "year": 2020, "abstract": "a", "summary": "s"}])
    return saved


def parse_sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


async def test_router_persists_trace_and_resets_the_answer_on_interim(client, db, monkeypatch):
    cypher_step = {"type": "step", "kind": "cypher", "description": "Find", "cypher": "MATCH", "count": 1,
                   "tool": "run_cypher", "input": {"query": "MATCH"}, "result": "[]", "is_error": False,
                   "papers": [{"id": P1, "title": "One", "year": 2020}]}

    def model(**kw):
        yield {"type": "token", "text": "Let me look."}
        yield {"type": "interim"}
        yield cypher_step
        yield {"type": "token", "text": "The "}
        yield {"type": "token", "text": "answer."}

    monkeypatch.setattr(kc, "knowledge_chat_stream", model)
    resp = await client.post("/knowledge-chat/stream", json={"question": "Q?", "use_web": False})
    events = parse_sse(resp.text)
    done = events[-1]
    assert done["type"] == "done" and done["conversation_id"] == "c1" and done["message_id"] == "assistant-1"
    assert any(e["type"] == "interim" for e in events)

    assistant = db.messages[1]
    assert assistant["content"] == "The answer."          # only the text after the last interim
    steps = assistant["steps"]
    assert [s["kind"] for s in steps] == ["scope", "text", "cypher"]
    assert steps[0]["description"].startswith("No scope given")
    assert steps[1] == {"kind": "text", "description": "", "text": "Let me look."}
    assert steps[2]["tool"] == "run_cypher" and steps[2]["papers"][0]["id"] == P1
    # The filler steps went over the wire but are not stored.
    descriptions = [e.get("description", "") for e in events if e["type"] == "step"]
    assert any(d.startswith("Parsing @mentions") for d in descriptions)
    assert any(d.startswith("Sending to Claude") for d in descriptions)
    assert not any(s.get("description", "").startswith(("Parsing", "Sending")) for s in steps)


async def test_mention_and_attach_steps_carry_scope_fields(client, db, monkeypatch):
    class AttachSession(_Session):
        def run(self, query, **k):
            return [{"id": P2, "title": "Attached", "year": 2022, "abstract": None, "summary": None}] if "UNWIND" in query else []

    class AttachDriver:
        def session(self):
            return AttachSession()

    monkeypatch.setattr(kc, "get_driver", lambda: AttachDriver())
    monkeypatch.setattr(kc, "_fetch_papers_for_mention", lambda s, t, v: (
        [{"id": P1, "title": "Tagged", "year": 2019, "abstract": "", "summary": ""}], "MATCH ...", f"Fetching {t} '{v}'"))
    monkeypatch.setattr(kc, "knowledge_chat_stream", lambda **kw: iter([{"type": "token", "text": "ok"}]))
    resp = await client.post("/knowledge-chat/stream", json={
        "question": "About @tag:rl please", "use_web": False, "paper_ids": [P2]})
    steps = db.messages[1]["steps"]
    mention, attach = steps[0], steps[1]
    assert mention["kind"] == "scope" and mention["tool"] == "mention"
    assert mention["input"] == {"type": "tag", "value": "rl"}
    assert mention["papers"] == [{"id": P1, "title": "Tagged", "year": 2019}]
    assert attach["kind"] == "attach" and attach["tool"] == "attach" and attach["papers"][0]["id"] == P2
    assert parse_sse(resp.text)[-1]["type"] == "done"


def test_cap_trace_drops_oldest_results_first():
    steps = [{"kind": "cypher", "result": "x" * 60_000, "n": i} for i in range(6)]
    capped = kc._cap_trace(steps)
    assert len(json.dumps(capped).encode()) <= 200_000
    assert "result" not in capped[0] and "result" in capped[-1]
    assert "result" in steps[0]  # the input is not modified
    small = [{"kind": "cypher", "result": "x"}]
    assert kc._cap_trace(small) == small


def test_stop_ends_a_running_producer_and_saves_the_partial_answer(db, monkeypatch):
    def slow(**kw):
        for i in range(500):
            time.sleep(0.01)
            yield {"type": "token", "text": "x"}

    monkeypatch.setattr(kc, "knowledge_chat_stream", slow)
    events = []
    for raw in kc._stream(kc.KnowledgeChatRequest(question="Q?", use_web=False)):
        if raw.startswith("data: "):
            event = json.loads(raw[6:])
            events.append(event)
            if event["type"] == "conversation":
                uid = event["user_message_id"]
            if event["type"] == "token" and len([e for e in events if e["type"] == "token"]) == 3:
                assert kc.stop_answer(kc.StopBody(user_message_id=uid)) == {"stopped": True}
    done = events[-1]
    assert done["type"] == "done" and done["stopped"] is True and done["message_id"] == "assistant-1"
    saved = db.messages[1]
    assert saved["stopped"] is True and 3 <= len(saved["content"]) < 50
    assert saved["steps"] is not None
    assert uid not in kc._running


def test_stop_before_any_text_marks_the_question_stopped(db, monkeypatch):
    started = threading.Event()

    def silent(**kw):
        started.set()
        for _ in range(500):
            time.sleep(0.01)
            yield {"type": "status", "text": "thinking"}

    monkeypatch.setattr(kc, "knowledge_chat_stream", silent)
    events = []
    for raw in kc._stream(kc.KnowledgeChatRequest(question="Q?", use_web=False)):
        if raw.startswith("data: "):
            event = json.loads(raw[6:])
            events.append(event)
            if event["type"] == "conversation":
                kc.stop_answer(kc.StopBody(user_message_id=event["user_message_id"]))
    done = events[-1]
    assert done == {"type": "done", "conversation_id": "c1", "message_id": None, "stopped": True}
    assert db.errors == [(db.messages[0]["id"], "Stopped.")] and len(db.messages) == 1


async def test_stop_route_reports_whether_an_answer_was_running(client):
    event = threading.Event()
    kc._running["u1"] = event
    try:
        assert (await client.post("/knowledge-chat/stop", json={"user_message_id": "u1"})).json() == {"stopped": True}
        assert event.is_set()
        assert (await client.post("/knowledge-chat/stop", json={"user_message_id": "zz"})).json() == {"stopped": False}
    finally:
        kc._running.pop("u1", None)


async def test_the_registry_is_cleaned_up_after_a_normal_answer(client, db, monkeypatch):
    monkeypatch.setattr(kc, "knowledge_chat_stream", lambda **kw: iter([{"type": "token", "text": "a"}]))
    await client.post("/knowledge-chat/stream", json={"question": "Q?", "use_web": False})
    assert kc._running == {}


async def test_model_error_is_saved_on_the_question_and_cleans_up(client, db, monkeypatch):
    def boom(**kw):
        yield {"type": "token", "text": "a"}
        raise RuntimeError("model down")

    monkeypatch.setattr(kc, "knowledge_chat_stream", boom)
    events = parse_sse((await client.post("/knowledge-chat/stream", json={"question": "Q?", "use_web": False})).text)
    assert events[-1] == {"type": "error", "message": "model down"}
    assert db.errors and kc._running == {}


async def test_retry_deletes_the_last_turn_before_saving_the_new_question(client, db, monkeypatch):
    monkeypatch.setattr(kc, "knowledge_chat_stream", lambda **kw: iter([{"type": "token", "text": "a"}]))
    resp = await client.post("/knowledge-chat/stream", json={
        "question": "Q?", "use_web": False, "conversation_id": "c9", "retry_of": "old-user-msg"})
    assert db.deleted == [("c9", "old-user-msg")]
    assert parse_sse(resp.text)[-1]["type"] == "done"
    assert db.messages[0]["role"] == "user"


async def test_retry_of_an_older_question_is_refused(client, db, monkeypatch):
    db.delete_result = False
    called = []
    monkeypatch.setattr(kc, "knowledge_chat_stream", lambda **kw: called.append(1) or iter([]))
    resp = await client.post("/knowledge-chat/stream", json={
        "question": "Q?", "use_web": False, "conversation_id": "c9", "retry_of": "old"})
    assert parse_sse(resp.text) == [{"type": "error", "message": "Only the last question can be retried."}]
    assert db.messages == [] and called == []


async def test_retry_of_without_a_conversation_is_ignored(client, db, monkeypatch):
    monkeypatch.setattr(kc, "knowledge_chat_stream", lambda **kw: iter([{"type": "token", "text": "a"}]))
    await client.post("/knowledge-chat/stream", json={"question": "Q?", "use_web": False, "retry_of": "x"})
    assert db.deleted == []


# ── Query layer ──────────────────────────────────────────────────────────────

def test_message_row_parses_steps_json_and_pops_the_raw_field():
    steps = [{"kind": "cypher", "tool": "run_cypher"}, {"kind": "text", "description": "", "text": "hm"}]
    row = conv_q._message_row({"id": "m", "role": "assistant", "content": "a", "steps_json": json.dumps(steps),
                               "stopped": True})
    assert row["steps"] == steps and "steps_json" not in row and row["stopped"] is True
    assert conv_q._message_row({"id": "m"})["steps"] is None
    assert conv_q._message_row({"id": "m", "steps_json": "{not json"})["steps"] is None
    assert conv_q._message_row({"id": "m", "steps_json": '{"a": 1}'})["steps"] is None


def test_message_out_exposes_steps_and_stopped():
    from models.schemas import MessageOut
    out = MessageOut(id="m", role="assistant", content="a", created_at="x", steps=[{"kind": "text"}], stopped=True)
    assert out.steps == [{"kind": "text"}] and out.stopped is True
    assert MessageOut(id="m", role="user", content="q", created_at="x").steps is None


class _CaptureSession:
    def __init__(self, result):
        self.calls = []
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return self.result


class _CaptureDriver:
    def __init__(self, result):
        self.session_ = _CaptureSession(result)

    def session(self):
        return self.session_


def test_add_message_stores_steps_json_and_stopped():
    single = SimpleNamespace(single=lambda: {"m": {"id": "m1"}})
    driver = _CaptureDriver(single)
    msg = conv_q.add_message(driver, "c1", "assistant", "a", [], 1, steps=[{"kind": "text"}], stopped=True)
    first = driver.session_.calls[0][1]
    assert json.loads(first["extra"]["steps_json"]) == [{"kind": "text"}] and first["extra"]["stopped"] is True
    assert msg["paper_refs"] == []
    driver = _CaptureDriver(single)
    conv_q.add_message(driver, "c1", "user", "q", [], 1)
    assert driver.session_.calls[0][1]["extra"] == {}


def test_delete_last_turn_reports_what_the_query_deleted():
    driver = _CaptureDriver(SimpleNamespace(single=lambda: {"deleted": 2}))
    assert conv_q.delete_last_turn(driver, "c1", "u1") is True
    query, params = driver.session_.calls[0]
    assert params == {"cid": "c1", "mid": "u1"} and "role: 'user'" in query and "DETACH DELETE" in query
    driver = _CaptureDriver(SimpleNamespace(single=lambda: {"deleted": 0}))
    assert conv_q.delete_last_turn(driver, "c1", "u1") is False


# ── Structures: small molecules ──────────────────────────────────────────────

SDF = "ATP\n  ideal\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n    0.0 0.0 0.0 C   0\nM  END\n$$$$\n"


@pytest.mark.parametrize("bad", ["", "ABCDEF", "../x", "AT P", "A-B", None])
def test_ccd_rejects_malformed_codes_before_any_request(bad, monkeypatch):
    monkeypatch.setattr(st, "_get", lambda url: pytest.fail("no request for a bad code"))
    with pytest.raises(st.StructureError):
        st.ccd_ligand(bad)


@pytest.mark.parametrize("bad", ["", "12345678901", "abc", "-5", "1.5", "../1", None])
def test_pubchem_rejects_malformed_cids_before_any_request(bad, monkeypatch):
    monkeypatch.setattr(st, "_get", lambda url: pytest.fail("no request for a bad cid"))
    with pytest.raises(st.StructureError):
        st.pubchem_compound(bad)


def test_ccd_fetches_once_titles_the_sdf_with_the_code_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    calls = []

    def get(url):
        calls.append(url)
        return SimpleNamespace(status_code=200, text="some title\n" + SDF.split("\n", 1)[1])

    monkeypatch.setattr(st, "_get", get)
    first = st.ccd_ligand("atp")
    second = st.ccd_ligand("ATP")
    assert first == second and first["name"] == "ATP" and first["format"] == "sdf"
    assert first["data"].split("\n")[0] == "ATP" and "M  END" in first["data"]
    assert calls == ["https://files.rcsb.org/ligands/download/ATP_ideal.sdf"]


def test_pubchem_fetches_the_3d_conformer(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(st, "_get", lambda url: calls.append(url) or SimpleNamespace(status_code=200, text=SDF))
    out = st.pubchem_compound(2244)
    assert out == {"name": "CID 2244", "format": "sdf", "data": SDF}
    assert calls == ["https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/SDF?record_type=3d"]


def test_missing_ligand_and_html_pages_are_errors_and_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(st, "_get", lambda url: SimpleNamespace(status_code=404, text=""))
    with pytest.raises(st.StructureError, match="no ideal coordinates for ZZZ"):
        st.ccd_ligand("zzz")
    monkeypatch.setattr(st, "_get", lambda url: SimpleNamespace(status_code=200, text="<html>not found</html>"))
    with pytest.raises(st.StructureError):
        st.pubchem_compound("99")
    assert list(tmp_path.iterdir()) == []


async def test_structure_route_serves_ccd_and_pubchem_and_maps_errors(client, tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(st, "_get", lambda url: SimpleNamespace(status_code=200, text=SDF))
    ccd = await client.get("/knowledge-chat/structures", params={"ccd": "atp"})
    pub = await client.get("/knowledge-chat/structures", params={"pubchem": "2244"})
    assert ccd.json()["name"] == "ATP" and ccd.json()["format"] == "sdf"
    assert pub.json()["name"] == "CID 2244"
    assert (await client.get("/knowledge-chat/structures", params={"ccd": "TOOLONG"})).status_code == 404
    assert (await client.get("/knowledge-chat/structures", params={"pubchem": "x"})).status_code == 404

    def down(url):
        raise OSError("no route")

    monkeypatch.setattr(st, "_get", down)
    resp = await client.get("/knowledge-chat/structures", params={"ccd": "GTP"})
    assert resp.status_code == 502 and "no route" not in resp.text
    none = await client.get("/knowledge-chat/structures")
    assert none.status_code == 422
    for param in ("pdb", "afdb", "ccd", "pubchem"):
        assert f"?{param}=" in none.json()["detail"]
