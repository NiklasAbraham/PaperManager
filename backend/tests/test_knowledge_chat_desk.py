"""Tests for the rebuilt Knowledge Chat: answer sections and concept cards,
the structure proxy, forks, and the new routes.

No model or network is called: the concept pipeline, the RCSB / AlphaFold
fetch and the query layer are patched.
"""
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

import routers.knowledge_chat as kc
import services.chat_concepts as cc
import services.structures as st
from main import app
from services.auth import get_current_user


# ── Sections ─────────────────────────────────────────────────────────────────

def test_split_sections_keeps_preamble_and_headings():
    text = "Intro line.\n\n## First\nBody one.\n## Second\nBody two."
    assert cc.split_sections(text) == ["Intro line.\n", "## First\nBody one.", "## Second\nBody two."]


def test_split_sections_ignores_headings_in_code_fences():
    text = "## A\n```python\n## not a heading\n```\ntext\n## B\nend"
    sections = cc.split_sections(text)
    assert len(sections) == 3
    assert sections[1].startswith("## A") and "## not a heading" in sections[1]


def test_split_sections_answer_without_headings_is_one_section():
    assert cc.split_sections("Just prose.\n### Small heading\nmore") == ["Just prose.\n### Small heading\nmore"]


def test_split_sections_long_fence_closes_only_on_matching_fence():
    text = "````md\n```\n## inside\n```\n````\n## Out\nx"
    assert len(cc.split_sections(text)) == 2


def test_answer_pages_drop_the_models_own_blocks():
    text = "## Fold\nAlphaFold predicts structures.\n```structure\n6VXX\n```\nMore text."
    pages = cc._answer_pages(text)
    assert "6VXX" not in pages[1] and "More text." in pages[1]


# ── Concept cards ────────────────────────────────────────────────────────────

def _c(page, label, vtype):
    return {"page": page, "label": label, "type": vtype, "anchor": "", "context": "Some context sentence."}


def test_pick_spreads_types_and_keeps_reading_order():
    found = [_c(1, "a", "formula"), _c(1, "b", "formula"), _c(2, "c", "graph"), _c(3, "d", "2d-anim")]
    picked = cc._pick(found, 3)
    assert [c["label"] for c in picked] == ["a", "c", "d"]


def test_visualise_answer_generates_specs_and_keeps_failures():
    text = "## EDM loss\nThe loss weights noise levels.\n## Sampler\nIntegrate the ODE."
    found = [_c(1, "EDM loss", "formula"), _c(2, "ODE sampler", "2d-anim")]

    def spec(concept, title):
        if concept["type"] == "2d-anim":
            raise RuntimeError("model failed")
        return {"type": "formula", "title": concept["label"]}

    with patch.object(cc, "detect_concepts", return_value=found) as detect, \
         patch.object(cc, "generate_spec", side_effect=spec):
        cards = cc.visualise_answer(text, title="Q")
    pages = detect.call_args.args[0]
    assert len(pages) == 3 and pages[1].startswith("## EDM loss")
    assert cards[0]["section"] == 1 and cards[0]["spec"]["title"] == "EDM loss" and cards[0]["error"] is None
    assert cards[1]["spec"] is None and "model failed" in cards[1]["error"]


def test_visualise_answer_on_empty_text_calls_no_model():
    with patch.object(cc, "detect_concepts") as detect:
        assert cc.visualise_answer("   ") == []
    detect.assert_not_called()


def test_repair_concept_passes_previous_spec_and_error():
    card = {"label": "Anim", "type": "2d-anim", "context": "ctx", "section": 0,
            "spec": {"type": "2d-anim", "setup_code": "boom"}, "error": None}
    with patch.object(cc, "generate_spec", return_value={"type": "2d-anim", "setup_code": "fixed"}) as gen:
        out = cc.repair_concept(card, "TypeError: x")
    assert out["spec"]["setup_code"] == "fixed" and out["section"] == 0
    assert gen.call_args.kwargs["previous"] == {"spec": card["spec"], "error": "TypeError: x"}


# ── Structure proxy ──────────────────────────────────────────────────────────

