"""SQLite ledger: recording and the aggregates behind /tokens (services/usage/ledger.py)."""
from datetime import datetime, timedelta, timezone

import pytest

from config import settings
from services.usage import ledger

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "usage_db_path", str(tmp_path / "usage.sqlite"))
    monkeypatch.setattr(settings, "usage_ledger_enabled", True)
    ledger.close()
    yield tmp_path / "usage.sqlite"
    ledger.close()


def _row(days_ago=0, **kw):
    ts = NOW - timedelta(days=days_ago)
    base = {
        "ts": ts.isoformat(), "feature": "summary", "label": "services.ai.summarize_paper",
        "provider": "anthropic", "model": "claude-opus-4-6", "input_tokens": 1000, "output_tokens": 100,
        "cost_usd": 0.01, "price_known": 1, "username": "alice", "latency_ms": 500,
    }
    base.update(kw)
    return base


def test_record_creates_file_and_row(db):
    assert ledger.record(_row())
    assert db.exists()
    rows, total = ledger.calls()
    assert total == 1
    r = rows[0]
    assert r["feature"] == "summary" and r["user"] == "alice" and r["ok"] is True
    assert r["price_known"] is True and r["streamed"] is False and r["estimated"] is False
    assert r["cost_usd"] == pytest.approx(0.01)


def test_record_disabled_does_nothing(db, monkeypatch):
    monkeypatch.setattr(settings, "usage_ledger_enabled", False)
    assert ledger.record(_row()) is False
    assert not db.exists()


def test_record_never_raises(tmp_path, monkeypatch):
    # the path's parent is a file: sqlite cannot open it
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(settings, "usage_db_path", str(blocker / "sub" / "u.sqlite"))
    ledger.close()
    assert ledger.record(_row()) is False


def test_reopens_when_path_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "usage_db_path", str(tmp_path / "a.sqlite"))
    ledger.close()
    ledger.record(_row())
    monkeypatch.setattr(settings, "usage_db_path", str(tmp_path / "b.sqlite"))
    assert ledger.calls()[1] == 0
    ledger.record(_row())
    ledger.record(_row())
    assert ledger.calls()[1] == 2
    ledger.close()


def test_totals_since(db):
    ledger.record(_row(0))
    ledger.record(_row(0, ok=0, username="bob", cost_usd=0.5))
    ledger.record(_row(3))
    since = (NOW - timedelta(hours=2)).isoformat()
    t = ledger.totals_since(since)
    assert t == {"calls": 2, "errors": 1, "input_tokens": 2000, "output_tokens": 200, "cost_usd": pytest.approx(0.51)}
    assert ledger.totals_since(since, "bob")["calls"] == 1


def test_summary_shape_and_totals(db):
    ledger.record(_row(0))
    ledger.record(_row(0, feature="topics", model="claude-haiku-4-5", cost_usd=0.001, username=None, paper_id="p1"))
    ledger.record(_row(1, provider="claude-code", model="opus", cost_usd=1.5, feature="knowledge-chat",
                       cache_read_tokens=7, cache_write_tokens=3))
    ledger.record(_row(2, model="mystery", cost_usd=None, price_known=0, paper_id="p1", ok=0))
    ledger.record(_row(40))  # outside the range

    s = ledger.summary(days=30, now=NOW)
    assert s["range"]["days"] == 30
    assert s["range"]["since"] == "2026-10-14T00:00:00+00:00"
    t = s["totals"]
    assert t["calls"] == 4 and t["errors"] == 1 and t["unknown_price_calls"] == 1
    assert t["cache_read_tokens"] == 7 and t["cache_write_tokens"] == 3
    assert t["cost_usd"] == pytest.approx(0.01 + 0.001 + 1.5)
    assert t["subscription_usd"] == pytest.approx(1.5)
    assert t["billed_usd"] == pytest.approx(0.011)
    assert s["today"]["calls"] == 2

    assert len(s["by_day"]) == 30
    assert s["by_day"][-1]["day"] == "2026-11-12" and s["by_day"][-1]["calls"] == 2
    assert s["by_day"][0]["calls"] == 0  # zero-filled, oldest first
    assert [d["day"] for d in s["by_day"]] == sorted(d["day"] for d in s["by_day"])
    assert sum(w["calls"] for w in s["by_week"]) == 4
    assert s["by_week"][-1]["week"] == "2026-W46" and s["by_week"][-1]["start"] == "2026-11-09"

    assert s["by_feature"][0]["feature"] == "knowledge-chat"  # costliest first
    assert {f["feature"] for f in s["by_feature"]} == {"summary", "topics", "knowledge-chat"}
    assert s["by_feature"][-1]["avg_latency_ms"] == 500
    models = {m["model"]: m for m in s["by_model"]}
    assert models["mystery"]["price_known"] is False and models["opus"]["provider"] == "claude-code"
    assert {p["provider"] for p in s["by_provider"]} == {"anthropic", "claude-code"}
    users = {u["user"]: u for u in s["by_user"]}
    assert set(users) == {"alice", "(system)"} and users["(system)"]["calls"] == 1
    assert s["top_calls"][0]["cost_usd"] == pytest.approx(1.5) and len(s["top_calls"]) == 4
    assert s["top_papers"] == [{"paper_id": "p1", "title": None, "calls": 2, "input_tokens": 2000,
                                "output_tokens": 200, "cost_usd": pytest.approx(0.001)}]
    assert s["unknown_models"] == ["mystery"]


def test_summary_filters_and_user_scope(db):
    ledger.record(_row(0))
    ledger.record(_row(0, username="bob", feature="topics"))
    s = ledger.summary(days=7, user="bob", now=NOW)
    assert s["totals"]["calls"] == 1 and s["today"]["calls"] == 1
    s = ledger.summary(days=7, feature="summary", now=NOW)
    assert s["totals"]["calls"] == 1 and s["today"]["calls"] == 2  # today ignores feature/model filters
    assert ledger.summary(days=7, include_users=False, now=NOW)["by_user"] == []
    assert ledger.summary(days=7, user="(system)", now=NOW)["totals"]["calls"] == 0


def test_calls_filters_paging_and_order(db):
    for i in range(5):
        ledger.record(_row(i, feature="a" if i % 2 else "b", paper_id="p9" if i == 4 else None, ok=0 if i == 3 else 1))
    rows, total = ledger.calls(limit=2, offset=0)
    assert total == 5 and len(rows) == 2 and rows[0]["ts"] > rows[1]["ts"]
    assert ledger.calls(limit=2, offset=4)[0][0]["ts"] == (NOW - timedelta(days=4)).isoformat()
    assert ledger.calls(feature="a")[1] == 2
    assert ledger.calls(paper_id="p9")[1] == 1
    assert ledger.calls(ok=False)[1] == 1
    assert ledger.calls(provider="openai")[1] == 0
