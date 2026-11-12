"""SQLite store of every LLM call (table ``llm_calls``) and the aggregates read from it.

One lazily opened connection (WAL, ``check_same_thread=False``) guarded by a lock; the file
is ``USAGE_DB_PATH`` (default ``backend/data/usage.sqlite``) and is reopened when the
setting changes. Recording never raises into the caller.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config import settings

log = logging.getLogger(__name__)

SYSTEM_USER = "(system)"
SUBSCRIPTION_PROVIDER = "claude-code"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    feature TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    price_known INTEGER NOT NULL DEFAULT 0,
    username TEXT,
    paper_id TEXT,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    streamed INTEGER NOT NULL DEFAULT 0,
    estimated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
CREATE INDEX IF NOT EXISTS idx_llm_calls_day ON llm_calls(day);
CREATE INDEX IF NOT EXISTS idx_llm_calls_username ON llm_calls(username);
CREATE INDEX IF NOT EXISTS idx_llm_calls_feature ON llm_calls(feature);
CREATE INDEX IF NOT EXISTS idx_llm_calls_paper ON llm_calls(paper_id);
"""

_COLUMNS = (
    "ts", "day", "feature", "label", "provider", "model", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "cost_usd", "price_known", "username", "paper_id",
    "ok", "error", "latency_ms", "streamed", "estimated",
)

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None
_last_error_log = 0.0


def db_path() -> str:
    """Configured ledger file (absolute)."""
    configured = (settings.usage_db_path or "").strip()
    if configured:
        return str(Path(configured).expanduser())
    return str(Path(__file__).resolve().parents[2] / "data" / "usage.sqlite")


def _connect() -> sqlite3.Connection:
    """The shared connection, (re)opened when the configured path changed. Call under _lock."""
    global _conn, _conn_path
    path = db_path()
    if _conn is not None and _conn_path == path:
        return _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:  # noqa: BLE001
            pass
        _conn = None
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    conn.commit()
    _conn, _conn_path = conn, path
    return conn


def close() -> None:
    """Close the connection (tests; it reopens on the next use)."""
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
        _conn, _conn_path = None, None


def enabled() -> bool:
    return bool(settings.usage_ledger_enabled)


def record(row: dict[str, Any]) -> bool:
    """Insert one call row. Returns False (and logs at most once a minute) when it failed."""
    global _last_error_log
    if not enabled():
        return False
    now = datetime.now(timezone.utc)
    data = {
        "ts": now.isoformat(timespec="milliseconds"),
        "day": now.strftime("%Y-%m-%d"),
        "feature": "unknown",
        "label": "",
        "provider": "unknown",
        "model": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": None,
        "price_known": 0,
        "username": None,
        "paper_id": None,
        "ok": 1,
        "error": None,
        "latency_ms": 0,
        "streamed": 0,
        "estimated": 0,
    }
    data.update({k: v for k, v in row.items() if k in data})
    if "username" not in row and row.get("user") is not None:
        data["username"] = row["user"]
    if row.get("ts") and "day" not in row:
        data["day"] = str(row["ts"])[:10]
    try:
        with _lock:
            conn = _connect()
            conn.execute(
                f"INSERT INTO llm_calls ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
                [data[c] for c in _COLUMNS],
            )
            conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — never raise into the call path
        if time.monotonic() - _last_error_log > 60:
            _last_error_log = time.monotonic()
            log.warning("Token ledger write failed (call dropped): %s: %s", type(exc).__name__, exc)
        return False


# ── queries ───────────────────────────────────────────────────────────────────