def test_rcsb_entry_rejects_bad_ids():
    with pytest.raises(st.StructureError):
        st.rcsb_entry("../etc/passwd")
    with pytest.raises(st.StructureError):
        st.alphafold_model("not-an-accession")


def test_rcsb_entry_fetches_once_then_reads_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    calls = []

    class R:
        status_code = 200
        text = "data_6VXX\n"

    def get(url):
        calls.append(url)
        return R()

    monkeypatch.setattr(st, "_get", get)
    first = st.rcsb_entry("6vxx")
    second = st.rcsb_entry("6VXX")
    assert first == second == {"name": "6VXX", "format": "cif", "data": "data_6VXX\n"}
    assert calls == ["https://files.rcsb.org/download/6VXX.cif"]
    assert (tmp_path / "6VXX.cif").exists()


def test_alphafold_model_follows_the_api_cif_url(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))

    class Api:
        status_code = 200
        def json(self):
            return [{"cifUrl": "https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v4.cif"}]

    class Cif:
        status_code = 200
        text = "data_AF\n"

    monkeypatch.setattr(st, "_get", lambda url: Api() if "/api/" in url else Cif())
    out = st.alphafold_model("AF-P69905-F1")
    assert out["name"] == "AF-P69905" and out["data"] == "data_AF\n"


# ── Routes ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[get_current_user] = lambda: "tester"
    kc._concept_jobs.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(kc, "get_driver", lambda: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


async def test_routes_require_login():
    app.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        resp = await c.get("/knowledge-chat/conversations")
    assert resp.status_code == 401


ANSWER = {"id": "m1", "role": "assistant", "content": "## A\ntext", "question": "Q?",
          "concepts": None, "concepts_status": None, "concepts_error": None}


async def test_visualise_starts_a_job_and_reports_running(client, monkeypatch):
    stored = []
    monkeypatch.setattr(kc, "get_message", lambda d, mid: dict(ANSWER))
    monkeypatch.setattr(kc, "set_message_concepts", lambda d, mid, cards, status, error=None: stored.append(status))
    started = []
    monkeypatch.setattr(kc.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args)})())
    resp = await client.post("/knowledge-chat/messages/m1/visualise")
    assert resp.status_code == 200 and resp.json()["status"] == "running"
    assert stored == ["running"] and len(started) == 1


async def test_running_state_without_a_job_reads_as_interrupted(client, monkeypatch):
    monkeypatch.setattr(kc, "get_message", lambda d, mid: {**ANSWER, "concepts_status": "running"})
    resp = await client.get("/knowledge-chat/messages/m1/concepts")
    assert resp.json()["status"] == "failed"


async def test_visualise_on_a_question_is_404(client, monkeypatch):
    monkeypatch.setattr(kc, "get_message", lambda d, mid: {**ANSWER, "role": "user"})
    resp = await client.post("/knowledge-chat/messages/m1/visualise")
    assert resp.status_code == 404


async def test_fork_validates_and_returns_the_copy(client, monkeypatch):
    monkeypatch.setattr(kc, "fork_conversation", lambda d, cid, keep, kind: {
        "id": "c2", "title": "T", "created_at": "x", "updated_at": "x", "parent_id": cid, "fork_at": keep,
        "fork_kind": kind, "message_count": 2})
    bad = await client.post("/knowledge-chat/conversations/c1/fork", json={"keep": -1})
    ok = await client.post("/knowledge-chat/conversations/c1/fork", json={"keep": 1, "kind": "edit"})
    assert bad.status_code == 422
    assert ok.json()["parent_id"] == "c1" and ok.json()["fork_at"] == 1 and ok.json()["fork_kind"] == "edit"


async def test_structure_route_maps_errors(client, monkeypatch):
    monkeypatch.setattr(st, "rcsb_entry", lambda pid: (_ for _ in ()).throw(st.StructureError("no entry")))
    missing = await client.get("/knowledge-chat/structures", params={"pdb": "9ZZZ"})
    neither = await client.get("/knowledge-chat/structures")
    assert missing.status_code == 404 and neither.status_code == 422


