"""vectors_export.py: the texts the live code embeds, written as JSONL plus spec.json, never into a repository."""
from __future__ import annotations

import json
import os
import stat

import pytest

from services.feed.pipeline import _candidate_text
from services.feed.store import Candidate, FeedStore
from services.library_search import semantic
from tests.bulk_embed_helpers import load_script

export = load_script("vectors_export")

PAPERS = [
    {"id": "p2", "title": " Second synthetic paper ", "abstract": "An abstract.\nWith a second line.", "summary": None},
    {"id": "p1", "title": "First synthetic paper", "abstract": None, "summary": "## Summary\n**Bold** words here"},
    {"id": "p3", "title": "Title only", "abstract": "", "summary": ""},
]


class Rows(list):
    def single(self):
        return self[0] if self else None


class FakeDriver:
    """Answers the semantic sync's one query (every paper) like the graph does."""

    def __init__(self, papers):
        self.papers, self.queries = papers, []

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.queries.append(query)
        assert "MATCH (p:Paper)" in query
        return Rows(dict(p) for p in self.papers)


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(autouse=True)
def _restore_model_environment(monkeypatch):
    """``main`` writes the --model options into os.environ (it is a command line tool); give them back."""
    for var in ("EMBED_MODEL", "EMBED_DIM", "EMBED_POOLING", "EMBED_QUERY_PREFIX", "EMBED_DOC_PREFIX"):
        monkeypatch.setenv(var, "x")
        monkeypatch.delenv(var)


@pytest.fixture
def feed(tmp_path):
    st = FeedStore(tmp_path / "feed.sqlite")
    st.upsert_candidates([
        Candidate("c1", "arxiv", "2501.00001", "Candidate one", "2026-01-02", abstract="Abstract one", fetched_at="2026-01-03T00:00:00+00:00"),
        Candidate("c2", "biorxiv", "10.1101/x", "Candidate two", "2026-01-05", abstract="", fetched_at="2026-01-06T00:00:00+00:00"),
    ])
    yield st
    st.close()


# ── the output directory ──────────────────────────────────────────────────────────────────────────

def test_a_directory_inside_a_git_repository_is_refused(tmp_path):
    repo = tmp_path / "work" / "repo"
    (repo / ".git").mkdir(parents=True)
    for inside in (repo, repo / "export", repo / "a" / "b" / "export"):
        with pytest.raises(SystemExit, match="git repository"):
            export.refuse_unsafe_output(inside)
    # a worktree has a .git *file*
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: elsewhere\n")
    with pytest.raises(SystemExit, match="git repository"):
        export.refuse_unsafe_output(wt / "out")


def test_the_backend_code_directory_is_refused():
    with pytest.raises(SystemExit):
        export.refuse_unsafe_output(export.BACKEND_DIR / "export")


def test_a_symlink_into_a_repository_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    link = tmp_path / "link"
    os.symlink(repo, link)
    with pytest.raises(SystemExit):
        export.refuse_unsafe_output(link / "export")


def test_another_directory_is_accepted(tmp_path):
    assert export.refuse_unsafe_output(tmp_path / "out" / "export") == (tmp_path / "out" / "export").resolve()


# ── the texts ─────────────────────────────────────────────────────────────────────────────────────

def test_library_texts_are_what_the_semantic_sync_embeds(tmp_path):
    out = tmp_path / "e"
    records = export.collect(["library"], FakeDriver(PAPERS))
    want = {p["id"]: semantic.paper_text(p["title"], p["abstract"], p["summary"]) for p in PAPERS}
    assert [r["id"] for r in records["library"]] == ["p1", "p2", "p3"]           # sorted: reproducible
    for r in records["library"]:
        assert r["text"] == want[r["id"]] and r["hash"] == semantic.text_hash(want[r["id"]])
        assert r["meta"] == {"kind": "paper", "source": "library"}
    assert want["p1"].startswith("First synthetic paper\nSummary Bold words here")      # summary cleaned like the index
    assert want["p3"] == "Title only"


def test_the_feed_namespace_uses_the_candidate_text_and_metadata(feed):
    recs = export.collect(["feed"], None, feed)["feed"]
    cands = {c.id: c for c in feed.all_candidates()}
    assert {r["id"] for r in recs} == {"c1", "c2"}
    for r in recs:
        c = cands[r["id"]]
        assert r["text"] == _candidate_text(c)
        assert r["meta"] == {"kind": "candidate", "source": c.source, "published": c.published, "added_at": c.fetched_at}
    assert next(r for r in recs if r["id"] == "c1")["text"] == "Candidate one\nAbstract one"


