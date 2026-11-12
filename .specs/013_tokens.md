# Token ledger — developer context

Every LLM call the backend makes is recorded once, with what it cost at list price. The Tokens
page (`/tokens`) reads the ledger; the Health page shows today's spend from it.

## Shape

```
backend/services/usage/
  __init__.py   re-exports: install, usage_context, record_call
  pricing.py    PRICES table (USD per million tokens), PRICES_AS_OF, price_for(model), cost(...)
  ledger.py     SQLite store: record(row), query helpers for the router and Health
  hook.py       install(): wraps the Anthropic and OpenAI SDK methods; usage_context();
                feature / paper / user attribution
backend/routers/tokens.py   /tokens/* HTTP API
frontend/src/pages/Tokens.tsx
```

## Why SQLite and not Neo4j

The ledger is append-only, grows by one row per LLM call (thousands a day during a bulk import)
and is only ever read as aggregates (`GROUP BY day / feature / model / user`). SQLite does that
in milliseconds, keeps the graph free of bookkeeping nodes (the library graph is what users browse,
export and back up), and records even when Neo4j is down or reconnecting. One file:
`USAGE_DB_PATH`, default `backend/data/usage.sqlite` (`/app/data/usage.sqlite` in the containers:
a bind mount in `docker-compose.example.yml`, the `paper_files` volume in the self-host compose).
WAL mode, one short write per call under a lock; the MCP server process writes to the same file.

## Where the logger hooks in

`services.usage.install()` runs once at import of `main.py`; `mcp_server.py` calls `install_lazy()`, which wraps each SDK the moment it is first imported, so the MCP server's startup stays free of anthropic/openai (`tests/test_mcp_lean.py`). It wraps,
idempotently, the SDK methods every call site ends up in, so no call site has to remember it and
new ones are covered automatically:

| SDK method | Covers |
|---|---|
| `anthropic` `Messages.create` (also `stream=True`) and `Messages.stream` | every `anthropic.Anthropic(...)` client in services and routers: personal key, work/Foundry gateway, fast provider "anthropic", LiteLLM fallback to Haiku |
| `anthropic` beta `Messages.create` / `Messages.stream` | concepts (`client.beta.messages.stream`) |
| `openai` `Completions.create` (chat, also `stream=True`) | LiteLLM proxy (Gemma) and OpenAI through `services/litellm_client.py`, the knowledge chat's LiteLLM path |
| `openai` `Embeddings.create` | LiteLLM embeddings (off by default) |

Claude Code (subscription, `services/claude_code_chat.py`) runs the CLI in a subprocess, so it
records explicitly from the `ResultMessage` (usage + `total_cost_usd`).

Provider is read from the client's base URL: `api.anthropic.com` → `anthropic`, any other
Anthropic base URL → `anthropic-gateway`, `api.openai.com` → `openai`, any other OpenAI-compatible
base URL → `litellm`; `claude-code` for the subscription path.

### Attribution

- **feature**: an explicit `usage_context(feature=...)` wins; otherwise the innermost backend
  frame on the call stack outside `services/usage/` and `services/litellm_client.py` is mapped by
  `hook.FEATURE_RULES` (module + function → feature, e.g. `services/ai.py:summarize_paper` →
  `summary`, `services/concept_map.py` → `concept-map`). Unmapped frames give `module.function`.
  `label` always holds `module.function` of that frame.