def test_heartbeat_fills_silence_and_passes_events_and_errors():
    import time

    def slow():
        yield {"type": "token", "text": "a"}
        time.sleep(0.25)
        yield {"type": "token", "text": "b"}

    out = list(kc._with_heartbeat(slow(), every=0.1))
    assert out[0]["text"] == "a" and out[-1]["text"] == "b" and None in out

    def broken():
        yield {"type": "token", "text": "a"}
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        list(kc._with_heartbeat(broken(), every=1))


# ── Every route needs a login ────────────────────────────────────────────────

ROUTES = [
    ("POST", "/knowledge-chat/stream", {"question": "q"}),
    ("GET", "/knowledge-chat/conversations", None),
    ("GET", "/knowledge-chat/conversations/c1/messages", None),
    ("PATCH", "/knowledge-chat/conversations/c1", {"title": "t"}),
    ("DELETE", "/knowledge-chat/conversations/c1", None),
    ("POST", "/knowledge-chat/conversations/c1/compact", None),
    ("POST", "/knowledge-chat/conversations/c1/fork", {"keep": 1}),
    ("POST", "/knowledge-chat/messages/m1/visualise", None),
    ("GET", "/knowledge-chat/messages/m1/concepts", None),
    ("POST", "/knowledge-chat/messages/m1/concepts/0/repair", {"error": "e"}),
    ("GET", "/knowledge-chat/structures?pdb=1UBQ", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_every_route_requires_login(method, path, body):
    app.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        resp = await c.request(method, path, json=body)
    assert resp.status_code == 401, path


# ── Conversation routes ──────────────────────────────────────────────────────

CONV = {"id": "c1", "title": "T", "created_at": "x", "updated_at": "x", "message_count": 2}


async def test_list_conversations_passes_fork_fields(client, monkeypatch):
    monkeypatch.setattr(kc, "list_conversations", lambda d: [
        CONV, {**CONV, "id": "c2", "parent_id": "c1", "fork_at": 1, "fork_kind": "strand", "branch_label": "Why?"}])
    rows = (await client.get("/knowledge-chat/conversations")).json()
    assert rows[1]["parent_id"] == "c1" and rows[1]["branch_label"] == "Why?" and rows[0]["parent_id"] is None


async def test_messages_include_papers_cards_and_errors(client, monkeypatch):
    monkeypatch.setattr(kc, "get_messages", lambda d, cid: [
        {"id": "u", "role": "user", "content": "q", "created_at": "1", "paper_refs": [], "answer_error": "boom"},
        {"id": "a", "role": "assistant", "content": "a", "created_at": "2", "paper_refs": ["p1"],
         "papers": [{"id": "p1", "title": "AF3", "year": 2024}], "concepts": [{"label": "x"}], "concepts_status": "done"},
    ])
    rows = (await client.get("/knowledge-chat/conversations/c1/messages")).json()
    assert rows[0]["answer_error"] == "boom"
    assert rows[1]["papers"][0]["title"] == "AF3" and rows[1]["concepts"] == [{"label": "x"}]


async def test_rename_validates_and_404s(client, monkeypatch):
    monkeypatch.setattr(kc, "rename_conversation", lambda d, cid, t: {**CONV, "title": t} if cid == "c1" else {})
    assert (await client.patch("/knowledge-chat/conversations/c1", json={"title": "  "})).status_code == 422
    assert (await client.patch("/knowledge-chat/conversations/zz", json={"title": "x"})).status_code == 404
    ok = await client.patch("/knowledge-chat/conversations/c1", json={"title": "  New  "})
    assert ok.json()["title"] == "New"


async def test_delete_conversation(client, monkeypatch):
    gone = []
    monkeypatch.setattr(kc, "delete_conversation", lambda d, cid: gone.append(cid))
    assert (await client.delete("/knowledge-chat/conversations/c1")).status_code == 204 and gone == ["c1"]


async def test_fork_missing_conversation_is_404(client, monkeypatch):
    def missing(d, cid, keep, kind):
        raise ValueError("Conversation not found")
    monkeypatch.setattr(kc, "fork_conversation", missing)
    resp = await client.post("/knowledge-chat/conversations/zz/fork", json={"keep": 1, "kind": "strand"})
    assert resp.status_code == 404
    bad_kind = await client.post("/knowledge-chat/conversations/c1/fork", json={"keep": 1, "kind": "aside"})
    assert bad_kind.status_code == 422


# ── Concept routes ───────────────────────────────────────────────────────────

async def test_visualise_twice_while_running_starts_one_job(client, monkeypatch):
    monkeypatch.setattr(kc, "get_message", lambda d, mid: dict(ANSWER))
    monkeypatch.setattr(kc, "set_message_concepts", lambda *a, **k: None)
    started = []
    monkeypatch.setattr(kc.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args)})())
    await client.post("/knowledge-chat/messages/m1/visualise")
    await client.post("/knowledge-chat/messages/m1/visualise")
    assert len(started) == 1


