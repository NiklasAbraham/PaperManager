"""SuggestionFilter and filter_events: the tag never reaches the stream (.specs/015_suggestions.md)."""
from __future__ import annotations

import pytest

from services import suggestions as svc
from services.suggestions import SuggestionFilter, filter_events


def run(chunks: list[str]) -> tuple[str, str | None]:
    flt = SuggestionFilter()
    out = "".join(flt.feed(c) for c in chunks)
    rest, found = flt.finish()
    return out + rest, found


def test_no_tag_passes_through():
    assert run(["Hello ", "world.\n", "Done."]) == ("Hello world.\nDone.", None)


def test_tag_in_one_token_removes_whitespace_before_it():
    text, found = run(["The answer.\n<suggestion>Add a CSV export of search results</suggestion>"])
    assert text == "The answer."
    assert found == "Add a CSV export of search results"


@pytest.mark.parametrize("step", [1, 2, 3, 5, 7])
def test_tag_split_across_arbitrary_boundaries(step):
    full = "Answer text. \n\n<suggestion>Let the chat read Zotero libraries</suggestion>"
    chunks = [full[i:i + step] for i in range(0, len(full), step)]
    assert run(chunks) == ("Answer text.", "Let the chat read Zotero libraries")


def test_tag_names_are_case_insensitive():
    assert run(["Ok <Suggestion>Show token cost per chat</SUGGESTION>"]) == ("Ok", "Show token cost per chat")


def test_unterminated_tag_content_is_the_suggestion():
    assert run(["Ok.\n<suggestion>Export notes as ", "markdown"]) == ("Ok.", "Export notes as markdown")


def test_unterminated_empty_tag_gives_no_suggestion():
    assert run(["Ok.\n<suggestion>"]) == ("Ok.", None)


def test_lone_angle_bracket_is_emitted():
    assert run(["a < b and c <", " d"]) == ("a < b and c < d", None)


def test_partial_tag_at_end_of_stream_is_emitted():
    assert run(["Use the <sugg"]) == ("Use the <sugg", None)


def test_only_the_first_of_two_tags_is_kept():
    text, found = run(["Text\n<suggestion>First idea</suggestion>\n<suggestion>Second idea</suggestion>"])
    assert (text, found) == ("Text", "First idea")


def test_text_after_tag_is_kept():
    assert run(["A <suggestion>x idea</suggestion> B"]) == ("A B", "x idea")


def test_holds_back_at_most_the_tag_length():
    flt = SuggestionFilter()
    out = flt.feed("hello <suggest")
    assert out == "hello"
    assert len(flt._pending) <= len("<suggestion>") + 1  # partial tag plus the space before it


def test_whitespace_inside_suggestion_is_collapsed():
    assert run(["x <suggestion>  Add\n  search by DOI </suggestion>"])[1] == "Add search by DOI"


# ── filter_events ─────────────────────────────────────────────────────────────

@pytest.fixture()
def recorded(monkeypatch):
    calls: list[dict] = []

    def fake_record(text, *, user, context="", conversation_id=None):
        calls.append({"text": text, "user": user, "context": context, "conversation_id": conversation_id})
        return {"id": "s1", "text": text, "votes": 1}

    monkeypatch.setattr(svc, "record_chat_suggestion", fake_record)
    monkeypatch.setattr(svc, "get_request_user", lambda: "alice")
    monkeypatch.setattr(svc.settings, "suggestions_from_chat", True)
    return calls


def tokens(*parts):
    return [{"type": "token", "text": p} for p in parts]


def test_filter_events_strips_tag_and_emits_suggestion(recorded):
    events = [{"type": "step", "n": 1}, *tokens("Hi.", "\n<sugg", "estion>Add X</suggestion>"), {"type": "done"}]
    out = list(filter_events(iter(events), question="how?" * 100, conversation_id="c1"))
    assert [e for e in out if e["type"] == "step"] == [{"type": "step", "n": 1}]
    assert "".join(e["text"] for e in out if e["type"] == "token") == "Hi."
    assert all(e["text"] for e in out if e["type"] == "token")
    assert out[-1] == {"type": "suggestion", "suggestion": {"id": "s1", "text": "Add X", "votes": 1}}
    assert {"type": "done"} in out
    assert recorded == [{"text": "Add X", "user": "alice", "context": ("how?" * 100)[:300], "conversation_id": "c1"}]


def test_filter_events_flushes_held_back_text(recorded):
    out = list(filter_events(iter(tokens("a <", "b")), question="q", conversation_id=None))
    assert "".join(e["text"] for e in out) == "a <b"
    assert recorded == []


def test_filter_events_records_nothing_when_disabled(recorded, monkeypatch):
    monkeypatch.setattr(svc.settings, "suggestions_from_chat", False)
    out = list(filter_events(iter(tokens("Hi <suggestion>Add X</suggestion>")), question="q", conversation_id=None))
    assert out == [{"type": "token", "text": "Hi"}]
    assert recorded == []


def test_recording_error_is_swallowed(monkeypatch):
    monkeypatch.setattr(svc.settings, "suggestions_from_chat", True)
    monkeypatch.setattr(svc, "get_request_user", lambda: "alice")

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "record_chat_suggestion", boom)
    out = list(filter_events(iter(tokens("Hi <suggestion>Add X</suggestion>")), question="q", conversation_id=None))
    assert out == [{"type": "token", "text": "Hi"}]


def test_inner_exception_propagates(recorded):
    def gen():
        yield {"type": "token", "text": "Hi"}
        raise ValueError("stream broke")

    it = filter_events(gen(), question="q", conversation_id=None)
    with pytest.raises(ValueError):
        list(it)
    assert recorded == []


def test_error_events_pass_through_unchanged(recorded):
    err = {"type": "error", "message": "nope"}
    assert list(filter_events(iter([err]), question="q", conversation_id=None)) == [err]


def test_held_text_is_released_before_a_step_event():
    from services.suggestions import filter_events

    events = [{"type": "token", "text": "First part "}, {"type": "step", "description": "x"},
              {"type": "token", "text": "second."}]
    out = list(filter_events(iter(events), question="q", conversation_id=None))
    texts = [(e["type"], e.get("text")) for e in out]
    assert texts == [("token", "First part"), ("token", " "), ("step", None), ("token", "second.")]
