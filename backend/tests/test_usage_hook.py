"""The SDK hook: real anthropic / openai clients on a mock transport, recorded in a temp ledger."""
import json

import anthropic
import httpx
import openai
import pytest

from config import settings
from services.usage import hook, ledger, usage_context

ANTHROPIC_USAGE = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50,
                   "cache_creation_input_tokens": 10}


@pytest.fixture(autouse=True)
def ledger_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "usage_db_path", str(tmp_path / "usage.sqlite"))
    monkeypatch.setattr(settings, "usage_ledger_enabled", True)
    ledger.close()
    hook.install()
    yield
    hook.uninstall()
    ledger.close()


def rows():
    return ledger.calls(limit=500)[0][::-1]  # oldest first


def anthropic_client(handler, base_url="https://api.anthropic.com"):
    return anthropic.Anthropic(api_key="x", base_url=base_url, max_retries=0,
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def openai_client(handler, base_url="https://litellm.example/v1"):
    return openai.OpenAI(api_key="x", base_url=base_url, max_retries=0,
                         http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def message_json(model="claude-haiku-4-5-20251001"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": ANTHROPIC_USAGE}


def sse(*events):
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def anthropic_events(model="claude-sonnet-4-6"):
    msg = {"id": "msg_2", "type": "message", "role": "assistant", "model": model, "content": [],
           "stop_reason": None, "stop_sequence": None,
           "usage": {"input_tokens": 300, "output_tokens": 1, "cache_read_input_tokens": 40,
                     "cache_creation_input_tokens": 0}}
    return [
        {"type": "message_start", "message": msg},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
         "usage": {"output_tokens": 42}},
        {"type": "message_stop"},
    ]


def test_install_is_idempotent_and_uninstall_restores():
    from anthropic.resources.messages.messages import Messages

    first = Messages.create
    hook.install()
    assert Messages.create is first and hasattr(first, hook._MARK)
    hook.uninstall()
    assert not hasattr(Messages.create, hook._MARK)
    hook.install()
    assert hasattr(Messages.create, hook._MARK)


def test_anthropic_create_records_usage_and_cost():
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json()))
    with usage_context(feature="summary", paper_id="p1", user="alice"):
        resp = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=10,
                                      messages=[{"role": "user", "content": "x"}])
    assert resp.content[0].text == "hi"  # response unchanged
    (r,) = rows()
    assert (r["provider"], r["model"], r["feature"], r["paper_id"], r["user"]) == (
        "anthropic", "claude-haiku-4-5-20251001", "summary", "p1", "alice")
    assert (r["input_tokens"], r["output_tokens"], r["cache_read_tokens"], r["cache_write_tokens"]) == (100, 20, 50, 10)
    assert r["ok"] and not r["streamed"] and r["price_known"]
    assert r["cost_usd"] == pytest.approx((100 * 1.0 + 20 * 5.0 + 10 * 1.25 + 50 * 0.1) / 1e6)
    assert r["latency_ms"] >= 0


def test_gateway_provider_from_base_url():
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json()), base_url="https://gw.corp/anthropic")
    client.messages.create(model="claude-opus-4-6", max_tokens=10, messages=[{"role": "user", "content": "x"}])
    assert rows()[0]["provider"] == "anthropic-gateway"


def test_anthropic_error_is_recorded_and_reraised():
    client = anthropic_client(lambda req: httpx.Response(500, json={"type": "error", "error": {
        "type": "api_error", "message": "boom"}}))
    with pytest.raises(anthropic.APIStatusError):
        client.messages.create(model="claude-opus-4-6", max_tokens=10, messages=[{"role": "user", "content": "x"}])
    (r,) = rows()
    assert not r["ok"] and r["error"].startswith("InternalServerError:") and len(r["error"]) <= 300
    assert r["input_tokens"] == 0


def test_anthropic_create_stream_true_records_once_when_exhausted():
    client = anthropic_client(lambda req: sse(*anthropic_events()))
    with usage_context(feature="x"):
        stream = client.messages.create(model="claude-sonnet-4-6", max_tokens=10, stream=True,
                                        messages=[{"role": "user", "content": "x"}])
    assert rows() == []  # nothing yet
    events = list(stream)
    assert [e.type for e in events][0] == "message_start"
    list(stream)
    (r,) = rows()
    assert r["streamed"] and r["ok"] and r["feature"] == "x"
    assert (r["input_tokens"], r["output_tokens"], r["cache_read_tokens"]) == (300, 42, 40)


