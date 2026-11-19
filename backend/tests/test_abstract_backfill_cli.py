"""scripts/backfill_abstracts.py: report path safety, dry run default, apply needs a report,
undo from a report. The database is the fake driver, HTTP the fake web."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from services import abstract_backfill as ab
from tests.abstract_backfill_helpers import LONG, FakeDriver, FakeWeb, paper

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_abstracts as cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
in_checkout = pytest.mark.skipif(not (REPO_ROOT / ".git").exists(), reason="not a git checkout (e.g. a source archive)")


@pytest.fixture
def env(monkeypatch):
    driver = FakeDriver([paper("p1", "10.1111/a", "Alpha scaling of toy systems"),
                         paper("p2", "10.1111/b", "Beta response of toy systems")])
    web = FakeWeb()
    web.openalex["10.1111/a"] = ("Alpha scaling of toy systems", LONG)
    monkeypatch.setattr(ab, "Http", lambda contact="": web.http(contact=contact))
    monkeypatch.delenv("ABSTRACT_BACKFILL_CONTACT", raising=False)
    return driver, web


@in_checkout
def test_refuses_a_report_inside_the_repository(env, capsys):
    driver, _ = env
    for bad in (REPO_ROOT / "report.json", REPO_ROOT / "backend" / "new_dir" / "r.json"):
        assert cli.main(["--report", str(bad)], driver=driver) == 2
        assert not bad.exists()
    assert "inside a git repository" in capsys.readouterr().err
    assert driver.queries == []                                # refused before touching anything


def test_refuses_a_report_inside_any_git_work_tree(env, tmp_path):
    (tmp_path / "other_repo" / ".git").mkdir(parents=True)
    assert cli.main(["--report", str(tmp_path / "other_repo" / "sub" / "r.json")], driver=env[0]) == 2


@in_checkout
def test_a_symlink_into_the_repository_does_not_get_around_it(env, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(REPO_ROOT)
    assert cli.main(["--report", str(link / "r.json")], driver=env[0]) == 2


@in_checkout
def test_inside_git_repo_helper(tmp_path):
    assert cli.inside_git_repo(tmp_path / "x" / "y.json") is None
    assert cli.inside_git_repo(REPO_ROOT / "x.json") == REPO_ROOT


def test_dry_run_is_default_prints_counts_and_writes_a_private_report(env, tmp_path, capsys):
    driver, _ = env
    path = tmp_path / "reports" / "dry.json"
    assert cli.main(["--report", str(path)], driver=driver) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["counts"]["would_apply"] == 1 and "papers" not in out
    report = json.loads(path.read_text())
    assert report["papers"][0]["id"] == "p1" and report["papers"][0]["outcome"] == "would_apply"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert driver.writes == []


def test_apply_needs_a_report_path(env, capsys):
    driver, _ = env
    assert cli.main(["--apply"], driver=driver) == 2
    assert "--report" in capsys.readouterr().err and driver.queries == []


def test_apply_then_undo_roundtrip(env, tmp_path, capsys):
    driver, _ = env
    path = tmp_path / "run1.json"
    assert cli.main(["--apply", "--report", str(path)], driver=driver) == 0
    assert driver.get("p1")["abstract"] == LONG and json.loads(capsys.readouterr().out)["counts"]["applied"] == 1

    assert cli.main(["--undo-report", str(path)], driver=driver) == 0           # dry run
    assert json.loads(capsys.readouterr().out)["would_clear"] == 1 and driver.get("p1")["abstract"] == LONG

    assert cli.main(["--undo-report", str(path), "--apply"], driver=driver) == 0
    assert json.loads(capsys.readouterr().out)["cleared"] == 1
    assert "abstract" not in driver.get("p1") and "abstract_source" not in driver.get("p1")


def test_undo_never_removes_a_user_written_abstract(env, tmp_path, capsys):
    driver, _ = env
    path = tmp_path / "run1.json"
    cli.main(["--apply", "--report", str(path)], driver=driver)
    capsys.readouterr()
    driver.get("p1")["abstract"] = "My own words."
    cli.main(["--undo-report", str(path), "--apply"], driver=driver)
    assert json.loads(capsys.readouterr().out)["skipped_text_changed"] == 1
    assert driver.get("p1")["abstract"] == "My own words."


def test_options_are_passed_through(env, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(ab, "run_backfill", lambda driver, **kw: seen.update(kw) or {"counts": {}, "papers": []})
    assert cli.main(["--limit", "5", "--include-stubs", "--sources", "crossref,openalex", "--title-search"], driver=env[0]) == 0
    assert seen == {"dry_run": True, "limit": 5, "include_stubs": True,
                    "sources": ["crossref", "openalex"], "title_search": True}


@pytest.mark.parametrize("argv", [["--sources", "pubmed"], ["--limit", "0"]])
def test_bad_options_exit_2(env, argv, capsys):
    assert cli.main(argv, driver=env[0]) == 2
    assert env[0].queries == []


def test_unreadable_undo_report_exits_2(env, tmp_path):
    assert cli.main(["--undo-report", str(tmp_path / "missing.json")], driver=env[0]) == 2
