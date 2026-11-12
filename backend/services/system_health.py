"""System health (.specs/016_health.md): the state of the whole instance in one response.

Every check returns ``{"id", "label", "status", "summary", "details", "checked_at",
"latency_ms"}``; ``status`` is ``ok | warn | error | off`` (``off`` = not configured). Checks
are cached per id (their own TTL, ``refresh=True`` bypasses), the uncached ones run
concurrently under an overall time cap, and a check that raises shows as ``error`` instead of
failing the endpoint.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from config import settings
from db.connection import get_driver
from services import heartbeat

log = logging.getLogger(__name__)

_STARTED = time.time()
_BACKEND_DIR = Path(__file__).resolve().parent.parent
OVERALL_TIMEOUT_S = 8.0
PROBE_TIMEOUT_S = 5.0
MAIN_LABELS = ("Paper", "Person", "Topic", "Tag", "Project", "Note", "Annotation", "Claim", "User")
PROVIDERS = ("anthropic", "anthropic-work", "openai", "litellm", "claude-code")

CheckResult = tuple[str, str, dict]  # status, summary, details


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def _age_s(iso: str | None) -> float | None:
    """Seconds since an ISO timestamp, None when it cannot be read."""
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (_now() - then).total_seconds())


def _ago(iso: str | None) -> str:
    """"5 min ago" for an ISO timestamp, "" when it cannot be read."""
    s = _age_s(iso)
    if s is None:
        return ""
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{round(s / 60)} min ago"
    if s < 172800:
        return f"{round(s / 3600)} h ago"
    return f"{round(s / 86400)} days ago"


def _mb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


# ── cache ─────────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def clear_cache() -> None:
    """Forget every cached result (tests)."""
    with _lock:
        _cache.clear()


def _cached(key: str, ttl: float) -> Any | None:
    if ttl <= 0:
        return None
    with _lock:
        hit = _cache.get(key)
    return hit[1] if hit and time.monotonic() - hit[0] < ttl else None


def _store(key: str, value: Any) -> None:
    with _lock:
        _cache[key] = (time.monotonic(), value)


# ── checks ────────────────────────────────────────────────────────────────────

def check_backend() -> CheckResult:
    uptime = int(time.time() - _STARTED)
    details = {
        "uptime_s": uptime,
        "python": platform.python_version(),
        "pid": os.getpid(),
        "threads": threading.active_count(),
        "threadpool_size": settings.server_threadpool_size,
    }
    return "ok", f"up {_duration(uptime)}, Python {details['python']}, {details['threads']} threads", details


def _duration(seconds: float) -> str:
    s = int(seconds)
    if s < 120:
        return f"{s} s"
    if s < 7200:
        return f"{s // 60} min"
    if s < 172800:
        return f"{s // 3600} h"
    return f"{s // 86400} days"


def _neo4j_counts(driver) -> dict:
    """Node and relationship counts: ``apoc.meta.stats``, else ``count()`` per main label."""
    try:
        with driver.session() as session:
            rec = session.run(
                "CALL apoc.meta.stats() YIELD labels, relTypesCount, nodeCount, relCount "
                "RETURN labels, relTypesCount, nodeCount, relCount"
            ).single()
        if rec:
            return {
                "source": "apoc",
                "nodes": rec["nodeCount"],
                "relationships": rec["relCount"],
                "labels": dict(rec["labels"] or {}),
                "relationship_types": dict(rec["relTypesCount"] or {}),
            }
    except Exception as exc:  # noqa: BLE001 — no APOC: count the main labels
        log.debug("apoc.meta.stats unavailable: %s", exc)
    labels: dict[str, int] = {}
    with driver.session() as session:
        for label in MAIN_LABELS:
            labels[label] = session.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
        rels = session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
    return {"source": "count", "nodes": sum(labels.values()), "relationships": rels,
            "labels": labels, "relationship_types": {}}


def check_neo4j() -> CheckResult:
    driver = get_driver()
    t0 = time.perf_counter()
    driver.verify_connectivity()
    latency = round((time.perf_counter() - t0) * 1000)
    details = {"latency_ms": latency}
    try:
        details.update(_neo4j_counts(driver))
    except Exception as exc:  # noqa: BLE001 — connected, counts failed
        return "warn", f"connected ({latency} ms), counts failed: {exc}", details
    papers = (details.get("labels") or {}).get("Paper")
    return "ok", (
        f"connected in {latency} ms, {details['nodes']:,} nodes, {details['relationships']:,} relationships"
        + (f", {papers:,} papers" if papers is not None else "")
    ), details


def _ssl_verify() -> bool | str:
    return (settings.ssl_ca_bundle or True) if settings.ssl_verify else False


def _probe_anthropic(api_key: str, base_url: str | None = None) -> int | None:
    """List one model (no tokens spent); raises when the API cannot be reached."""
    import anthropic

    kwargs: dict[str, Any] = {
        "api_key": api_key, "timeout": PROBE_TIMEOUT_S, "max_retries": 0,
        "http_client": anthropic.DefaultHttpxClient(verify=_ssl_verify()),
    }
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)
    try:
        client.models.list(limit=1)
    finally:
        client.close()
    return None


def _probe_openai(api_key: str, base_url: str | None = None) -> int | None:
    """List the models of an OpenAI-compatible API; returns how many."""
    import httpx
    import openai

    http = httpx.Client(verify=_ssl_verify(), timeout=PROBE_TIMEOUT_S)
    client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=PROBE_TIMEOUT_S,
                           max_retries=0, http_client=http)
    try:
        return len(client.models.list().data)
    finally:
        client.close()


def _litellm_base_url() -> str:
    endpoint = settings.litellm_endpoint.strip().rstrip("/")
    return endpoint if endpoint.endswith("/v1") else f"{endpoint}/v1"


def _fast_info() -> tuple[str | None, str]:
    try:
        from services.litellm_client import fast_model, fast_provider

        return fast_provider(), fast_model()
    except Exception:  # noqa: BLE001
        return None, ""


def check_llm(provider: str) -> CheckResult:
    fast, model = _fast_info()
    details: dict[str, Any] = {"provider": provider, "fast_tasks": provider == fast}
    if provider == fast:
        details["fast_model"] = model
    tail = f" · runs the fast tasks ({model})" if provider == fast else ""

    if provider == "claude-code":
        return _check_claude_code(details, tail)

    if provider == "anthropic":
        key, base, hint = settings.anthropic_api_key.strip(), None, "ANTHROPIC_API_KEY"
        probe = lambda: _probe_anthropic(key)  # noqa: E731
    elif provider == "anthropic-work":
        key, base = settings.anthropic_work_api_key.strip(), settings.anthropic_work_base_url.strip() or None
        hint = "ANTHROPIC_WORK_API_KEY"
        probe = lambda: _probe_anthropic(key, base)  # noqa: E731
    elif provider == "openai":
        key, base, hint = settings.openai_api_key.strip(), None, "OPENAI_API_KEY"
        probe = lambda: _probe_openai(key)  # noqa: E731
    else:  # litellm
        key = settings.litellm_api_key.strip()
        base = _litellm_base_url() if settings.litellm_endpoint.strip() else None
        hint = "LITELLM_ENDPOINT and LITELLM_API_KEY"
        probe = lambda: _probe_openai(key, base)  # noqa: E731

    configured = bool(key and (provider != "litellm" or base))
    details["configured"] = configured
    if base:
        details["base_url"] = base
    if not configured:
        if provider == fast:
            return "error", f"chosen for the fast tasks but not configured ({hint})", details
        return "off", f"not configured ({hint})", details

    t0 = time.perf_counter()
    try:
        models = probe()
    except Exception as exc:  # noqa: BLE001 — any SDK or network error: not reachable
        details.update(reachable=False, error=f"{type(exc).__name__}: {exc}"[:300])
        # A gateway need not implement models.list, so the work gateway only warns.
        status = "warn" if provider == "anthropic-work" and provider != fast else "error"
        return status, f"configured, not reachable: {type(exc).__name__}{tail}", details
    latency = round((time.perf_counter() - t0) * 1000)
    details.update(reachable=True, probe_ms=latency, models=models)
    count = f", {models} models" if models is not None else ""
    return "ok", f"configured, reachable in {latency} ms{count}{tail}", details


def _check_claude_code(details: dict, tail: str) -> CheckResult:
    users = [u for u in settings.claude_code_users.split(",") if u.strip()]
    details.update(configured=bool(users), users=len(users))
    if not users:
        return "off", "not configured (CLAUDE_CODE_USERS)", details
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        details["sdk"] = False
        return "error", "claude-agent-sdk is not installed", details
    from services.claude_code_chat import _has_credentials

    details["sdk"] = True
    details["credentials"] = _has_credentials()
    if not details["credentials"]:
        return "error", f"enabled for {len(users)} user(s), but no credentials (CLAUDE_CODE_OAUTH_TOKEN)", details
    return "ok", f"enabled for {len(users)} user(s), credentials present (not probed){tail}", details


def _dir_size(path: Path, limit: int = 20000) -> tuple[int, int, bool]:
    """(bytes, files, capped) of the files below *path*, looking at no more than *limit* files."""
    total = files = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                continue
            files += 1
            if files >= limit:
                return total, files, True
    return total, files, False


def _drive_probe() -> dict:
    """Credentials present and one cheap Drive call; never starts the OAuth browser flow."""
    from services import drive

    token_file = drive._get_token_file()
    if not token_file.exists() and not settings.google_token_json.strip():
        raise RuntimeError("no Drive token (token.json missing; run the OAuth flow once)")
    import google_auth_httplib2
    import httplib2
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), drive._SCOPES)
    else:
        import json

        creds = Credentials.from_authorized_user_info(json.loads(settings.google_token_json), drive._SCOPES)
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=PROBE_TIMEOUT_S))
    service = build("drive", "v3", http=http, cache_discovery=False)
    about = service.about().get(fields="user(emailAddress)").execute()
    return {"account": (about.get("user") or {}).get("emailAddress")}


def check_storage() -> CheckResult:
    from services.drive import uses_local_storage

    if uses_local_storage():
        path = Path(settings.local_storage_dir)
        details: dict[str, Any] = {"backend": "local", "path": str(path)}
        if not path.exists():
            probe = path.parent
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            details.update(exists=False, writable=os.access(probe, os.W_OK))
            status = "ok" if details["writable"] else "error"
            return status, f"local files: {path} does not exist yet" + (
                "" if details["writable"] else " and cannot be created"), details
        size, files, capped = _dir_size(path)
        writable = os.access(path, os.W_OK)
        details.update(exists=True, writable=writable, files=files, bytes=size, size_capped=capped)
        if not writable:
            return "error", f"local files: {path} is not writable", details
        return "ok", f"local files in {path}: {'over ' if capped else ''}{files:,} files, {_mb(size)}", details

    details = {"backend": "drive", "folder_configured": bool(settings.google_drive_folder_id.strip())}
    try:
        details.update(_drive_probe(), credentials=True, reachable=True)
    except Exception as exc:  # noqa: BLE001
        details.update(reachable=False, error=f"{type(exc).__name__}: {exc}"[:300])
        return "error", f"Google Drive not usable: {exc}"[:200], details
    return "ok", f"Google Drive reachable ({details.get('account') or 'account unknown'})", details


def _first_existing(path: Path) -> Path | None:
    while not path.exists():
        if path == path.parent:
            return None
        path = path.parent
    return path


def check_disk() -> CheckResult:
    from services.drive import uses_local_storage

    candidates = [("backend data", _BACKEND_DIR / "data"), ("logs", _BACKEND_DIR.parent / "logs")]
    if uses_local_storage():
        candidates.insert(0, ("local files", Path(settings.local_storage_dir)))
    rows = []
    for label, path in candidates:
        real = _first_existing(path)
        if real is None:
            continue
        try:
            usage = shutil.disk_usage(real)
        except OSError:
            continue
        row = {"label": label, "path": str(path), "total": usage.total, "used": usage.used,
               "free": usage.free, "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0}
        rows.append(row)
    if not rows:
        return "off", "no directory to measure", {"volumes": []}
    worst = max(r["percent"] for r in rows)
    status = "error" if worst >= 95 else "warn" if worst >= 85 else "ok"
    summary = ", ".join(f"{r['label']} {r['percent']:.0f} % ({_mb(r['free'])} free)" for r in rows)
    return status, summary, {"volumes": rows, "worst_percent": worst}


def _cache_counts(module: Any) -> dict:
    """Job states of a disk-backed ingest cache (status.json per entry, TTL applied)."""
    counts: dict[str, int] = {"pending": 0, "running": 0, "ready": 0, "error": 0, "stale_running": 0}
    root: Path = module._CACHE_ROOT
    if not root.is_dir():
        return counts
    for i, entry in enumerate(root.iterdir()):
        if i >= 2000:
            break
        st = module._read_status(entry.name)
        if not st:
            continue
        state = st.get("status")
        if state in counts:
            counts[state] += 1
        if state == "running" and time.time() - float(st.get("updated_at") or st.get("created_at") or 0) > 1800:
            counts["stale_running"] += 1
    return counts


def check_ingest() -> CheckResult:
    from services import ingest_analysis_cache, ingest_preprocess_cache, reference_import

    pre = _cache_counts(ingest_preprocess_cache)
    ana = _cache_counts(ingest_analysis_cache)
    with reference_import._lock:
        states = [j.get("status") for j in reference_import._jobs.values()]
    refs = {s: states.count(s) for s in ("queued", "running", "done", "error")}
    last = None
    try:
        with get_driver().session() as session:
            last = session.run("MATCH (p:Paper) RETURN max(p.created_at) AS t").single()["t"]
    except Exception as exc:  # noqa: BLE001
        log.debug("last ingest unreadable: %s", exc)
    last = str(last) if last else None
    details = {"preprocess": pre, "analysis": ana, "reference_import": refs, "last_ingest": last}
    failed = pre["error"] + ana["error"] + refs["error"]
    stale = pre["stale_running"] + ana["stale_running"]
    summary = (
        f"pre-processing {pre['pending']} pending / {pre['running']} running / {pre['error']} failed, "
        f"pre-analysis {ana['pending']} / {ana['running']} / {ana['error']}, "
        f"reference imports {refs['queued'] + refs['running']} open / {refs['error']} failed"
        + (f", last paper added {_ago(last)}" if last and _ago(last) else "")
    )
    status = "warn" if failed or stale else "ok"
    if stale:
        summary += f" ({stale} running job(s) have not moved for 30 min)"
    return status, summary, details


def check_jobs() -> CheckResult:
    from routers import concept_map, paper_tour

    with concept_map._jobs_lock:
        builds = [j for j in concept_map._jobs.values() if j.get("running")]
    builds_running = len(builds)
    with paper_tour._lock:
        tours_running, tour_errors = len(paper_tour._running), len(paper_tour._errors)
    since = (_now() - timedelta(hours=24)).isoformat()
    with get_driver().session() as session:
        failed_mapping = session.run(
            "MATCH (p:Paper) WHERE p.concept_map_error IS NOT NULL AND coalesce(p.concept_map_attempts, 1) >= 3 "
            "RETURN count(p) AS n"
        ).single()["n"]
        reports = session.run(
            "MATCH (r:Report) RETURN "
            "sum(CASE WHEN r.status = 'running' THEN 1 ELSE 0 END) AS running, "
            "sum(CASE WHEN r.status = 'failed' AND r.updated_at >= $since THEN 1 ELSE 0 END) AS failed",
            since=since,
        ).single()
    reports_running = int(reports["running"] or 0) if reports else 0
    reports_failed = int(reports["failed"] or 0) if reports else 0
    details = {
        "concept_map_builds_running": builds_running,
        "concept_map_failed_3x": failed_mapping,
        "reports_running": reports_running,
        "reports_failed_24h": reports_failed,
        "tours_running": tours_running,
        "tours_with_error": tour_errors,
    }
    summary = (
        f"{builds_running} concept-map build(s) running, {failed_mapping} paper(s) failed mapping 3x, "
        f"reports {reports_running} running / {reports_failed} failed in 24 h, "
        f"tours {tours_running} running / {tour_errors} with error"
    )
    return ("warn" if failed_mapping or reports_failed or tour_errors else "ok"), summary, details


def _sweeper_entries() -> list[dict]:
    """The background loops: alive (by thread name), last beat, last error."""
    alive = {t.name for t in threading.enumerate() if t.is_alive()}
    beats = heartbeat.snapshot()
    out: list[dict] = []

    b = beats.get("concept-map-sweeper", {})
    out.append({
        "name": "concept-map-sweeper", "alive": "concept-map-sweeper" in alive,
        "enabled": bool(settings.concept_map_auto), "last_run": b.get("last_run"),
        "last_ok": b.get("last_ok"), "last_error": b.get("last_error"),
        "interval_s": b.get("interval_s") or 600,
    })

    entry: dict[str, Any] = {
        "name": "library-embeddings", "alive": "library-embeddings" in alive, "enabled": True,
        "last_run": None, "last_ok": None, "last_error": None,
        "interval_s": float(os.environ.get("LIBRARY_SEMANTIC_INTERVAL", "600")),
    }
    try:
        from services.library_search import semantic

        st = semantic.status()
        state = st.get("state")
        entry.update(enabled=bool(st.get("enabled")), last_run=st.get("last_sync"),
                     last_ok=(state != "error") if (st.get("last_sync") or state == "error") else None,
                     last_error=st.get("error"), state=state, indexed=st.get("indexed"))
    except Exception as exc:  # noqa: BLE001
        entry["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
    out.append(entry)

    conf: dict[str, Any] = {
        "name": "conference-builder", "alive": "conference-builder" in alive,
        # The worker starts with the first queued build and then stays: idle is normal.
        "enabled": os.environ.get("CONFERENCES_AUTO", "true").strip().lower() not in ("0", "false", "no", "off"),
        "last_run": None, "last_ok": None, "last_error": None, "interval_s": None,
    }
    try:
        from services.conferences import store

        states = {k: store.status(k) for k in store.default_keys()}
        latest = max((s.get("updated_at") for s in states.values() if s.get("updated_at")), default=None)
        errors = [f"{k}: {s.get('message')}" for k, s in states.items() if s.get("state") == "error"]
        conf.update(last_run=latest, last_ok=not errors if states else None,
                    last_error="; ".join(errors)[:300] or None,
                    states={k: s.get("state") for k, s in states.items()})
    except Exception as exc:  # noqa: BLE001
        conf["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
    out.append(conf)
    return out


def check_sweepers() -> CheckResult:
    entries = _sweeper_entries()
    problems: list[str] = []
    status = "ok"
    for e in entries:
        if not e["enabled"]:
            continue
        if e["name"] == "conference-builder":
            if e["last_ok"] is False:
                problems.append(f"{e['name']}: {e['last_error']}")
            continue
        if not e["alive"]:
            if e["name"] == "concept-map-sweeper":  # library search merely falls back to words
                status = "error"
            problems.append(f"{e['name']} is not running")
        elif e["last_ok"] is False:
            problems.append(f"{e['name']}: {e['last_error']}")
        else:
            age = _age_s(e["last_run"]) if e["interval_s"] else None
            if age is not None and age > 3 * e["interval_s"] + 300:
                problems.append(f"{e['name']} has not run for {_duration(age)}")
    if problems and status == "ok":
        status = "warn"
    live = [e["name"] for e in entries if e["alive"]]
    summary = "; ".join(problems) if problems else (
        f"running: {', '.join(live)}" if live else "no background threads started (idle or switched off)")
    return status, summary, {"sweepers": entries}


def check_tokens() -> CheckResult:
    if not settings.usage_ledger_enabled:
        return "off", "token ledger switched off (USAGE_LEDGER_ENABLED)", {}
    try:
        from services.usage import ledger

        today = _now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        totals = ledger.totals_since(today, None)
    except Exception as exc:  # noqa: BLE001 — the ledger is optional for the health page
        log.debug("token ledger unavailable: %s", exc)
        return "off", "token ledger unavailable", {}
    today_totals = {
        "calls": int(totals.get("calls") or 0), "errors": int(totals.get("errors") or 0),
        "input_tokens": int(totals.get("input_tokens") or 0),
        "output_tokens": int(totals.get("output_tokens") or 0),
        "cost_usd": round(float(totals.get("cost_usd") or 0.0), 4),
    }
    calls, errors = today_totals["calls"], today_totals["errors"]
    summary = f"today {calls} calls, {errors} errors, ${today_totals['cost_usd']:.2f}"
    status = "warn" if errors >= 5 and errors / max(calls, 1) >= 0.25 else "ok"
    return status, summary, {"today": today_totals}


# ── log tail, audit, version ──────────────────────────────────────────────────

_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})  (\w+)\s+(\S+)  (.*)$")


def read_recent_errors(path: Path | str | None = None, limit: int = 30, tail_bytes: int = 512 * 1024) -> list[dict]:
    """The last *limit* ERROR / CRITICAL records of the log file, newest first.

    Reads only the file's last *tail_bytes*. A record's traceback is folded into its message:
    the last unindented continuation line (the exception) is appended.
    """
    if path is None:
        import logger

        path = logger._LOG_FILE
    path = Path(path)
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    records: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = _LOG_LINE.match(line)
        if m:
            current = {"ts": m.group(1), "level": m.group(2), "logger": m.group(3),
                       "message": m.group(4), "_tail": None}
            records.append(current)
        elif current is not None and line.strip() and not line[0].isspace() and not line.startswith("Traceback"):
            current["_tail"] = line.strip()
    out = []
    for r in reversed(records):
        if r["level"] not in ("ERROR", "CRITICAL"):
            continue
        message = r["message"] + (f" | {r['_tail']}" if r["_tail"] else "")
        out.append({"ts": r["ts"], "logger": r["logger"], "level": r["level"], "message": message[:400]})
        if len(out) >= limit:
            break
    return out


def recent_audit() -> dict:
    """Actions of the last 24 hours and the latest ones."""
    from db.queries.audit_log import get_audit_logs

    driver = get_driver()
    since = (_now() - timedelta(hours=24)).isoformat()
    with driver.session() as session:
        n = session.run("MATCH (l:AuditLog) WHERE l.timestamp >= $since RETURN count(l) AS n", since=since).single()["n"]
    last = [
        {"ts": r.get("timestamp"), "username": r.get("username"),
         "action_type": r.get("action_type"), "entity_type": r.get("entity_type")}
        for r in get_audit_logs(driver, limit=10)
    ]
    return {"actions_24h": n, "last": last}


def _read_git(git: Path) -> tuple[str | None, str | None]:
    """(sha, branch) from a ``.git`` directory (or worktree file), no git binary needed."""
    if git.is_file():
        text = git.read_text().strip()
        if not text.startswith("gitdir:"):
            return None, None
        git = (git.parent / text.split(":", 1)[1].strip()).resolve()
    head = (git / "HEAD").read_text().strip()
    if not head.startswith("ref:"):
        return head or None, None
    ref = head.split(":", 1)[1].strip()
    branch = ref.removeprefix("refs/heads/")
    ref_file = git / ref
    if ref_file.is_file():
        return ref_file.read_text().strip() or None, branch
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0], branch
    return None, branch


def git_info(repo_root: Path | None = None) -> tuple[str | None, str | None]:
    """(short sha, branch): GIT_SHA from the environment, else the mounted repository, else None."""
    sha, branch = None, None
    try:
        git = (repo_root or _BACKEND_DIR.parent) / ".git"
        if git.exists():
            sha, branch = _read_git(git)
    except Exception as exc:  # noqa: BLE001
        log.debug("cannot read .git: %s", exc)
    configured = settings.git_sha.strip()
    if configured:
        sha = configured
    if sha and re.fullmatch(r"[0-9a-f]{8,40}", sha):
        sha = sha[:7]
    return sha, branch


def version_info() -> dict:
    sha, branch = git_info()
    return {
        "app": settings.app_version.strip() or "dev",
        "git_sha": sha,
        "git_branch": branch,
        "python": platform.python_version(),
        "started_at": _iso(_STARTED),
        "uptime_s": int(time.time() - _STARTED),
    }


# ── collection ────────────────────────────────────────────────────────────────

def _checks() -> list[tuple[str, str, float, Callable[[], CheckResult]]]:
    """(id, label, cache TTL in seconds, function) in page order."""
    llm = [(f"llm:{p}", f"LLM: {p}", 300.0, (lambda p=p: check_llm(p))) for p in PROVIDERS]
    return [
        ("backend", "Backend", 0, check_backend),
        ("neo4j", "Neo4j", 60, check_neo4j),
        *llm,
        ("storage", "File storage", 600, check_storage),
        ("disk", "Disk", 60, check_disk),
        ("ingest", "Ingest", 10, check_ingest),
        ("jobs", "Jobs", 30, check_jobs),
        ("sweepers", "Background threads", 0, check_sweepers),
        ("tokens", "Token ledger", 30, check_tokens),
    ]


def run_check(check_id: str, label: str, fn: Callable[[], CheckResult]) -> dict:
    """Run one check; an exception becomes status ``error``. Never raises."""
    t0 = time.perf_counter()
    try:
        status, summary, details = fn()
    except Exception as exc:  # noqa: BLE001 — one broken check must not fail the endpoint
        log.warning("Health check %s failed: %s", check_id, exc)
        status, summary, details = "error", f"{type(exc).__name__}: {exc}"[:300], {}
    return {
        "id": check_id, "label": label, "status": status, "summary": summary, "details": details,
        "checked_at": _now().isoformat(), "latency_ms": round((time.perf_counter() - t0) * 1000),
    }


def _timed_out(check_id: str, label: str) -> dict:
    return {"id": check_id, "label": label, "status": "warn", "summary": f"timed out after {OVERALL_TIMEOUT_S:.0f} s",
            "details": {}, "checked_at": _now().isoformat(), "latency_ms": round(OVERALL_TIMEOUT_S * 1000)}


def overall_status(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    return "error" if "error" in statuses else "degraded" if "warn" in statuses else "ok"


def collect(refresh: bool = False) -> dict:
    """The whole health response. ``refresh`` bypasses every cache."""
    specs = _checks()
    results: dict[str, Any] = {}
    jobs: list[tuple[str, str, float, Callable[[], Any]]] = []

    def check_job(cid: str, label: str, ttl: float, fn: Callable[[], CheckResult]):
        def run() -> dict:
            res = run_check(cid, label, fn)
            _store(cid, res)  # a late finisher still fills the cache for the next call
            return res
        return cid, label, ttl, run

    for cid, label, ttl, fn in specs:
        hit = None if refresh else _cached(cid, ttl)
        if hit is not None:
            results[cid] = hit
        else:
            jobs.append(check_job(cid, label, ttl, fn))

    def part(key: str, ttl: float, fn: Callable[[], Any], default: Any):
        def run() -> Any:
            try:
                value = fn()
            except Exception as exc:  # noqa: BLE001
                log.warning("Health part %s failed: %s", key, exc)
                return default(exc) if callable(default) else default
            _store(key, value)
            return value
        return key, key, ttl, run

    extra = [
        ("recent_errors", 10, read_recent_errors, []),
        ("audit", 30, recent_audit, lambda exc: {"actions_24h": 0, "last": [], "error": f"{type(exc).__name__}: {exc}"[:300]}),
    ]
    defaults: dict[str, Any] = {}
    for key, ttl, fn, default in extra:
        hit = None if refresh else _cached(key, ttl)
        defaults[key] = default(RuntimeError("timed out")) if callable(default) else default
        if hit is not None:
            results[key] = hit
        else:
            jobs.append(part(key, ttl, fn, default))

    if jobs:
        pool = ThreadPoolExecutor(max_workers=min(10, len(jobs)), thread_name_prefix="health")
        futures = {pool.submit(run): (key, label) for key, label, _ttl, run in jobs}
        done, _pending = wait(futures, timeout=OVERALL_TIMEOUT_S)
        pool.shutdown(wait=False, cancel_futures=True)
        for fut, (key, label) in futures.items():
            if fut in done and not fut.exception():
                results[key] = fut.result()
            elif key in defaults:
                results[key] = defaults[key]
            else:
                results[key] = _timed_out(key, label)

    checks = [results[cid] for cid, *_ in specs]
    by_id = {c["id"]: c for c in checks}
    tokens_today = (by_id.get("tokens", {}).get("details") or {}).get("today") or {
        "calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    sweepers = [
        {k: e.get(k) for k in ("name", "alive", "last_run", "last_ok", "last_error", "interval_s")}
        for e in ((by_id.get("sweepers", {}).get("details") or {}).get("sweepers") or [])
    ]
    return {
        "generated_at": _now().isoformat(),
        "status": overall_status(checks),
        "checks": checks,
        "version": version_info(),
        "tokens_today": tokens_today,
        "recent_errors": results["recent_errors"],
        "sweepers": sweepers,
        "audit": results["audit"],
    }