def test_run_concepts_stores_cards_or_the_failure(monkeypatch):
    stored = []
    monkeypatch.setattr(kc, "get_driver", lambda: None)
    monkeypatch.setattr(kc, "set_message_concepts", lambda d, mid, cards, status, error=None: stored.append((status, cards, error)))
    kc._concept_jobs.add("m1")
    with patch.object(cc, "visualise_answer", return_value=[{"label": "x"}]) as vis:
        kc._run_concepts(dict(ANSWER))
    assert stored[-1] == ("done", [{"label": "x"}], None) and "m1" not in kc._concept_jobs
    assert vis.call_args.kwargs["title"] == "Q?"
    with patch.object(cc, "visualise_answer", side_effect=RuntimeError("detector down")):
        kc._run_concepts(dict(ANSWER))
    assert stored[-1][0] == "failed" and stored[-1][1] is None and "detector down" in stored[-1][2]


async def test_concepts_state_for_a_missing_answer_is_404(client, monkeypatch):
    monkeypatch.setattr(kc, "get_message", lambda d, mid: None)
    assert (await client.get("/knowledge-chat/messages/zz/concepts")).status_code == 404


async def test_repair_replaces_one_card(client, monkeypatch):
    cards = [{"label": "a", "type": "2d-anim", "context": "c", "section": 0, "spec": {"type": "2d-anim"}, "error": None},
             {"label": "b", "type": "formula", "context": "c", "section": 1, "spec": {"type": "formula"}, "error": None}]
    monkeypatch.setattr(kc, "get_message", lambda d, mid: {**ANSWER, "concepts": [dict(c) for c in cards]})
    saved = []
    monkeypatch.setattr(kc, "set_message_concepts", lambda d, mid, c, status, error=None: saved.append(c))
    with patch.object(cc, "generate_spec", return_value={"type": "2d-anim", "setup_code": "fixed"}):
        resp = await client.post("/knowledge-chat/messages/m1/concepts/0/repair", json={"error": "TypeError"})
    assert resp.status_code == 200
    assert resp.json()["concepts"][0]["spec"]["setup_code"] == "fixed"
    assert saved[0][1] == cards[1]


async def test_repair_bad_index_and_model_failure(client, monkeypatch):
    from services.concepts import ConceptsError
    monkeypatch.setattr(kc, "get_message", lambda d, mid: {**ANSWER, "concepts": [
        {"label": "a", "type": "formula", "context": "c", "section": 0, "spec": {"type": "formula"}}]})
    monkeypatch.setattr(kc, "set_message_concepts", lambda *a, **k: None)
    assert (await client.post("/knowledge-chat/messages/m1/concepts/5/repair", json={"error": "e"})).status_code == 404
    with patch.object(cc, "generate_spec", side_effect=ConceptsError("refused")):
        resp = await client.post("/knowledge-chat/messages/m1/concepts/0/repair", json={"error": "e"})
    assert resp.status_code == 502 and "refused" in resp.json()["detail"]


def test_repair_concept_without_a_spec_raises():
    from services.concepts import ConceptsError
    with pytest.raises(ConceptsError):
        cc.repair_concept({"label": "a", "type": "formula", "context": "c", "spec": None}, "e")


def test_visualise_answer_caps_cards_and_skips_models_own_blocks():
    text = "## A\nx\n```concept\n{\"type\": \"formula\"}\n```\n## B\ny"
    found = [_c(i % 3, f"c{i}", "formula") for i in range(9)]
    with patch.object(cc, "detect_concepts", return_value=found) as detect, \
         patch.object(cc, "generate_spec", return_value={"type": "formula"}):
        cards = cc.visualise_answer(text, limit=2)
    assert len(cards) == 2
    assert all('"type"' not in page for page in detect.call_args.args[0])


