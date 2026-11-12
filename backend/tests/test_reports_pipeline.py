"""Report pipeline: stages, progress, citations, cancel and failure, with retrieval, the model
and the query layer replaced (no Neo4j, no network)."""
from __future__ import annotations

import json
import re
import threading

import pytest

from db.queries import reports as rq
from services.reports import jobs, llm, pipeline, retrieval

OWNER = "alice"


class FakeReports:
    """In-memory stand-in for db.queries.reports with the same activity guards."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.edges: dict[str, list[dict]] = {}
        self.history: dict[str, list[tuple]] = {}
        self.counter = 0
        self.papers: dict[str, dict] = {}

    def install(self, monkeypatch) -> "FakeReports":
        for name in (
            "create_report get_report list_reports is_active update_progress finish_report "
            "fail_report cancel_report fail_interrupted delete_report report_papers"
        ).split():
            monkeypatch.setattr(rq, name, getattr(self, name))
        return self

    def create_report(self, driver, data):
        self.counter += 1
        rid = f"r{self.counter}"
        row = {
            "id": rid, "owner": data["owner"], "title": data.get("title", ""), "question": data.get("question", ""),
            "project_id": data.get("project_id", ""), "project_name": data.get("project_name", ""),
            "paper_ids_json": json.dumps(data.get("paper_ids") or []), "length": data.get("length", "standard"),
            "model": data.get("model", "fast"), "status": "queued", "stage": "queued", "progress": 0,
            "steps_json": rq.append_step("[]", "Queued"), "markdown": "", "error": "", "paper_count": 0,
            "word_count": 0, "created_at": f"2026-11-12T10:00:0{self.counter % 10}+00:00",
            "updated_at": "2026-11-12T10:00:00+00:00", "finished_at": "",
        }
        self.rows[rid] = row
        self.history[rid] = []
        return dict(row)

    def get_report(self, driver, rid):
        row = self.rows.get(rid)
        return dict(row) if row else None

    def list_reports(self, driver, owner=None, limit=500):
        rows = [r for r in self.rows.values() if owner is None or r["owner"] == owner]
        rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
        return [{k: v for k, v in r.items() if k != "markdown"} for r in rows]

    def is_active(self, driver, rid):
        return bool(self.rows.get(rid) and self.rows[rid]["status"] in rq.ACTIVE)

    def update_progress(self, driver, rid, *, status=None, stage=None, progress=None, step=None, title=None,
                        paper_count=None):
        row = self.rows.get(rid)
        if not row or row["status"] not in rq.ACTIVE:
            return False
        if status:
            row["status"] = status
        if stage:
            row["stage"] = stage
        if progress is not None:
            row["progress"] = progress
        if title:
            row["title"] = title
        if paper_count is not None:
            row["paper_count"] = paper_count
        if step:
            row["steps_json"] = rq.append_step(row["steps_json"], step)
        self.history[rid].append((row["stage"], row["progress"], step))
        return True

    def finish_report(self, driver, rid, *, title, markdown, word_count, cited):
        row = self.rows.get(rid)
        if not row or row["status"] not in rq.ACTIVE:
            return False
        row.update(status="done", stage="done", progress=100, title=title, markdown=markdown,
                   word_count=word_count, paper_count=len(cited), finished_at="2026-11-12T11:00:00+00:00",
                   steps_json=rq.append_step(row["steps_json"], "Report saved"))
        self.edges[rid] = list(cited)
        return True

    def _end(self, rid, status, error=""):
        row = self.rows.get(rid)
        if not row or row["status"] not in rq.ACTIVE:
            return False
        row.update(status=status, stage=status, error=error)
        return True

    def fail_report(self, driver, rid, error):
        return self._end(rid, "failed", (error or "Unknown error")[:1000])

    def cancel_report(self, driver, rid):
        return self._end(rid, "cancelled")

    def fail_interrupted(self, driver):
        n = 0
        for rid in list(self.rows):
            if self._end(rid, "failed", "Interrupted by a server restart"):
                n += 1
        return n

    def delete_report(self, driver, rid):
        self.edges.pop(rid, None)
        return self.rows.pop(rid, None) is not None

    def report_papers(self, driver, rid):
        return [
            {"id": c["id"], "title": self.papers.get(c["id"], {}).get("title", ""),
             "year": self.papers.get(c["id"], {}).get("year"), "n": c["n"]}
            for c in sorted(self.edges.get(rid, []), key=lambda c: c["n"])
        ]


PAPERS = {
    f"p{i}": {
        "id": f"p{i}", "title": f"Title of p{i}", "year": 2020 + i, "venue": "Venue X",
        "authors": ["Ann Author", "Bob Writer"], "summary": f"Summary of paper {i} about diffusion models.",
        "abstract": "", "claims": [f"Claim {i}a"], "note": "my note" if i == 1 else "", "highlights": [],
    }
    for i in range(1, 7)
}
PLAN = {
    "title": "Diffusion models in the library",
    "lede": "Plan lede.",
    "sections": [
        {"title": "Background", "focus": "Define things.", "queries": ["diffusion"], "candidates": ["C1", "C2", "C3"]},
        {"title": "Methods", "focus": "How they work.", "queries": ["sampler"], "candidates": ["C4", "C5", "C6"]},
        {"title": "Limits", "focus": "What is open.", "queries": [], "candidates": ["C2", "C5", "C6"]},
    ],
}
FRAME = {"lede": "The answer first.", "introduction": "Intro text [S1].", "closing": "Closing text [S4].\n\n- Open question?"}


@pytest.fixture
def env(monkeypatch):
    store = FakeReports().install(monkeypatch)
    store.papers = PAPERS
    monkeypatch.setattr(retrieval, "papers_by_ids", lambda d, ids: [
        {"id": i, "title": PAPERS[i]["title"], "year": PAPERS[i]["year"]} for i in ids if i in PAPERS])
    # The question search returns every paper; section queries return nothing, so a section holds
    # exactly the papers its plan names.
    monkeypatch.setattr(retrieval, "search", lambda d, q, project_id=None, limit=20: [
        {"id": f"p{i}", "title": f"Title of p{i}", "year": 2020 + i} for i in range(1, 7)][:limit]
        if q.startswith("How do") else [])
    monkeypatch.setattr(retrieval, "project_papers", lambda d, pid, limit=60: [])
    monkeypatch.setattr(retrieval, "fetch_evidence", lambda d, ids: {i: dict(PAPERS[i]) for i in ids if i in PAPERS})
    monkeypatch.setattr(retrieval, "fetch_raw", lambda d, ids: {
        i: "Intro. " * 50 + "Diffusion models denoise samples step by step. " + "Filler. " * 200 for i in ids})
    monkeypatch.setattr(llm, "evidence_budget", lambda model: 20_000)
    prompts: list[str] = []
    replies = {"plan": json.dumps(PLAN), "frame": json.dumps(FRAME)}

    def complete(messages, *, model, max_tokens, json_mode=False):
        prompt = messages[-1]["content"]
        prompts.append(prompt)
        if "plan a long-read report" in prompt:
            reply = replies["plan"]
        elif "finishing a long-read report" in prompt:
            reply = replies["frame"]
        else:
            n = len([p for p in prompts if "writing one section" in p])
            reply = f"Body {n}: diffusion works [S1] and also [S2, S4][S5]. Unknown source [S99]."
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm, "complete", complete)
    store.prompts, store.replies = prompts, replies
    return store


def make(env, **data):
    return env.create_report(None, {"owner": OWNER, "question": "How do diffusion models work?", **data})["id"]


def test_happy_path(env):
    rid = make(env)
    pipeline.run_report(rid, driver=object())
    row = env.rows[rid]
    assert row["status"] == "done" and row["progress"] == 100 and row["error"] == ""
    assert row["title"] == "Diffusion models in the library"
    md = row["markdown"]
    assert md.startswith("# Diffusion models in the library\n\nThe answer first.")
    assert "## Introduction" in md and "## Background" in md and "## Limits" in md
    assert "## What the library shows and what it does not" in md
    assert "[S" not in md and "S99" not in md
    # numbers follow first citation: S1 -> [1] ...
    assert "[[1]](/paper/p1)" in md and "## References" in md
    assert re.search(
        r"^1\. Ann Author, Bob Writer \(2021\)\. \*Title of p1\*\. Venue X\. \[Open in library\]\(/paper/p1\)$",
        md, re.M)
    ids = [c["id"] for c in env.edges[rid]]
    assert ids[0] == "p1" and len(ids) == len(set(ids))
    assert [c["n"] for c in env.edges[rid]] == list(range(1, len(ids) + 1))
    assert row["word_count"] > 20 and row["paper_count"] == len(ids)
    steps = [s["message"] for s in json.loads(row["steps_json"])]
    assert "Found 6 candidate papers" in steps
    assert "Writing section 3 of 3: Limits" in steps and steps[-1] == "Report saved"


def test_progress_numbers_are_monotonic_and_hit_the_marks(env):
    rid = make(env)
    pipeline.run_report(rid, driver=object())
    progress = [p for _, p, _ in env.history[rid]]
    assert progress == sorted(progress)
    for mark in (10, 20, 55, 90, 97):
        assert mark in progress
    stages = [s for s, _, _ in env.history[rid]]
    assert (stages.index("scope") < stages.index("plan") < stages.index("evidence")
            < stages.index("sections") < stages.index("frame") < stages.index("save"))


def test_section_prompts_hold_only_their_sources(env):
    rid = make(env)
    pipeline.run_report(rid, driver=object())
    sections = [p for p in env.prompts if "writing one section" in p]
    assert len(sections) == 3
    assert "Title of p1" in sections[0] and "[S1]" in sections[0] and "Title of p6" not in sections[0]
    assert "Title of p6" in sections[1] and "Title of p1" not in sections[1]
    assert "Your note: my note" in sections[0]
    assert "Passages:" in sections[0] and "Diffusion models denoise" in sections[0]
    assert "{{" not in "".join(sections)  # every placeholder replaced


def test_cancel_between_model_calls(env, monkeypatch):
    rid = make(env)
    inner = llm.complete
    calls = {"sections": 0}

    def cancelling(messages, **kw):
        if "writing one section" in messages[-1]["content"]:
            calls["sections"] += 1
            if calls["sections"] == 2:
                env.cancel_report(None, rid)
        return inner(messages, **kw)

    monkeypatch.setattr(llm, "complete", cancelling)
    pipeline.run_report(rid, driver=object())
    assert env.rows[rid]["status"] == "cancelled"
    assert calls["sections"] == 2  # no third section call, no frame call
    assert not any("finishing a long-read" in p for p in env.prompts)
    assert rid not in env.edges


def test_failure_is_recorded_not_raised(env):
    rid = make(env)
    env.replies["plan"] = RuntimeError("provider is down " + "x" * 2000)
    pipeline.run_report(rid, driver=object())
    row = env.rows[rid]
    assert row["status"] == "failed" and "provider is down" in row["error"] and len(row["error"]) <= 1000


def test_no_candidates_fails_with_a_clear_message(env, monkeypatch):
    monkeypatch.setattr(retrieval, "search", lambda *a, **k: [])
    rid = make(env)
    pipeline.run_report(rid, driver=object())
    assert env.rows[rid]["status"] == "failed" and "no papers" in env.rows[rid]["error"].lower()


def test_invalid_plan_falls_back_to_a_generic_outline(env):
    env.replies["plan"] = "sorry, no JSON here"
    rid = make(env, length="short")
    pipeline.run_report(rid, driver=object())
    row = env.rows[rid]
    assert row["status"] == "done"
    assert row["markdown"].count("\n## ") >= 5  # intro + 3 sections + closing + references
    assert len([p for p in env.prompts if "plan a long-read" in p]) == 2  # one retry


def test_invalid_frame_gets_a_generic_closing(env):
    env.replies["frame"] = "not json"
    rid = make(env)
    pipeline.run_report(rid, driver=object())
    md = env.rows[rid]["markdown"]
    assert env.rows[rid]["status"] == "done" and "## What the library shows and what it does not" in md


def test_deleted_report_stops_the_job(env):
    rid = make(env)
    env.delete_report(None, rid)
    pipeline.run_report(rid, driver=object())  # returns quietly
    assert rid not in env.rows


def test_project_without_question_asks_for_an_overview(env, monkeypatch):
    monkeypatch.setattr(retrieval, "project_papers", lambda d, pid, limit=60: [
        {"id": "p1", "title": "T", "year": 2021}, {"id": "p2", "title": "T", "year": 2022}])
    rid = env.create_report(None, {"owner": OWNER, "project_id": "proj", "project_name": "Thesis"})["id"]
    pipeline.run_report(rid, driver=object())
    assert env.rows[rid]["status"] == "done"
    plan_prompt = next(p for p in env.prompts if "plan a long-read" in p)
    assert "overview of the literature in the project" in plan_prompt and "Thesis" in plan_prompt


def test_request_user_is_the_owner_inside_the_job(env, monkeypatch):
    from services.auth import get_request_user

    seen = []

    def fetch(d, ids):
        seen.append(get_request_user())
        return {i: dict(PAPERS[i]) for i in ids if i in PAPERS}

    monkeypatch.setattr(retrieval, "fetch_evidence", fetch)
    rid = make(env)
    pipeline.run_report(rid, driver=object())
    assert seen and set(seen) == {OWNER}
    assert get_request_user() is None  # reset afterwards


# ------------------------------------------------------------------ units

def test_prompts_exist_and_use_explicit_placeholders():
    for name in ("report_plan.txt", "report_section.txt", "report_frame.txt"):
        text = (pipeline.PROMPTS_DIR / name).read_text(encoding="utf-8")
        assert "{{" in text and "{0}" not in text
    filled = pipeline.load_prompt("report_plan.txt", QUESTION="Q?", LENGTH="short", SECTIONS="3", CANDIDATES="C1 | t")
    assert "Q?" in filled and "{{" not in filled


def test_normalise_plan_clamps_and_drops_unknown_labels():
    data = {"title": "T", "sections": [
        {"title": "A", "focus": "f", "queries": ["q1", "q2", "q3", "q4"], "candidates": ["C1", "C9", 2, "c2"]},
        {"title": "", "candidates": []},
        {"title": "B"}, {"title": "C"},
    ]}
    plan = pipeline.normalise_plan(data, 2, {"C1": "a", "C2": "b"}, "question")
    assert [s["title"] for s in plan["sections"]] == ["A", "B"]
    assert plan["sections"][0]["ids"] == ["a", "b"] and len(plan["sections"][0]["queries"]) == 3
    with pytest.raises(ValueError):
        pipeline.normalise_plan({"sections": []}, 3, {}, "q")


def test_find_passages_picks_best_windows_and_nothing_without_terms():
    raw = "x " * 3000 + "diffusion sampler noise schedule " * 5 + "y " * 3000 + "diffusion once " + "z " * 3000
    out = retrieval.find_passages(raw, ["diffusion", "sampler", "schedule"])
    assert 1 <= len(out) <= 2 and "sampler" in out[0] and all(len(p) < 1400 for p in out)
    assert retrieval.find_passages(raw, []) == [] and retrieval.find_passages("", ["a"]) == []


def test_format_source_respects_limit_and_priority():
    ev = dict(PAPERS["p1"], highlights=[{"text": "hl", "note": "why"}], abstract="abs")
    block = retrieval.format_source("S3", ev, ["passage text " * 40], 400)
    assert block.startswith("[S3] Title of p1 (2021), Ann Author, Bob Writer. Venue X")
    assert len(block) <= 420 and "Summary:" in block and "Claims: Claim 1a" in block


def test_query_terms_skip_stopwords():
    assert retrieval.query_terms("What are the limits of diffusion models?", "Sampler") == [
        "limits", "diffusion", "models", "sampler"]


def test_parse_json_handles_fences_and_prose():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('Here you go: {"a": {"b": 2}} done') == {"a": {"b": 2}}
    for bad in ("", "no json", "{broken", "[1]"):
        with pytest.raises(ValueError):
            llm.parse_json(bad)


def test_model_labels():
    assert llm.claude_label("claude-sonnet-4-6") == "Claude Sonnet 4.6"
    assert llm.claude_label("claude-haiku-4-5-20251001") == "Claude Haiku 4.5"


# ------------------------------------------------------------------ jobs

def test_recover_interrupted_marks_active_reports_failed(env):
    a, b = make(env), make(env)
    env.update_progress(None, b, status="running")
    done = make(env)
    env.finish_report(None, done, title="t", markdown="m", word_count=1, cited=[])
    assert jobs.recover_interrupted(object()) == 2
    assert env.rows[a]["status"] == env.rows[b]["status"] == "failed"
    assert env.rows[a]["error"] == "Interrupted by a server restart"
    assert env.rows[done]["status"] == "done"


def test_jobs_start_runs_the_pipeline_with_a_cancel_event(monkeypatch):
    ran = threading.Event()
    seen = {}

    def fake_run(rid, cancel_event=None):
        seen["rid"], seen["event"] = rid, cancel_event
        ran.set()

    monkeypatch.setattr(pipeline, "run_report", fake_run)
    jobs.start("abc")
    assert ran.wait(5) and seen["rid"] == "abc" and not seen["event"].is_set()


def test_cancel_event_stops_a_job_before_its_next_step(env):
    rid = make(env)
    event = threading.Event()
    event.set()
    pipeline.run_report(rid, driver=object(), cancel_event=event)
    assert env.rows[rid]["status"] == "cancelled" and not env.prompts


@pytest.fixture(autouse=True)
def _no_request_user():
    """Importing mcp_server in-process (other tests) leaves a request user set; start clean."""
    from services.auth import reset_request_user, set_request_user

    token = set_request_user(None)
    yield
    reset_request_user(token)