def _query(sql: str, params: list[Any] | tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return _connect().execute(sql, params).fetchall()


def _where(
    since_day: str | None = None,
    user: str | None = None,
    feature: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    paper_id: str | None = None,
    ok: bool | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if since_day:
        clauses.append("day >= ?")
        params.append(since_day)
    if user:
        if user == SYSTEM_USER:
            clauses.append("username IS NULL")
        else:
            clauses.append("username = ?")
            params.append(user)
    for column, value in (("feature", feature), ("model", model), ("provider", provider), ("paper_id", paper_id)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if ok is not None:
        clauses.append("ok = ?")
        params.append(1 if ok else 0)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _num(value: Any) -> float:
    return round(float(value or 0.0), 8)


def totals_since(since_iso: str, username: str | None = None) -> dict[str, Any]:
    """Calls, errors, tokens and cost since an ISO timestamp (the Health page's "today")."""
    sql = (
        "SELECT COUNT(*) AS calls, COALESCE(SUM(1 - ok), 0) AS errors, "
        "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
        "COALESCE(SUM(cost_usd), 0) AS cost_usd FROM llm_calls WHERE ts >= ?"
    )
    params: list[Any] = [since_iso]
    if username:
        sql += " AND username = ?"
        params.append(username)
    try:
        r = _query(sql, params)[0]
    except Exception as exc:  # noqa: BLE001
        log.warning("Token ledger read failed: %s", exc)
        return {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    return {
        "calls": int(r["calls"]), "errors": int(r["errors"]),
        "input_tokens": int(r["input_tokens"]), "output_tokens": int(r["output_tokens"]),
        "cost_usd": _num(r["cost_usd"]),
    }


def call_row(r: sqlite3.Row) -> dict[str, Any]:
    """A ledger row as the API's CallRow."""
    return {
        "id": r["id"], "ts": r["ts"], "feature": r["feature"], "label": r["label"],
        "provider": r["provider"], "model": r["model"],
        "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
        "cache_read_tokens": r["cache_read_tokens"], "cache_write_tokens": r["cache_write_tokens"],
        "cost_usd": r["cost_usd"], "price_known": bool(r["price_known"]),
        "user": r["username"], "paper_id": r["paper_id"],
        "ok": bool(r["ok"]), "error": r["error"], "latency_ms": r["latency_ms"],
        "streamed": bool(r["streamed"]), "estimated": bool(r["estimated"]),
    }


def calls(
    *, limit: int = 100, offset: int = 0, days: int | None = None, user: str | None = None,
    feature: str | None = None, model: str | None = None, provider: str | None = None,
    paper_id: str | None = None, ok: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Newest-first page of calls and the total number matching the filters."""
    since_day = _since_day(days) if days else None
    where, params = _where(since_day, user, feature, model, provider, paper_id, ok)
    total = _query(f"SELECT COUNT(*) AS n FROM llm_calls{where}", params)[0]["n"]
    rows = _query(
        f"SELECT * FROM llm_calls{where} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)],
    )
    return [call_row(r) for r in rows], int(total)


def _since_day(days: int, today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    return (today - timedelta(days=max(1, days) - 1)).isoformat()


_SUM = (
    "COUNT(*) AS calls, COALESCE(SUM(1 - ok), 0) AS errors, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
    "COALESCE(SUM(cost_usd), 0) AS cost_usd"
)
_ORDER = "ORDER BY cost_usd DESC, calls DESC"


def summary(
    *, days: int = 30, user: str | None = None, feature: str | None = None, model: str | None = None,
    include_users: bool = True, now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregates for the Tokens page (everything of the API's /tokens/summary except scope,
    prices_as_of and paper titles, which the router adds)."""
    now = now or datetime.now(timezone.utc)
    days = max(1, int(days))
    since_day = _since_day(days, now.date())
    where, params = _where(since_day, user, feature, model)
    sub = f"provider = '{SUBSCRIPTION_PROVIDER}'"

    t = _query(
        f"SELECT {_SUM}, COALESCE(SUM(cache_read_tokens), 0) AS cr, COALESCE(SUM(cache_write_tokens), 0) AS cw, "
        f"COALESCE(SUM(CASE WHEN {sub} THEN cost_usd ELSE 0 END), 0) AS sub_cost, "
        f"COALESCE(SUM(1 - price_known), 0) AS unknown FROM llm_calls{where}", params)[0]
    total_cost = _num(t["cost_usd"])
    totals = {
        "calls": int(t["calls"]), "errors": int(t["errors"]),
        "input_tokens": int(t["input_tokens"]), "output_tokens": int(t["output_tokens"]),
        "cache_read_tokens": int(t["cr"]), "cache_write_tokens": int(t["cw"]),
        "cost_usd": total_cost, "billed_usd": _num(total_cost - float(t["sub_cost"])),
        "subscription_usd": _num(t["sub_cost"]), "unknown_price_calls": int(t["unknown"]),
    }

    # today: the user scope only, not the feature/model filters
    td_where, td_params = _where(now.strftime("%Y-%m-%d"), user)
    td = _query(f"SELECT {_SUM} FROM llm_calls{td_where}", td_params)[0]
    today = {
        "calls": int(td["calls"]), "errors": int(td["errors"]),
        "input_tokens": int(td["input_tokens"]), "output_tokens": int(td["output_tokens"]),
        "cost_usd": _num(td["cost_usd"]),
    }

    day_rows = {
        r["day"]: r for r in _query(f"SELECT day, {_SUM} FROM llm_calls{where} GROUP BY day", params)
    }
    by_day: list[dict[str, Any]] = []
    first = now.date() - timedelta(days=days - 1)
    for i in range(days):
        d = (first + timedelta(days=i)).isoformat()
        r = day_rows.get(d)
        by_day.append({
            "day": d, "calls": int(r["calls"]) if r else 0,
            "input_tokens": int(r["input_tokens"]) if r else 0,
            "output_tokens": int(r["output_tokens"]) if r else 0,
            "cost_usd": _num(r["cost_usd"]) if r else 0.0,
        })

    weeks: dict[str, dict[str, Any]] = {}
    for row in by_day:
        d = date.fromisoformat(row["day"])
        iso = d.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        w = weeks.setdefault(key, {
            "week": key, "start": (d - timedelta(days=d.weekday())).isoformat(),
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        })
        for k in ("calls", "input_tokens", "output_tokens"):
            w[k] += row[k]
        w["cost_usd"] = _num(w["cost_usd"] + row["cost_usd"])
    by_week = sorted(weeks.values(), key=lambda w: w["start"])

    by_feature = [
        {"feature": r["feature"], "calls": int(r["calls"]), "errors": int(r["errors"]),
         "input_tokens": int(r["input_tokens"]), "output_tokens": int(r["output_tokens"]),
         "cost_usd": _num(r["cost_usd"]), "avg_latency_ms": int(round(r["avg_latency"] or 0))}
        for r in _query(
            f"SELECT feature, {_SUM}, AVG(latency_ms) AS avg_latency FROM llm_calls{where} "
            f"GROUP BY feature {_ORDER}", params)
    ]
    by_model = [
        {"model": r["model"], "provider": r["provider"], "calls": int(r["calls"]),
         "input_tokens": int(r["input_tokens"]), "output_tokens": int(r["output_tokens"]),
         "cost_usd": _num(r["cost_usd"]), "price_known": bool(r["known"])}
        for r in _query(
            f"SELECT model, provider, {_SUM}, MIN(price_known) AS known FROM llm_calls{where} "
            f"GROUP BY model, provider {_ORDER}", params)
    ]
    by_provider = [
        {"provider": r["provider"], "calls": int(r["calls"]), "cost_usd": _num(r["cost_usd"])}
        for r in _query(f"SELECT provider, {_SUM} FROM llm_calls{where} GROUP BY provider {_ORDER}", params)
    ]
    by_user: list[dict[str, Any]] = []
    if include_users:
        by_user = [
            {"user": r["username"] or SYSTEM_USER, "calls": int(r["calls"]),
             "input_tokens": int(r["input_tokens"]), "output_tokens": int(r["output_tokens"]),
             "cost_usd": _num(r["cost_usd"])}
            for r in _query(f"SELECT username, {_SUM} FROM llm_calls{where} GROUP BY username {_ORDER}", params)
        ]

    top_calls = [
        call_row(r) for r in _query(
            f"SELECT * FROM llm_calls{where} ORDER BY COALESCE(cost_usd, -1) DESC, id DESC LIMIT 20", params)
    ]
    paper_where = where + (" AND " if where else " WHERE ") + "paper_id IS NOT NULL"
    top_papers = [
        {"paper_id": r["paper_id"], "title": None, "calls": int(r["calls"]),
         "input_tokens": int(r["input_tokens"]), "output_tokens": int(r["output_tokens"]),
         "cost_usd": _num(r["cost_usd"])}
        for r in _query(
            f"SELECT paper_id, {_SUM} FROM llm_calls{paper_where} GROUP BY paper_id {_ORDER} LIMIT 20", params)
    ]
    unknown_where = where + (" AND " if where else " WHERE ") + "price_known = 0"
    unknown_models = [
        r["model"] for r in _query(
            f"SELECT DISTINCT model FROM llm_calls{unknown_where} ORDER BY model", params)
    ]

    return {
        "range": {
            "since": datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
            "until": now.isoformat(timespec="seconds"), "days": days,
        },
        "totals": totals, "today": today, "by_day": by_day, "by_week": by_week,
        "by_feature": by_feature, "by_model": by_model, "by_provider": by_provider,
        "by_user": by_user, "top_calls": top_calls, "top_papers": top_papers,
        "unknown_models": unknown_models,
    }