# ── Structure routes and service ─────────────────────────────────────────────

async def test_structure_route_returns_coordinates_for_pdb_and_afdb(client, monkeypatch):
    monkeypatch.setattr(st, "rcsb_entry", lambda pid: {"name": pid.upper(), "format": "cif", "data": "x"})
    monkeypatch.setattr(st, "alphafold_model", lambda acc: {"name": f"AF-{acc}", "format": "cif", "data": "y"})
    pdb = await client.get("/knowledge-chat/structures", params={"pdb": "1ubq"})
    af = await client.get("/knowledge-chat/structures", params={"afdb": "P69905"})
    assert pdb.json()["name"] == "1UBQ" and af.json()["name"] == "AF-P69905"


async def test_structure_route_network_failure_is_502(client, monkeypatch):
    def down(pid):
        raise OSError("no route")
    monkeypatch.setattr(st, "rcsb_entry", down)
    resp = await client.get("/knowledge-chat/structures", params={"pdb": "1UBQ"})
    assert resp.status_code == 502 and "no route" not in resp.text


@pytest.mark.parametrize("bad", ["", "1UB", "1UBQX", "ABCD", "../x", "1U?Q"])
def test_rcsb_rejects_malformed_ids_before_any_request(bad, monkeypatch):
    monkeypatch.setattr(st, "_get", lambda url: pytest.fail("no request for a bad id"))
    with pytest.raises(st.StructureError):
        st.rcsb_entry(bad)


def test_rcsb_missing_entry_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(st, "_get", lambda url: type("R", (), {"status_code": 404, "text": ""})())
    with pytest.raises(st.StructureError, match="no entry 9ZZZ"):
        st.rcsb_entry("9zzz")
    assert list(tmp_path.iterdir()) == []


def test_oversized_download_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(st, "MAX_BYTES", 10)
    monkeypatch.setattr(st, "_get", lambda url: type("R", (), {"status_code": 200, "text": "x" * 11})())
    with pytest.raises(st.StructureError, match="larger"):
        st.rcsb_entry("1UBQ")
    assert not (tmp_path / "1UBQ.cif").exists()


def test_alphafold_refuses_a_model_url_off_the_afdb_host(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))

    class Api:
        status_code = 200
        def json(self):
            return [{"cifUrl": "https://evil.example/model.cif"}]

    monkeypatch.setattr(st, "_get", lambda url: Api())
    with pytest.raises(st.StructureError, match="no model file"):
        st.alphafold_model("P69905")


