"""System health (.specs/016_health.md): no Neo4j, no SDK calls, no network."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers import system_health as router_mod
from services import heartbeat, system_health as sh
from services.auth import get_current_user


@pytest.fixture(autouse=True)
def clean_state():
    sh.clear_cache()
    heartbeat.reset()
    yield
    sh.clear_cache()
    heartbeat.reset()


# ── fake Neo4j driver ─────────────────────────────────────────────────────────

class _Result:
    def __init__(self, row): self.row = row
    def single(self): return self.row


class FakeSession:
    def __init__(self, driver): self.driver = driver
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def run(self, query, **params):
        self.driver.queries.append(query)
        for needle, answer in self.driver.answers.items():
            if needle in query:
                if isinstance(answer, Exception):
                    raise answer
                return _Result(answer(params) if callable(answer) else answer)
        return _Result({"n": 0})


class FakeDriver:
    def __init__(self, answers=None, connect_error=None):
        self.answers, self.queries, self.connect_error = answers or {}, [], connect_error

    def session(self): return FakeSession(self)

    def verify_connectivity(self):
        if self.connect_error:
            raise self.connect_error


# ── Neo4j check ───────────────────────────────────────────────────────────────

def test_neo4j_counts_from_apoc(monkeypatch):
    driver = FakeDriver({"apoc.meta.stats": {"labels": {"Paper": 12, "Person": 40}, "relTypesCount": {"AUTHORED_BY": 50},
                                              "nodeCount": 52, "relCount": 50}})
    monkeypatch.setattr(sh, "get_driver", lambda: driver)
    status, summary, details = sh.check_neo4j()
    assert status == "ok"
    assert details["source"] == "apoc" and details["nodes"] == 52 and details["labels"]["Paper"] == 12
    assert "12 papers" in summary


def test_neo4j_counts_fall_back_to_count_per_label(monkeypatch):
    driver = FakeDriver({"apoc.meta.stats": RuntimeError("no apoc"), "(n:Paper)": {"n": 7}, "()-[r]->()": {"n": 30}})
    monkeypatch.setattr(sh, "get_driver", lambda: driver)
    status, _summary, details = sh.check_neo4j()
    assert status == "ok" and details["source"] == "count"
    assert details["labels"]["Paper"] == 7 and set(details["labels"]) == set(sh.MAIN_LABELS)
    assert details["relationships"] == 30


def test_neo4j_down_is_an_error_via_run_check(monkeypatch):
    monkeypatch.setattr(sh, "get_driver", lambda: FakeDriver(connect_error=ConnectionError("refused")))
    res = sh.run_check("neo4j", "Neo4j", sh.check_neo4j)
    assert res["status"] == "error" and "refused" in res["summary"]
    assert set(res) == {"id", "label", "status", "summary", "details", "checked_at", "latency_ms"}


# ── providers ─────────────────────────────────────────────────────────────────

@pytest.fixture
def no_keys(monkeypatch):
    for name in ("anthropic_api_key", "anthropic_work_api_key", "anthropic_work_base_url", "openai_api_key",
                 "litellm_endpoint", "litellm_api_key", "claude_code_users", "ai_provider", "fast_model"):
        monkeypatch.setattr(sh.settings, name, "auto" if name == "ai_provider" else "")


@pytest.mark.parametrize("provider", ["anthropic", "anthropic-work", "openai", "litellm", "claude-code"])
def test_provider_without_configuration_is_off(no_keys, monkeypatch, provider):
    monkeypatch.setattr(sh, "_probe_anthropic", lambda *a: pytest.fail("must not probe"))
    monkeypatch.setattr(sh, "_probe_openai", lambda *a: pytest.fail("must not probe"))
    status, summary, details = sh.check_llm(provider)
    assert status == "off" and "not configured" in summary
    assert details.get("configured") is False


def test_anthropic_reachable_and_runs_fast_tasks(no_keys, monkeypatch):
    monkeypatch.setattr(sh.settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(sh, "_probe_anthropic", lambda key, base=None: None)
    status, summary, details = sh.check_llm("anthropic")
    assert status == "ok" and details["fast_tasks"] is True and details["reachable"] is True
    assert "fast tasks" in summary and "sk-ant" not in str(details)


def test_litellm_probe_gets_the_v1_endpoint(no_keys, monkeypatch):
    seen = {}
    monkeypatch.setattr(sh.settings, "litellm_endpoint", "https://llm.example.org/")
    monkeypatch.setattr(sh.settings, "litellm_api_key", "k")
    monkeypatch.setattr(sh, "_probe_openai", lambda key, base=None: seen.update(key=key, base=base) or 14)
    status, summary, details = sh.check_llm("litellm")
    assert status == "ok" and details["models"] == 14 and "14 models" in summary
    assert seen == {"key": "k", "base": "https://llm.example.org/v1"}


def test_unreachable_provider_is_an_error_but_a_work_gateway_only_warns(no_keys, monkeypatch):
    def refuse(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(sh, "_probe_anthropic", refuse)
    monkeypatch.setattr(sh.settings, "openai_api_key", "k")
    monkeypatch.setattr(sh, "_probe_openai", refuse)
    monkeypatch.setattr(sh.settings, "anthropic_work_api_key", "k")
    monkeypatch.setattr(sh.settings, "anthropic_work_base_url", "https://gw.example.org")
    assert sh.check_llm("openai")[0] == "error"
    status, _summary, details = sh.check_llm("anthropic-work")
    assert status == "warn" and details["reachable"] is False and "TimeoutError" in details["error"]


def test_chosen_fast_provider_without_key_is_an_error(no_keys, monkeypatch):
    monkeypatch.setattr(sh.settings, "ai_provider", "openai")
    status, summary, _ = sh.check_llm("openai")
    assert status == "error" and "fast tasks" in summary


def test_claude_code_checks_credentials_without_starting_the_cli(no_keys, monkeypatch):
    monkeypatch.setattr(sh.settings, "claude_code_users", "alice")
    import services.claude_code_chat as cc

    monkeypatch.setattr(cc, "_has_credentials", lambda: True)
    status, summary, details = sh.check_llm("claude-code")
    if details.get("sdk") is False:  # claude_agent_sdk not installed in this environment
        assert status == "error"
    else:
        assert status == "ok" and "not probed" in summary
        monkeypatch.setattr(cc, "_has_credentials", lambda: False)
        assert sh.check_llm("claude-code")[0] == "error"


# ── other checks ──────────────────────────────────────────────────────────────

def test_backend_check():
    status, summary, details = sh.check_backend()
    assert status == "ok" and details["threadpool_size"] and details["python"] in summary


def test_disk_thresholds(monkeypatch, tmp_path):
    monkeypatch.setattr(sh, "_BACKEND_DIR", tmp_path / "backend")
    (tmp_path / "backend").mkdir()
    monkeypatch.setattr(sh.settings, "storage_backend", "local")
    monkeypatch.setattr(sh.settings, "local_storage_dir", str(tmp_path / "files"))

    def usage(percent):
        total = 1000
        return lambda path: type("U", (), {"total": total, "used": percent * 10, "free": total - percent * 10})()

    monkeypatch.setattr(sh.shutil, "disk_usage", usage(50))
    assert sh.check_disk()[0] == "ok"
    monkeypatch.setattr(sh.shutil, "disk_usage", usage(88))
    assert sh.check_disk()[0] == "warn"
    monkeypatch.setattr(sh.shutil, "disk_usage", usage(96))
    status, _summary, details = sh.check_disk()
    assert status == "error" and details["worst_percent"] == 96.0


def test_local_storage_counts_files(monkeypatch, tmp_path):
    (tmp_path / "local-aaa.pdf").write_bytes(b"x" * 1000)
    (tmp_path / "local-bbb.png").write_bytes(b"y" * 500)
    monkeypatch.setattr(sh.settings, "storage_backend", "local")
    monkeypatch.setattr(sh.settings, "local_storage_dir", str(tmp_path))
    status, summary, details = sh.check_storage()
    assert status == "ok" and details["backend"] == "local"
    assert details["files"] == 2 and details["bytes"] == 1500 and details["writable"] is True


def test_ingest_counts_cache_entries_and_reference_jobs(monkeypatch, tmp_path):
    import json

    from services import ingest_analysis_cache as ana, ingest_preprocess_cache as pre, reference_import

    monkeypatch.setattr(pre, "_CACHE_ROOT", tmp_path / "pre")
    monkeypatch.setattr(ana, "_CACHE_ROOT", tmp_path / "ana")
    now = time.time()
    for root, name, state, age in [("pre", "k1", "running", 0), ("pre", "k2", "error", 0), ("pre", "k3", "ready", 0),
                                   ("ana", "k1", "pending", 0), ("ana", "k2", "running", 4000)]:
        d = tmp_path / root / name
        d.mkdir(parents=True)
        (d / "status.json").write_text(json.dumps({"status": state, "created_at": now - age, "updated_at": now - age}))
    monkeypatch.setattr(reference_import, "_jobs", {"a": {"status": "queued"}, "b": {"status": "error"}})
    monkeypatch.setattr(sh, "get_driver", lambda: FakeDriver({"max(p.created_at)": {"t": "2026-11-12T08:00:00+00:00"}}))
    status, summary, details = sh.check_ingest()
    assert details["preprocess"] == {"pending": 0, "running": 1, "ready": 1, "error": 1, "stale_running": 0}
    assert details["analysis"]["pending"] == 1 and details["analysis"]["stale_running"] == 1
    assert details["reference_import"]["queued"] == 1 and details["reference_import"]["error"] == 1
    assert details["last_ingest"] == "2026-11-12T08:00:00+00:00"
    assert status == "warn" and "last paper added" in summary


def test_jobs_check_handles_missing_reports(monkeypatch):
    from routers import concept_map, paper_tour

    monkeypatch.setattr(concept_map, "_jobs", {"p1": {"running": True}, "p2": {"running": False}})
    monkeypatch.setattr(paper_tour, "_running", {"x"})
    monkeypatch.setattr(paper_tour, "_errors", {})
    driver = FakeDriver({"concept_map_error": {"n": 2}, ":Report": {"running": None, "failed": None}})
    monkeypatch.setattr(sh, "get_driver", lambda: driver)
    status, _summary, details = sh.check_jobs()
    assert details == {"concept_map_builds_running": 1, "concept_map_failed_3x": 2, "reports_running": 0,
                       "reports_failed_24h": 0, "tours_running": 1, "tours_with_error": 0}
    assert status == "warn"


def test_tokens_check_off_when_the_ledger_breaks(monkeypatch):
    import services.usage.ledger as ledger

    monkeypatch.setattr(sh.settings, "usage_ledger_enabled", True)
    monkeypatch.setattr(ledger, "totals_since", lambda *a: (_ for _ in ()).throw(RuntimeError("db locked")))
    status, summary, _ = sh.check_tokens()
    assert (status, summary) == ("off", "token ledger unavailable")


def test_tokens_check_reads_todays_totals(monkeypatch):
    import services.usage.ledger as ledger

    monkeypatch.setattr(sh.settings, "usage_ledger_enabled", True)
    monkeypatch.setattr(ledger, "totals_since", lambda since, user: {
        "calls": 12, "errors": 1, "input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.5})
    status, summary, details = sh.check_tokens()
    assert status == "ok" and details["today"]["calls"] == 12 and "12 calls" in summary


# ── heartbeat and sweepers ────────────────────────────────────────────────────

def test_heartbeat_snapshot():
    assert heartbeat.snapshot() == {}
    heartbeat.beat("concept-map-sweeper", ok=True, interval_s=600)
    heartbeat.beat("concept-map-sweeper", ok=False, error="boom")
    snap = heartbeat.snapshot()["concept-map-sweeper"]
    assert snap["last_ok"] is False and snap["last_error"] == "boom"
    assert snap["interval_s"] == 600 and snap["runs"] == 2 and snap["last_run"]
    snap["last_ok"] = "mutated"
    assert heartbeat.snapshot()["concept-map-sweeper"]["last_ok"] is False  # snapshot is a copy


def test_sweepers_combine_beats_with_thread_aliveness(monkeypatch):
    import threading

    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="concept-map-sweeper", daemon=True)
    t.start()
    try:
        monkeypatch.setattr(sh.settings, "concept_map_auto", True)
        heartbeat.beat("concept-map-sweeper", ok=True, interval_s=600)
        entries = {e["name"]: e for e in sh._sweeper_entries()}
        assert entries["concept-map-sweeper"]["alive"] is True and entries["concept-map-sweeper"]["last_ok"] is True
        assert set(entries) == {"concept-map-sweeper", "library-embeddings", "conference-builder"}
        status, _summary, _details = sh.check_sweepers()
        assert status in ("ok", "warn")  # the library thread is not running here: a warning at most
    finally:
        stop.set()
        t.join(1)


def test_dead_concept_map_sweeper_is_an_error(monkeypatch):
    monkeypatch.setattr(sh.settings, "concept_map_auto", True)
    status, summary, _ = sh.check_sweepers()
    assert status == "error" and "concept-map-sweeper is not running" in summary


def test_switched_off_sweeper_is_not_an_error(monkeypatch):
    monkeypatch.setattr(sh.settings, "concept_map_auto", False)
    status, summary, _ = sh.check_sweepers()
    assert status != "error" and "concept-map-sweeper" not in summary


# ── log tail ──────────────────────────────────────────────────────────────────

LOG = """\
tail of a record cut by the 512 KB window
2026-11-12 09:00:00  INFO      main  started
2026-11-12 09:10:00  ERROR     services.ai  Summary failed for paper 1
Traceback (most recent call last):
  File "x.py", line 3, in f
    raise ValueError("bad")