def test_stream_proxy_context_manager_and_attribute_access():
    client = anthropic_client(lambda req: sse(*anthropic_events()))
    with client.messages.create(model="claude-sonnet-4-6", max_tokens=10, stream=True,
                                messages=[{"role": "user", "content": "x"}]) as stream:
        assert stream.response.status_code == 200  # forwarded attribute
        next(iter(stream))
    (r,) = rows()  # closed early: recorded once with what was seen
    assert r["streamed"] and r["input_tokens"] == 300


def test_anthropic_messages_stream_manager():
    client = anthropic_client(lambda req: sse(*anthropic_events()))
    with usage_context(feature="knowledge-chat", user="bob"):
        with client.messages.stream(model="claude-sonnet-4-6", max_tokens=10,
                                    messages=[{"role": "user", "content": "x"}]) as stream:
            text = "".join(stream.text_stream)
            final = stream.get_final_message()
    assert text == "Hello" and final.stop_reason == "end_turn"
    (r,) = rows()
    assert r["streamed"] and r["ok"] and r["feature"] == "knowledge-chat" and r["user"] == "bob"
    assert (r["input_tokens"], r["output_tokens"], r["cache_read_tokens"]) == (300, 42, 40)
    assert r["cost_usd"] == pytest.approx((300 * 3 + 42 * 15 + 40 * 0.3) / 1e6)


def test_anthropic_beta_stream_manager():
    client = anthropic_client(lambda req: sse(*anthropic_events()))
    with client.beta.messages.stream(model="claude-sonnet-4-6", max_tokens=10,
                                     messages=[{"role": "user", "content": "x"}]) as stream:
        stream.get_final_message()
    (r,) = rows()
    assert r["streamed"] and r["output_tokens"] == 42


def test_stream_manager_records_error_inside_block():
    client = anthropic_client(lambda req: sse(*anthropic_events()))
    with pytest.raises(ValueError):
        with client.messages.stream(model="claude-sonnet-4-6", max_tokens=10,
                                    messages=[{"role": "user", "content": "x"}]) as stream:
            next(iter(stream))
            raise ValueError("client side")
    (r,) = rows()
    assert not r["ok"] and r["error"] == "ValueError: client side"


def openai_completion(usage=True):
    body = {"id": "c1", "object": "chat.completion", "created": 1, "model": "gemma-3-27b",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230,
                         "prompt_tokens_details": {"cached_tokens": 50}}
    return body


def test_openai_chat_create_litellm_is_free_and_splits_cache():
    client = openai_client(lambda req: httpx.Response(200, json=openai_completion()))
    with usage_context(feature="claims"):
        resp = client.chat.completions.create(model="gemma-3-27b", messages=[{"role": "user", "content": "x"}])
    assert resp.choices[0].message.content == "ok"
    (r,) = rows()
    assert r["provider"] == "litellm" and r["cost_usd"] == 0.0 and r["price_known"]
    assert (r["input_tokens"], r["cache_read_tokens"], r["output_tokens"]) == (150, 50, 30)


def test_openai_provider_and_cost():
    client = openai_client(lambda req: httpx.Response(200, json=openai_completion()), base_url="https://api.openai.com/v1")
    client.chat.completions.create(model="gpt-5-mini", messages=[{"role": "user", "content": "x"}])
    (r,) = rows()
    assert r["provider"] == "openai"
    assert r["cost_usd"] == pytest.approx((150 * 0.25 + 30 * 2.0 + 50 * 0.025) / 1e6)