def test_alphafold_unknown_accession(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(st, "_get", lambda url: type("R", (), {"status_code": 404})())
    with pytest.raises(st.StructureError, match="no prediction"):
        st.alphafold_model("Q9ZZZ9")


def test_cache_dir_falls_back_when_the_configured_one_is_not_writable(tmp_path, monkeypatch):
    blocked = tmp_path / "file"
    blocked.write_text("not a dir")
    monkeypatch.setenv("STRUCTURE_CACHE_DIR", str(blocked / "sub"))
    assert st.cache_dir() != blocked / "sub"


# ── The stream: attached papers, saving after a disconnect, failures ─────────

class _Session:
    def __init__(self, rows=None):
        self.rows = rows or []
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def run(self, query, **params):
        if "UNWIND $ids" in query:
            return [{"id": pid, "title": f"T{pid}", "year": 2024, "abstract": "", "summary": ""} for pid in params["ids"]]
        return []


class _Driver:
    def session(self):
        return _Session()


@pytest.fixture
def stream_env(monkeypatch):
    saved = {"messages": [], "errors": []}
    monkeypatch.setattr(kc, "get_driver", lambda: _Driver())
    monkeypatch.setattr(kc, "get_paper_context_snippets", lambda d, pid: {})
    monkeypatch.setattr(kc, "create_conversation", lambda d, title: {"id": "c-new"})
    monkeypatch.setattr(kc, "set_branch_label_if_empty", lambda d, cid, label: None)
    monkeypatch.setattr(kc, "set_message_error", lambda d, mid, err: saved["errors"].append((mid, err)))

    # The unscoped fallback embeds the question; with a LiteLLM endpoint in .env that would reach
    # the network, so embeddings are unavailable here (the fallback then uses recency only).
    def no_embeddings(text):
        raise RuntimeError("no embeddings in tests")

    monkeypatch.setattr("services.embeddings.embed_text", no_embeddings)

    def add_message(d, cid, role, content, paper_ids, tokens, **extra):  # extra: steps, stopped
        saved["messages"].append({"role": role, "content": content, "papers": paper_ids})
        return {"id": f"{role}-id"}

    monkeypatch.setattr(kc, "add_message", add_message)
    return saved


def _events(chunks):
    import json as _json
    return [_json.loads(c[6:]) for c in chunks if c.startswith("data: ")]


def test_stream_puts_attached_papers_first_and_saves_the_answer(stream_env, monkeypatch):
    from models.schemas import KnowledgeChatRequest
    seen = {}

    def fake_stream(**kw):
        seen["papers"] = [p["id"] for p in kw["papers"]]
        yield {"type": "token", "text": "Hello "}
        yield {"type": "token", "text": "world"}

    monkeypatch.setattr(kc, "knowledge_chat_stream", fake_stream)
    events = _events(list(kc._stream(KnowledgeChatRequest(question="q", paper_ids=["p9", "p8"]))))
    assert seen["papers"][:2] == ["p9", "p8"]
    kinds = [e["type"] for e in events]
    assert kinds.index("context") < kinds.index("conversation") < kinds.index("token") < kinds.index("done")
    attach = next(e for e in events if e.get("kind") == "attach")
    assert [p["id"] for p in attach["papers"]] == ["p9", "p8"]
    assert stream_env["messages"][-1] == {"role": "assistant", "content": "Hello world", "papers": ["p9", "p8"]}
    assert events[-1] == {"type": "done", "conversation_id": "c-new", "message_id": "assistant-id"}


def test_stream_saves_the_answer_even_if_the_client_disconnects(stream_env, monkeypatch):
    import threading as _t
    from models.schemas import KnowledgeChatRequest
    finished = _t.Event()

    def fake_stream(**kw):
        yield {"type": "token", "text": "first"}
        yield {"type": "token", "text": " second"}
        finished.set()

    monkeypatch.setattr(kc, "knowledge_chat_stream", fake_stream)
    gen = kc._stream(KnowledgeChatRequest(question="q"))
    for chunk in gen:
        if '"conversation"' in chunk:
            break
    gen.close()                     # the browser went away mid-answer
    assert finished.wait(5)
    for _ in range(50):
        if any(m["role"] == "assistant" for m in stream_env["messages"]):
            break
        __import__("time").sleep(0.05)
    assert stream_env["messages"][-1]["content"] == "first second"


def test_stream_failure_is_reported_and_marked_on_the_question(stream_env, monkeypatch):
    from models.schemas import KnowledgeChatRequest

    def fake_stream(**kw):
        yield {"type": "token", "text": "partial"}
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(kc, "knowledge_chat_stream", fake_stream)
    events = _events(list(kc._stream(KnowledgeChatRequest(question="q"))))
    assert events[-1] == {"type": "error", "message": "model unavailable"}
    assert stream_env["errors"] == [("user-id", "model unavailable")]
    assert not any(m["role"] == "assistant" for m in stream_env["messages"])


def test_heartbeat_gives_up_after_max_silence():
    import time

    def stuck():
        time.sleep(1)
        yield {"type": "token", "text": "late"}

    with pytest.raises(TimeoutError):
        list(kc._with_heartbeat(stuck(), every=0.05, max_silence=0.2))


def test_captions_are_trimmed_at_a_sentence_not_mid_word():
    from services.concepts import trim_sentences
    text = "First sentence is here. " * 30
    out = trim_sentences(text.strip(), 400)
    assert len(out) <= 400 and out.endswith("here.")
    assert trim_sentences("short", 400) == "short"
    assert trim_sentences("word " * 200, 50).endswith("…")
