# Reports — developer context

A report is a long read written from the library: the user asks a question (or picks a project,
or both), and a background job retrieves the relevant papers, reads their summaries, claims, the
user's notes and highlights and passages of the full text, and writes a sectioned article that
cites library papers (links to `/paper/<id>`). Reports are stored per user in Neo4j, listed,
viewable, exportable as Markdown or HTML, and deletable.

## Shape

```
backend/db/queries/reports.py        Report nodes: create, get, list, update progress, finish, delete
backend/services/reports/
  __init__.py
  pipeline.py    run_report(report_id): scope → plan → evidence → sections → frame → save
  retrieval.py   candidate papers for a query (library search, project, attached ids) and the
                 evidence pack per paper (summary, abstract, claims, note, highlights, passages)
  llm.py         complete(messages, *, model, max_tokens, json_mode) on the app's configured models
  render.py      citation markers → links, reference list, Markdown → standalone HTML (no new deps)
  jobs.py        start(report_id), cancel(report_id), recover_interrupted(driver); thread pool
backend/routers/reports.py           /reports/* HTTP API
prompts/report_plan.txt, report_section.txt, report_frame.txt
frontend/src/pages/Reports.tsx       /reports (list + new) and /reports/:id (viewer)
```

## Storage (Neo4j)

`(:Report {id, owner, title, question, project_id, project_name, length, model, status, stage,
progress, steps_json, markdown, error, paper_count, word_count, created_at, updated_at,
finished_at})` and `(:Report)-[:CITES_PAPER {n}]->(:Paper)` for every cited paper (`n` = its
number in the reference list). Constraint `report_id` (unique `Report.id`), created with the other
constraints in `db/schema.py`. `status` ∈ `queued | running | done | failed | cancelled`;
`progress` 0–100; `steps_json` the last 50 progress lines `[{"ts", "message"}]`. Deleting a paper
removes its `CITES_PAPER` edge, never the report. Reports are private: only the owner and admins
read or delete them.

## Pipeline

1. **Scope** (→ 10 %). Candidates = `paper_ids` given, the project's papers if `project_id`, and
   the top hits of the library search for the question (`services.library_search.engine.search`,
   hybrid mode, lexical fallback; visibility-filtered as the request user, which the job thread
   inherits). A project without a question asks for an overview of the project's literature.
2. **Plan** (→ 20 %). One JSON call: title, lede, 3 / 5 / 7 sections (`length` short / standard /
   long), each with a focus, 1–3 search queries and the candidate ids it should draw on.
3. **Evidence** (→ 55 %). Per section: extra retrieval with its queries, then an evidence pack per
   paper (≤ 8 papers per section): title, year, first authors, venue, summary, abstract, up to 8
   claims, the user's note, up to 6 highlights with comments, and up to 2 full-text passages
   around the query terms. Packs are capped by a character budget (`REPORTS_EVIDENCE_CHARS`, 0 =
   20,000 on the LiteLLM model, 60,000 on Anthropic or OpenAI). Every paper gets a global source
   number `S1…Sn`.
4. **Sections** (→ 90 %). One call per section, Markdown, every claim followed by `[S3]`-style
   markers; only the section's sources may be cited.
5. **Frame** (→ 97 %). One call: lede/introduction and a closing section (what the library shows,
   what it does not, open questions).
6. **Save** (100 %). Markers become `[[3]](/paper/<id>)`; unknown markers are dropped; a
   "References" list is appended in first-cited order; `CITES_PAPER` edges are written.

The job checks the cancel flag between steps. At most `REPORTS_MAX_PARALLEL` (2) reports run at
once; further ones wait as `queued`. A restart marks `queued` / `running` reports `failed` with
"Interrupted by a server restart" (`jobs.recover_interrupted`, called at startup). All LLM calls
run inside `usage_context(feature="reports", user=owner)`, so the token ledger attributes them.

## Models

`model` in the request: `fast` (default: the app's fast provider through
`services.litellm_client.chat_completion`: LiteLLM, Anthropic Haiku or OpenAI, whichever is
configured), `claude` (the user's personal Anthropic key, `REPORTS_CLAUDE_MODEL`, default
`claude-sonnet-4-6`), `claude-work` (the work gateway, same model). `GET /reports/options` says
which are available.

## API (`routers/reports.py`)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/reports/options` | | `{"models": [{"id": "fast", "label": "Claude Haiku 4.5", "available": true}], "lengths": ["short", "standard", "long"], "default_model": "fast"}` |
| POST | `/reports` | `{"question"?: str, "project_id"?: str, "paper_ids"?: [str], "length"?: "standard", "model"?: "fast"}` | 202, `ReportSummary` (422 without question and project) |
| GET | `/reports` | `?all=false` (admins: `all=true` lists every user's) | `[ReportSummary]`, newest first |
| GET | `/reports/{id}` | | `ReportDetail` (404 when missing or not yours) |
| GET | `/reports/{id}/export` | `?format=md\|html` | file download, `Content-Disposition: attachment; filename="<slug>.md"` |
| POST | `/reports/{id}/cancel` | | `ReportSummary` |
| DELETE | `/reports/{id}` | | 204 |

`ReportSummary`: `{"id", "title", "question", "project_id", "project_name", "status", "stage",
"progress", "model", "length", "owner", "created_at", "updated_at", "finished_at",
"paper_count", "word_count", "error"}`.
`ReportDetail` = `ReportSummary` + `{"markdown", "steps": [{"ts", "message"}], "papers":
[{"id", "title", "year", "n"}]}`.

The HTML export is one self-contained page (inline CSS, no external requests) in the long-read
look of the desk reports: eyebrow, title, lede, an "AI-written" note naming the model and date,
numbered sections, reference list with library links (made absolute with `FRONTEND_URL`).

## Settings

| Variable | Default | |
|---|---|---|
| `REPORTS_MAX_PARALLEL` | `2` | concurrent report jobs |
| `REPORTS_CLAUDE_MODEL` | `claude-sonnet-4-6` | model for `claude` / `claude-work` |
| `REPORTS_EVIDENCE_CHARS` | `0` | evidence budget per section (0 = by provider) |

## Tests

`tests/test_reports_pipeline.py` (LLM and retrieval mocked; checks progress, citations, references,
cancel, failure), `tests/test_reports_render.py`, `tests/test_reports_router.py` (query layer
replaced by an in-memory fake; ownership, export, delete). No real Neo4j, no API calls.