def chunks_sse(with_usage):
    parts = []
    for text in ("Hel", "lo wor", "ld!"):
        parts.append({"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "gemma-3-27b",
                      "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]})
    last = {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "gemma-3-27b", "choices": []}
    if with_usage:
        last["usage"] = {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}
        parts.append(last)
    body = "".join(f"data: {json.dumps(p)}\n\n" for p in parts) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def test_openai_stream_with_usage():
    client = openai_client(lambda req: chunks_sse(True))
    stream = client.chat.completions.create(model="gemma-3-27b", stream=True,
                                            messages=[{"role": "user", "content": "x"}])
    assert "".join(c.choices[0].delta.content or "" for c in stream if c.choices) == "Hello world!"
    (r,) = rows()
    assert r["streamed"] and not r["estimated"] and (r["input_tokens"], r["output_tokens"]) == (11, 5)


def test_openai_stream_without_usage_is_estimated():
    client = openai_client(lambda req: chunks_sse(False))
    stream = client.chat.completions.create(model="gemma-3-27b", stream=True,
                                            messages=[{"role": "user", "content": "a" * 400}])
    list(stream)
    (r,) = rows()
    assert r["streamed"] and r["estimated"]
    assert r["input_tokens"] == 100 and r["output_tokens"] == len("Hello world!") // 4


def test_openai_embeddings():
    body = {"object": "list", "model": "text-embedding-3-small", "data": [{"object": "embedding", "index": 0,
            "embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 8, "total_tokens": 8}}
    client = openai_client(lambda req: httpx.Response(200, json=body), base_url="https://api.openai.com/v1")
    with usage_context(feature="embeddings"):
        client.embeddings.create(model="text-embedding-3-small", input="hello", encoding_format="float")
    (r,) = rows()
    assert (r["provider"], r["input_tokens"], r["output_tokens"], r["feature"]) == ("openai", 8, 0, "embeddings")
    assert r["cost_usd"] == pytest.approx(8 * 0.02 / 1e6)


def test_unknown_model_has_no_cost():
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json("claude-future-9")))
    client.messages.create(model="claude-future-9", max_tokens=10, messages=[{"role": "user", "content": "x"}])
    (r,) = rows()
    assert r["cost_usd"] is None and not r["price_known"]


def test_disabled_ledger_records_nothing(monkeypatch):
    monkeypatch.setattr(settings, "usage_ledger_enabled", False)
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json()))
    assert client.messages.create(model="claude-haiku-4-5", max_tokens=10,
                                  messages=[{"role": "user", "content": "x"}]).content
    assert rows() == []


def test_ledger_failure_never_reaches_the_caller(monkeypatch):
    def boom(row):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ledger, "_connect", boom)
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json()))
    assert client.messages.create(model="claude-haiku-4-5", max_tokens=10,
                                  messages=[{"role": "user", "content": "x"}]).content[0].text == "hi"


# ── attribution ───────────────────────────────────────────────────────────────

def test_usage_context_nests_and_inner_wins():
    with usage_context(feature="outer", user="alice", paper_id="p1"):
        with usage_context(feature="inner"):
            c = hook.capture()
            assert (c["feature"], c["user"], c["paper_id"]) == ("inner", "alice", "p1")
        assert hook.capture()["feature"] == "outer"


def test_stack_inference_label_feature_paper_and_user(monkeypatch):
    monkeypatch.setitem(hook.FEATURE_RULES, "tests/test_usage_hook.py:fake_summarize", "summary")
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json()))

    def fake_summarize(paper_id, current_user):
        return client.messages.create(model="claude-haiku-4-5", max_tokens=10,
                                      messages=[{"role": "user", "content": "x"}])

    fake_summarize("paper-42", "carol")
    (r,) = rows()
    assert r["label"] == "tests.test_usage_hook.fake_summarize"
    assert (r["feature"], r["paper_id"], r["user"]) == ("summary", "paper-42", "carol")


def test_private_helper_takes_feature_of_its_public_caller(monkeypatch):
    monkeypatch.setitem(hook.FEATURE_RULES, "tests/test_usage_hook.py:public_caller", "tour")
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json()))

    def _helper():
        client.messages.create(model="claude-haiku-4-5", max_tokens=10, messages=[{"role": "user", "content": "x"}])

    def public_caller():
        _helper()

    public_caller()
    (r,) = rows()
    assert r["label"].endswith("._helper") and r["feature"] == "tour"


def test_unmapped_frame_gives_label_as_feature():
    client = anthropic_client(lambda req: httpx.Response(200, json=message_json()))

    def some_unmapped_function():
        client.messages.create(model="claude-haiku-4-5", max_tokens=10, messages=[{"role": "user", "content": "x"}])

    some_unmapped_function()
    (r,) = rows()
    assert r["feature"] == r["label"] == "tests.test_usage_hook.some_unmapped_function"
    assert r["user"] is None and r["paper_id"] is None


def test_request_user_beats_stack_locals_and_context_beats_request_user():
    from services.auth import reset_request_user, set_request_user

    token = set_request_user("dave")
    try:
        assert hook.capture()["user"] == "dave"
        current_user = "local"  # noqa: F841 — a stack local the request user outranks
        assert hook.capture()["user"] == "dave"
        with usage_context(user="erin"):
            assert hook.capture()["user"] == "erin"
    finally:
        reset_request_user(token)


def test_long_or_non_string_paper_id_locals_are_ignored():
    paper_id = "x" * 200  # noqa: F841
    assert hook.capture()["paper_id"] is None
    paper_id = 5  # noqa: F841
    assert hook.capture()["paper_id"] is None