def test_feed_library_holds_what_the_search_index_will_not(monkeypatch):
    drv = FakeDriver(PAPERS)
    monkeypatch.setenv("LIBRARY_SEMANTIC", "true")
    assert export.collect(["library", "feed_library"], drv)["feed_library"] == []     # the index covers every paper
    monkeypatch.setenv("LIBRARY_SEMANTIC", "false")
    recs = export.collect(["feed_library"], drv)["feed_library"]
    assert [r["id"] for r in recs] == ["p1", "p2", "p3"]
    assert recs[0]["meta"] == {"kind": "library", "source": "feed_cache"} and recs[0]["hash"]


def test_the_export_reads_only(feed):
    drv = FakeDriver(PAPERS)
    export.collect(["library", "feed", "feed_library"], drv, feed)
    assert all(q.lstrip().startswith("MATCH") and "SET" not in q and "CREATE" not in q and "DELETE" not in q
               for q in drv.queries)


# ── the files ─────────────────────────────────────────────────────────────────────────────────────

def test_write_export_gives_jsonl_and_a_spec(tmp_path):
    from services.vectorstore.model_config import ModelSpec, TEXT_FORMAT

    out = tmp_path / "e"
    records = export.collect(["library"], FakeDriver(PAPERS))
    (out).mkdir()
    (out / "library.npy").write_bytes(b"stale")          # vectors of an earlier export must not survive
    spec = ModelSpec("example/target", 768, "mean", "", "")
    doc = export.write_export(out, spec, records, 256)
    assert doc == json.loads((out / "spec.json").read_text())
    assert doc["model"] == "example/target" and doc["dim"] == 768 and doc["pooling"] == "mean"
    assert doc["doc_prefix"] == "" and doc["text_format"] == TEXT_FORMAT and doc["max_length"] == 256
    assert doc["counts"] == {"library": 3} and doc["format"] == 1
    lines = read(out / "library.jsonl")
    assert [l["id"] for l in lines] == ["p1", "p2", "p3"] and set(lines[0]) == {"id", "text", "hash", "meta"}
    assert lines[1]["text"] == "Second synthetic paper\nAn abstract.\nWith a second line."     # newline survives JSON
    assert not (out / "library.npy").exists() and not list(out.glob("*.tmp"))
    assert stat.S_IMODE(out.stat().st_mode) == 0o700 and stat.S_IMODE((out / "library.jsonl").stat().st_mode) == 0o600


def test_the_command_end_to_end(monkeypatch, tmp_path, feed, capsys):
    import db.connection

    monkeypatch.setattr(db.connection, "get_driver", lambda: FakeDriver(PAPERS))
    monkeypatch.setenv("PAPER_FEED", "true")
    monkeypatch.setenv("PAPER_FEED_DIR", str(feed.path.parent))
    for var in ("EMBED_DIM", "EMBED_POOLING", "EMBED_DOC_PREFIX", "EMBED_QUERY_PREFIX", "CONFERENCE_EMBED_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    out = tmp_path / "exp"
    assert export.main(["--out", str(out), "--model", "J0nasW/sciembed-full"]) == 0
    spec = json.loads((out / "spec.json").read_text())
    assert (spec["model"], spec["dim"], spec["pooling"]) == ("J0nasW/sciembed-full", 768, "mean")
    assert spec["counts"] == {"library": 3, "feed": 2, "feed_library": 0}
    assert len(read(out / "library.jsonl")) == 3 and len(read(out / "feed.jsonl")) == 2
    assert (out / "feed_library.jsonl").read_text() == ""
    assert "library: 3 texts" in capsys.readouterr().out


def test_without_the_feed_only_the_library_is_exported(monkeypatch, tmp_path, capsys):
    import db.connection

    monkeypatch.setattr(db.connection, "get_driver", lambda: FakeDriver(PAPERS))
    monkeypatch.delenv("PAPER_FEED", raising=False)
    out = tmp_path / "exp"
    assert export.main(["--out", str(out), "--model", "J0nasW/sciembed-full"]) == 0
    assert json.loads((out / "spec.json").read_text())["counts"] == {"library": 3}
    assert not (out / "feed.jsonl").exists() and "PAPER_FEED is off" in capsys.readouterr().out


def test_the_command_refuses_a_repository_before_touching_anything(monkeypatch, tmp_path):
    import db.connection

    monkeypatch.setattr(db.connection, "get_driver", lambda: pytest.fail("the database must not be opened"))
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(SystemExit):
        export.main(["--out", str(tmp_path / "repo" / "export")])
    assert not (tmp_path / "repo" / "export").exists()


def test_an_unknown_model_needs_its_dimension(monkeypatch, tmp_path):
    for var in ("EMBED_DIM", "EMBED_MODEL", "CONFERENCE_EMBED_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        export.main(["--out", str(tmp_path / "exp"), "--model", "example/unlisted-model"])