- **user**: explicit context, else the request user (`services.auth.get_request_user()`, set by
  the auth middleware and copied into the chat's worker threads), else a `current_user` /
  `username` local on the stack, else `null` (background work: sweepers, ingest workers).
- **paper_id**: explicit context, else a `paper_id` local (str) on a backend frame of the stack.

Threads that lose the stack (Claude Code's worker) capture the context in the calling thread
(`hook.capture()`) and re-enter it with `usage_context(**captured)`.

Recording never raises into the call path: a failed write is logged once per minute and dropped.
`USAGE_LEDGER_ENABLED=false` turns recording off.

## Table `llm_calls`

| Column | Type | |
|---|---|---|
| `id` | INTEGER PK | |
| `ts` | TEXT | ISO 8601 UTC, end of the call |
| `day` | TEXT | `YYYY-MM-DD` (UTC) |
| `feature` | TEXT | `summary`, `topics`, `claims`, `knowledge-chat`, `paper-chat`, `concepts`, `concept-map`, `tour`, `cv-builder`, `reports`, ... |
| `label` | TEXT | `module.function` of the call site |
| `provider` | TEXT | `anthropic` / `anthropic-gateway` / `openai` / `litellm` / `claude-code` |
| `model` | TEXT | as sent (or reported) |
| `input_tokens` | INTEGER | uncached input (OpenAI: prompt − cached) |
| `output_tokens` | INTEGER | |
| `cache_read_tokens` | INTEGER | |
| `cache_write_tokens` | INTEGER | |
| `cost_usd` | REAL NULL | list price; NULL when the model is not in the price table |
| `price_known` | INTEGER | 0/1 |
| `username` | TEXT NULL | |
| `paper_id` | TEXT NULL | |
| `ok` | INTEGER | 0/1 |
| `error` | TEXT NULL | exception class + message, ≤ 300 chars |
| `latency_ms` | INTEGER | |
| `streamed` | INTEGER | 0/1 |
| `estimated` | INTEGER | 0/1: tokens estimated from characters (stream without usage) |

Indexes on `ts`, `day`, `username`, `feature`, `paper_id`.

## Prices (`services/usage/pricing.py`)

USD per million tokens `(input, output, cache_write_5m, cache_read)`, matched by the longest
prefix after normalising the id (lower case; provider prefixes `anthropic/`, `openai/`,
`us.anthropic.`, `anthropic.` dropped). `PRICES_AS_OF` names the date. `USAGE_PRICES_FILE`
(JSON `{"model-prefix": [in, out, cache_write, cache_read]}`) adds or overrides rows.

- LiteLLM runs on own hardware: cost 0 (`USAGE_LITELLM_FREE=true`, default).
- Claude Code: `total_cost_usd` from the CLI (list-price equivalent; the subscription is not billed
  per token). Summaries report it apart (`subscription_usd`) and leave it out of `billed_usd`.
- Unknown model: `cost_usd = NULL`, `price_known = 0`; the Tokens page lists such models.

## API (`routers/tokens.py`)

All endpoints need a session. An admin sees every user and may filter with `user=`; anyone else
sees only their own rows (`user` is ignored).

`GET /tokens/summary?days=30&user=&feature=&model=`

```json
{
  "range": {"since": "2026-10-14T00:00:00+00:00", "until": "2026-11-12T10:00:00+00:00", "days": 30},
  "scope": {"user": "niklas", "is_admin": true},
  "totals": {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0,
             "cache_read_tokens": 0, "cache_write_tokens": 0,
             "cost_usd": 0.0, "billed_usd": 0.0, "subscription_usd": 0.0, "unknown_price_calls": 0},
  "today": {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
  "by_day":  [{"day": "2026-11-12", "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}],
  "by_week": [{"week": "2026-W46", "start": "2026-11-09", "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}],
  "by_feature":  [{"feature": "summary", "calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "avg_latency_ms": 0}],
  "by_model":    [{"model": "claude-haiku-4-5", "provider": "anthropic", "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "price_known": true}],
  "by_provider": [{"provider": "anthropic", "calls": 0, "cost_usd": 0.0}],
  "by_user":     [{"user": "niklas", "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}],
  "top_calls":   [CallRow],
  "top_papers":  [{"paper_id": "…", "title": "…", "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}],
  "unknown_models": ["some-model"],
  "prices_as_of": "2026-11-12"
}
```

`by_day` has one row per day of the range (zeros filled), oldest first; `by_week` ISO weeks,
oldest first; the `by_*` lists are sorted by cost, then calls, descending; `by_user` is `[]` for
non-admins; `top_calls` and `top_papers` hold the 20 most expensive (titles read from Neo4j,
`null` when the paper is gone). `user` = `null` rows show as `"(system)"` in `by_user`.

`GET /tokens/calls?limit=100&offset=0&user=&feature=&model=&provider=&paper_id=&ok=&days=`
→ `{"calls": [CallRow], "total": 0}`, newest first, `limit` ≤ 500.

`CallRow`: `{"id", "ts", "feature", "label", "provider", "model", "input_tokens", "output_tokens",
"cache_read_tokens", "cache_write_tokens", "cost_usd", "price_known", "user", "paper_id",
"ok", "error", "latency_ms", "streamed", "estimated"}` (booleans as JSON booleans).

`GET /tokens/prices` → `{"as_of": "2026-11-12", "litellm_free": true, "models":
[{"prefix": "claude-haiku-4-5", "input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.1}]}`

## Settings

| Variable | Default | |
|---|---|---|
| `USAGE_LEDGER_ENABLED` | `true` | record calls |
| `USAGE_DB_PATH` | `""` → `backend/data/usage.sqlite` | ledger file |
| `USAGE_LITELLM_FREE` | `true` | LiteLLM calls cost 0 |
| `USAGE_PRICES_FILE` | `""` | JSON price overrides |

## Tests

`tests/test_usage_pricing.py`, `tests/test_usage_ledger.py`, `tests/test_usage_hook.py`,
`tests/test_tokens_router.py`: temp ledger file, fake SDK clients (no network), no Neo4j.