def test_feature_rules_cover_the_known_call_sites():
    rules = hook.FEATURE_RULES
    for key, feature in {
        "services/ai.py:summarize_paper": "summary", "services/ai.py:knowledge_chat_stream": "knowledge-chat",
        "services/concepts.py": "concepts", "routers/knowledge_chat.py:compact": "chat-compaction",
        "services/claude_code_chat.py:chat_with_paper_claude_code": "paper-chat",
    }.items():
        assert rules[key] == feature
    assert hook._feature_for("services/reports/build.py", "run") == "reports"
    assert hook._feature_for("routers/knowledge_chat.py", "compact") == "chat-compaction"
    assert hook._feature_for("routers/knowledge_chat.py", "stream") == "knowledge-chat"
    assert hook._feature_for("services/concept_map.py", "anything") == "concept-map"


def test_litellm_client_and_usage_frames_are_looked_through():
    assert hook._skipped("services/litellm_client.py", "chat_completion")
    assert hook._skipped("services/usage/hook.py", "capture")
    assert hook._skipped("services/claude_code_chat.py", "run_structured_claude_code")
    assert not hook._skipped("services/concepts.py", "_run_json")


def test_claude_code_style_capture_and_reentry():
    """What _drive does: capture in the caller's thread, re-enter in a worker with no stack."""
    import threading

    with usage_context(feature="tour", paper_id="p7", user="zed"):
        captured = hook.capture()
    seen = {}

    def worker():
        with usage_context(**captured):
            hook.record_call(provider="claude-code", model="opus", input_tokens=5, output_tokens=6,
                             cost_usd=0.25, latency_ms=1234, streamed=True)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    (r,) = rows()
    assert (r["provider"], r["model"], r["feature"], r["paper_id"], r["user"]) == ("claude-code", "opus", "tour", "p7", "zed")
    assert r["cost_usd"] == 0.25 and r["price_known"] and r["latency_ms"] == 1234 and r["streamed"]
    assert seen == {}


def test_claude_code_result_recorded_without_reported_cost_uses_alias_price():
    hook.record_call(provider="claude-code", model="sonnet", input_tokens=1_000_000, attribution={"feature": "f"})
    (r,) = rows()
    assert r["cost_usd"] == pytest.approx(2.0)


# ── services/claude_code_chat.py ──────────────────────────────────────────────

def fake_result(**kw):
    from types import SimpleNamespace

    base = dict(usage={"input_tokens": 12, "output_tokens": 34, "cache_read_input_tokens": 5,
                       "cache_creation_input_tokens": 6},
                total_cost_usd=0.0421, duration_ms=2500, is_error=False, errors=None, result="", subtype="success",
                model_usage={"claude-opus-5-5": {"costUSD": 0.04}, "claude-haiku-4-5": {"costUSD": 0.002}})
    base.update(kw)
    return SimpleNamespace(**base)


def test_claude_code_record_result():
    from services.claude_code_chat import _record_result

    with usage_context(feature="tour", user="niklas"):
        _record_result(fake_result(), "opus")
        _record_result(fake_result(model_usage=None, is_error=True, errors=["rate limited"]), "sonnet")
    ok_row, err_row = rows()
    assert ok_row["provider"] == "claude-code" and ok_row["model"] == "claude-opus-5-5"  # the dominant model
    assert ok_row["cost_usd"] == pytest.approx(0.0421) and ok_row["latency_ms"] == 2500
    assert (ok_row["input_tokens"], ok_row["output_tokens"], ok_row["cache_read_tokens"],
            ok_row["cache_write_tokens"]) == (12, 34, 5, 6)
    assert ok_row["feature"] == "tour" and ok_row["user"] == "niklas" and ok_row["streamed"]
    assert err_row["model"] == "sonnet" and not err_row["ok"] and "rate limited" in err_row["error"]


def test_claude_code_drive_carries_attribution_into_the_worker(monkeypatch):
    from services import claude_code_chat as cc

    monkeypatch.setitem(hook.FEATURE_RULES, "tests/test_usage_hook.py:fake_caller", "paper-chat")

    async def run(emit):
        cc._record_result(fake_result(model_usage=None), "opus")  # runs in the worker thread
        emit({"type": "token", "text": "hi"})

    def fake_caller(paper_id):
        return list(cc._drive(run))

    assert fake_caller("paper-9") == [{"type": "token", "text": "hi"}]
    (r,) = rows()
    assert (r["feature"], r["paper_id"], r["label"]) == ("paper-chat", "paper-9", "tests.test_usage_hook.fake_caller")


@pytest.fixture(autouse=True)
def _no_request_user():
    """Importing mcp_server in-process (other tests) leaves a request user set; start clean."""
    from services.auth import reset_request_user, set_request_user

    token = set_request_user(None)
    yield
    reset_request_user(token)