ValueError: bad
2026-11-12 09:20:00  WARNING   routers.papers  slow upload
2026-11-12 09:30:00  CRITICAL  db.connection  Neo4j gone
2026-11-12 09:40:00  ERROR     services.drive  Upload failed
"""


def test_read_recent_errors_parses_newest_first(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text(LOG)
    out = sh.read_recent_errors(log_file)
    assert [r["ts"] for r in out] == ["2026-11-12 09:40:00", "2026-11-12 09:30:00", "2026-11-12 09:10:00"]
    assert out[0] == {"ts": "2026-11-12 09:40:00", "logger": "services.drive", "level": "ERROR", "message": "Upload failed"}
    assert out[1]["level"] == "CRITICAL"
    assert out[2]["message"] == "Summary failed for paper 1 | ValueError: bad"


def test_read_recent_errors_limit_tail_and_missing_file(tmp_path):
    log_file = tmp_path / "app.log"
    lines = [f"2026-11-12 09:{i // 60:02d}:{i % 60:02d}  ERROR     m  error {i}\n" for i in range(100)]
    log_file.write_text("".join(lines))
    assert len(sh.read_recent_errors(log_file, limit=30)) == 30
    assert sh.read_recent_errors(log_file, limit=30)[0]["message"] == "error 99"
    tail = sh.read_recent_errors(log_file, limit=500, tail_bytes=len(lines[0]) * 10 + 5)
    assert 9 <= len(tail) <= 11 and tail[0]["message"] == "error 99"
    assert sh.read_recent_errors(tmp_path / "missing.log") == []


# ── version ───────────────────────────────────────────────────────────────────

def test_git_info_reads_head_ref_and_packed_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(sh.settings, "git_sha", "")
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text("92affd2aa1bb2cc3dd4ee5ff6677889900aabbcc\n")
    assert sh.git_info(tmp_path) == ("92affd2", "main")
    (git / "refs" / "heads" / "main").unlink()
    (git / "packed-refs").write_text("# pack-refs\n1234567890abcdef1234567890abcdef12345678 refs/heads/main\n")
    assert sh.git_info(tmp_path) == ("1234567", "main")
    (git / "HEAD").write_text("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n")
    assert sh.git_info(tmp_path) == ("deadbee", None)


def test_git_info_env_wins_and_missing_repository_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sh.settings, "git_sha", "")
    assert sh.git_info(tmp_path) == (None, None)
    monkeypatch.setattr(sh.settings, "git_sha", "abc1234def5678")
    assert sh.git_info(tmp_path)[0] == "abc1234"
    monkeypatch.setattr(sh.settings, "git_sha", "v1.2.3")
    assert sh.git_info(tmp_path)[0] == "v1.2.3"


def test_version_info(monkeypatch):
    monkeypatch.setattr(sh.settings, "app_version", "")
    v = sh.version_info()
    assert v["app"] == "dev" and set(v) == {"app", "git_sha", "git_branch", "python", "started_at", "uptime_s"}


# ── collect: caching, failures, timeout ───────────────────────────────────────

@pytest.fixture
def cheap(monkeypatch):
    """Replace the checks with counters; the audit and log readers with constants."""
    calls: dict[str, int] = {}

    def make(cid, status="ok"):
        def fn():
            calls[cid] = calls.get(cid, 0) + 1
            return status, f"{cid} {status}", {}
        return fn

    monkeypatch.setattr(sh, "_checks", lambda: [
        ("backend", "Backend", 0, make("backend")),
        ("neo4j", "Neo4j", 60, make("neo4j")),
        ("tokens", "Token ledger", 30, lambda: ("ok", "today", {"today": {"calls": 3, "errors": 0, "input_tokens": 1,
                                                                          "output_tokens": 2, "cost_usd": 0.1}})),
        ("sweepers", "Background threads", 0, lambda: ("ok", "x", {"sweepers": [
            {"name": "concept-map-sweeper", "alive": True, "last_run": None, "last_ok": None,
             "last_error": None, "interval_s": 600, "enabled": True}]})),
    ])
    monkeypatch.setattr(sh, "read_recent_errors", lambda *a, **k: [{"ts": "t", "logger": "l", "level": "ERROR", "message": "m"}])
    monkeypatch.setattr(sh, "recent_audit", lambda: {"actions_24h": 4, "last": []})
    return calls, make


def test_collect_shape(cheap):
    body = sh.collect()
    assert set(body) == {"generated_at", "status", "checks", "version", "tokens_today", "recent_errors", "sweepers", "audit"}
    assert body["status"] == "ok"
    assert [c["id"] for c in body["checks"]] == ["backend", "neo4j", "tokens", "sweepers"]
    assert body["tokens_today"]["calls"] == 3
    assert body["sweepers"] == [{"name": "concept-map-sweeper", "alive": True, "last_run": None, "last_ok": None,
                                 "last_error": None, "interval_s": 600}]
    assert body["audit"]["actions_24h"] == 4 and body["recent_errors"][0]["message"] == "m"


def test_second_call_is_served_from_the_cache_and_refresh_bypasses(cheap):
    calls, _ = cheap
    sh.collect()
    sh.collect()
    assert calls["neo4j"] == 1            # TTL 60 s
    assert calls["backend"] == 2          # TTL 0: always fresh
    sh.collect(refresh=True)
    assert calls["neo4j"] == 2


def test_a_broken_check_does_not_fail_the_collection(cheap, monkeypatch):
    def broken():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(sh, "_checks", lambda: [("backend", "Backend", 0, lambda: ("ok", "up", {})),
                                                ("neo4j", "Neo4j", 60, broken)])
    body = sh.collect()
    by_id = {c["id"]: c for c in body["checks"]}
    assert by_id["neo4j"]["status"] == "error" and "kaboom" in by_id["neo4j"]["summary"]
    assert by_id["backend"]["status"] == "ok"
    assert body["status"] == "error"


def test_broken_audit_and_log_parts_degrade_to_empty(cheap, monkeypatch):
    monkeypatch.setattr(sh, "recent_audit", lambda: (_ for _ in ()).throw(RuntimeError("no neo4j")))
    monkeypatch.setattr(sh, "read_recent_errors", lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    body = sh.collect()
    assert body["recent_errors"] == []
    assert body["audit"]["actions_24h"] == 0 and "no neo4j" in body["audit"]["error"]


def test_overall_status_levels():
    assert sh.overall_status([{"status": "ok"}, {"status": "off"}]) == "ok"
    assert sh.overall_status([{"status": "ok"}, {"status": "warn"}]) == "degraded"
    assert sh.overall_status([{"status": "warn"}, {"status": "error"}]) == "error"


def test_a_slow_check_times_out_as_warn(cheap, monkeypatch):
    monkeypatch.setattr(sh, "OVERALL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(sh, "_checks", lambda: [("backend", "Backend", 0, lambda: ("ok", "up", {})),
                                                ("neo4j", "Neo4j", 60, lambda: (time.sleep(0.8), ("ok", "late", {}))[1])])
    t0 = time.perf_counter()
    body = sh.collect()
    assert time.perf_counter() - t0 < 0.7
    by_id = {c["id"]: c for c in body["checks"]}
    assert by_id["neo4j"]["status"] == "warn" and "timed out" in by_id["neo4j"]["summary"]
    assert by_id["backend"]["status"] == "ok" and body["status"] == "degraded"
    time.sleep(0.9)                                     # the late finisher filled the cache
    assert sh.collect()["checks"][1]["summary"] == "late"


# ── endpoint ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch, cheap):
    app = FastAPI()
    app.include_router(router_mod.router)
    app.state.user = "alice"
    app.state.admins = set()
    app.dependency_overrides[get_current_user] = lambda: app.state.user
    monkeypatch.setattr(router_mod, "_is_admin", lambda u: u in app.state.admins)
    return app


async def test_health_endpoint_is_admin_only(api):
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as c:
        assert (await c.get("/system/health")).status_code == 403
        api.state.admins.add("alice")
        r = await c.get("/system/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok" and len(r.json()["checks"]) == 4


async def test_health_endpoint_refresh_flag(api, cheap):
    calls, _ = cheap
    api.state.admins.add("alice")
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as c:
        await c.get("/system/health")
        await c.get("/system/health")
        assert calls["neo4j"] == 1
        await c.get("/system/health?refresh=true")
        assert calls["neo4j"] == 2


async def test_health_endpoint_needs_a_session():
    app = FastAPI()
    app.include_router(router_mod.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/system/health")).status_code == 401


def test_admin_check_failure_counts_as_not_admin(monkeypatch):
    monkeypatch.setattr(router_mod, "get_driver", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    assert router_mod._is_admin("alice") is False
