# System health — developer context

One admin page (`/health`) with the state of the instance: is everything up, configured and
keeping pace. The public `GET /health` (load balancer probe) stays as it is; the page reads
`GET /system/health`.

## Shape

```
backend/services/heartbeat.py      beat(name, ok=True, error=None, interval_s=None), snapshot()
backend/services/system_health.py  the checks, each with its own cache TTL; collect(refresh)
backend/routers/system_health.py   GET /system/health (admin only)
frontend/src/pages/Health.tsx      /health
```

## Checks

Each check returns `{"id", "label", "status", "summary", "details", "checked_at", "latency_ms"}`
with `status` ∈ `ok | warn | error | off` (`off` = not configured, not an error). Results are
cached per check; `?refresh=true` recomputes all.

| id | What | TTL |
|---|---|---|
| `backend` | process up, uptime, Python, threadpool size | 0 |
| `neo4j` | `verify_connectivity` latency; node and relationship counts per label (`apoc.meta.stats`, else `count()` per main label) | 60 s |
| `llm:<provider>` | one per provider (`anthropic`, `anthropic-work`, `openai`, `litellm`, `claude-code`): configured?, which one runs the fast tasks, reachable (`models.list`, 5 s timeout; no tokens spent) | 300 s |
| `storage` | storage backend in use (Drive / local), Drive credentials present and reachable, local files directory writable and its size | 600 s |
| `disk` | `shutil.disk_usage` for the local files dir, `backend/data`, the log dir; warn ≥ 85 %, error ≥ 95 % | 60 s |
| `ingest` | upload pre-processing and pre-analysis jobs pending / running / failed (in-memory caches), reference import jobs, last ingest (newest `Paper.created_at`) | 10 s |
| `jobs` | concept-map builds running, papers that failed mapping 3×, reports running / failed in 24 h, quick tours with an error | 30 s |
| `sweepers` | background threads: concept-map sweeper, library embeddings, conference auto-build: alive (by thread name), last beat, last error | 0 |
| `tokens` | today's calls, errors and spend from the token ledger | 30 s |

Overall `status`: `error` if any check is `error`, `degraded` if any is `warn`, else `ok`.

## Response

```json
{
  "generated_at": "2026-11-12T10:00:00+00:00",
  "status": "ok",
  "checks": [Check],
  "version": {"app": "…", "git_sha": "abc1234", "git_branch": "main", "python": "3.11.9",
              "started_at": "…", "uptime_s": 0},
  "tokens_today": {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
  "recent_errors": [{"ts": "2026-11-12 09:58:01", "logger": "services.ai", "level": "ERROR", "message": "…"}],
  "sweepers": [{"name": "concept-map-sweeper", "alive": true, "last_run": "…", "last_ok": true,
                "last_error": null, "interval_s": 600}],
  "audit": {"actions_24h": 0, "last": [{"ts", "username", "action_type", "entity_type"}]}
}
```

`recent_errors`: the last 30 `ERROR` / `CRITICAL` lines of `logs/app.log` (read from the file's
last 512 KB, newest first). `version.git_sha`: `GIT_SHA` env, else read from `.git` next to the
backend when the repository is mounted, else `null`; `version.app`: `APP_VERSION` env or `dev`.

## Settings

| Variable | Default | |
|---|---|---|
| `GIT_SHA` | `""` | shown as the version when the repository is not mounted |
| `APP_VERSION` | `""` | free-form version label |

## Tests

`tests/test_system_health.py`: admin-only, response shape, caching (a second call does not re-run
an expensive check), provider "off" without keys, log tail parsing, heartbeat snapshot. Neo4j and
SDK clients mocked.
