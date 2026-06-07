# Upload Queue Workflow (normative)

This spec defines the end-to-end PDF upload path: queue, preprocessing, confirmation, and commit.
Implementations and tests MUST match this document.

Related: `003_ingestion.md` (overview), `docs/technical/ingestion-workflow.md` (narrative).

---

## Goals

1. **Docling runs once per PDF** while the file is in the upload queue, not on confirm.
2. **Figures and tables** are extracted during queue time so confirm/upload is faster.
3. **All heavy LLM work** (metadata, summary, AI topics, claims, references, author
   affiliations, tag suggestions) is **precomputed** while the file sits in the queue,
   so that clicking **Upload** performs **no LLM calls** — it only reuses cached
   results, writes to Neo4j, and uploads assets to Drive.
4. **Metadata parse** stays fast and independent of Docling.
5. Upload **reuses** cached layout + analysis output; it MUST NOT start a second
   Docling run or re-run any LLM step when a valid cache entry exists.
6. The queue **survives navigation/reload** (persisted to IndexedDB) and
   **self-heals**: if the backend cache was lost, precompute restarts automatically.

---

## Actors and storage

| Component | Role |
|-----------|------|
| Frontend queue (`PaperDrop`) | Holds `File` + metadata + `preprocess_key` + `analysis_key` + statuses + tag suggestions per row; persisted to IndexedDB |
| `POST /papers/parse` | Metadata only (pypdf + S2/CrossRef/LLM/heuristics) — fast modal preview |
| `POST /papers/preprocess` | Starts Docling figure/table extraction; idempotent per PDF SHA-256 |
| `GET /papers/preprocess/{key}` | Status: `pending` \| `running` \| `ready` \| `error` \| `missing` |
| `POST /papers/preanalyze` | Starts the heavy LLM analysis (summary, topics, claims, references, affiliations, tag suggestions); idempotent per PDF SHA-256 |
| `GET /papers/preanalyze/{key}` | Status + `tag_suggestions` once `ready` |
| Preprocess cache | Disk under `INGEST_PREPROCESS_DIR` (default `/tmp/papermanager_preprocess`), TTL 24h |
| Analysis cache | Disk under `INGEST_ANALYSIS_DIR` (default `/tmp/papermanager_analysis`), TTL 24h, `result.json` |
| `POST /papers/upload` | Full ingest; consumes both caches when `preprocess_key` / `analysis_key` provided |

> **Cache key:** Both caches key on **SHA-256 of the raw PDF bytes**, so for a given
> file `preprocess_key == analysis_key`. The same file always maps to the same caches.

> **Single-GPU serialization:** The LiteLLM proxy and Docling share one GPU. Both
> caches serialize their heavy work with a semaphore (`PREANALYZE_CONCURRENCY`,
> `DOCLING_CONCURRENCY`, default `1`) so the first queued file finishes (turns
> green) quickly instead of all files thrashing the GPU at once.

---

## Stage 0 — Drop (client)

**Trigger:** User drops one or more PDFs on Library **+** → PDF tab.

**Client MUST**, through a small concurrency pool (max ~2 in-flight to respect the
browser per-host connection limit), for each file run these stages **sequentially**:

1. Append each file to the queue with `status: parsing`.
2. Stage 1a — `POST /papers/parse` (metadata for the modal) → run duplicate check.
3. Stage 1b — `POST /papers/preprocess` with `caption_method` from user settings
   (`figureCaptionMethod`, default `docling`); store the returned `preprocess_key`.
4. Stage 1c — `POST /papers/preanalyze`; store the returned `analysis_key`.
5. Poll `GET /papers/preprocess/{key}` and `GET /papers/preanalyze/{key}` every ~3s
   until each is `ready` or `error`.
6. A row only shows the **green “ready”** indicator when **status is `ready` AND both
   `preprocess` and `preanalyze` are `ready`** (i.e. fully precomputed).

**Persistence & self-heal:**

- The queue (file bytes + metadata + `preprocess_key`/`analysis_key` + statuses +
  tag suggestions) is persisted to IndexedDB, so leaving and returning to the page
  restores it without recomputing.
- On restore, the client re-verifies each row against the backend (`GET` status). If
  the backend cache is gone (e.g. backend restarted / `/tmp` cleared) or not ready,
  it **re-fires** `preprocess`/`preanalyze` so the queue returns to fully precomputed
  on its own.

**Client MUST NOT** call Docling, figure extraction, or any analysis LLM directly.

---

## Stage 1 — Parse (server, parallel)

**Endpoint:** `POST /papers/parse`

| Step | Action |
|------|--------|
| 1 | `extract_text` via pypdf |
| 2 | DOI / arXiv detection |
| 3 | Semantic Scholar → CrossRef |
| 4 | LiteLLM fallback on first 3000 chars |
| 5 | Heuristic title/year |
| 6 | Abstract regex → Claude Haiku if needed |

**Response:** JSON metadata (no `raw_text`).

**On success:** Client runs duplicate check (`GET /papers/check-duplicate`).
- If duplicate has existing PDF (`drive_file_id` present) → row `duplicate`.
- If duplicate is a reference stub (no `drive_file_id`) → row stays `ready` (with hint) so user can confirm upload and enrich the existing node.
- If no duplicate → row `ready`.

**No Neo4j write. No summary. No Drive.**

---

## Stage 1b — Preprocess (server, parallel, once per hash)

**Endpoint:** `POST /papers/preprocess`

| Rule | Behavior |
|------|----------|
| Cache key | SHA-256 of raw PDF bytes |
| Idempotency | If status is `pending`, `running`, or `ready` for that key → return same key, do **not** start another job |
| New job | Background thread runs `extract_figures` (Docling → remote/on-demand/local per config) |
| Output | PNGs on disk + `tables` JSON (markdown per table) |
| Terminal states | `ready` or `error` |

**Caption method:** Taken from request; used for Docling + optional caption supplements during preprocess.

**Failure:** Non-fatal for queue. Row may show layout error; upload may fall back (see Stage 3).

---

## Stage 1c — Preanalyze (server, parallel, once per hash)

**Endpoint:** `POST /papers/preanalyze`

Runs the **entire heavy LLM pipeline once** in a background thread and caches the
result (`result.json`) keyed by the PDF SHA-256. This is what makes Upload instant.

| Rule | Behavior |
|------|----------|
| Cache key | SHA-256 of raw PDF bytes (same key as preprocess) |
| Idempotency | If status is `pending`, `running`, or `ready` → return same key, do **not** start another job |
| Serialization | Held behind `PREANALYZE_CONCURRENCY` semaphore (default 1) so one file finishes before the next starts |
| Terminal states | `ready` or `error` |

**Precomputed and stored in `result.json`:**

| Field | Produced by | LLM? |
|-------|-------------|------|
| `meta` | `extract_metadata` (pypdf + S2/CrossRef + LLM fallback) | sometimes |
| `summary` | `summarize_paper` (default instructions) | **yes** |
| `ai_topics` | `suggest_topics` | **yes** |
| `claims` | `extract_claims(model="litellm")` | **yes** |
| `references` | `extract_references` | **yes** |
| `affiliations` | `extract_affiliations_with_litellm` (authors missing an affiliation) | **yes** |
| `tag_suggestions` | `suggest_tags_litellm` | **yes** |

**`GET /papers/preanalyze/{key}`** returns `{status, ...}` and, once `ready`, includes
`tag_suggestions` so the modal's tag step is instant.

**Failure:** Non-fatal. Upload falls back to running the missing LLM steps inline.

---

## Stage 2 — Review (client)

**Trigger:** User clicks a `ready` queue row (fully precomputed).

**Modal shows:** Title, authors, year, DOI, abstract, document type. Tag suggestions
are taken from the precomputed `tag_suggestions` (no `POST /tags/suggest` call needed).

| Document type | Summary on upload | Figures/tables | References | Claims |
|---------------|-------------------|----------------|------------|--------|
| `paper` (default) | yes | yes (from cache) | yes | optional |
| `book` | no | no | no | no |
| `lecture_deck` | no | no | no | no |

**Nothing persisted until user confirms upload.**

---

## Stage 3 — Upload (server, on confirm)

**Endpoint:** `POST /papers/upload`

**Form fields (relevant):** `file`, `title_override`, `document_type`, `preprocess_key`, `analysis_key`, `caption_method`, `summary_instructions`, `claims_model`, `skip_embedding`, …

> **Normative:** When `analysis_key` is provided and the analysis cache is `ready`,
> Upload MUST reuse every cached field below and MUST NOT make any LLM call. The only
> work performed is Drive uploads (PDF + figure images), Neo4j writes, and best-effort
> author enrichment over public HTTP APIs (ORCID / Semantic Scholar). Verified by log
> trace: a fully-precomputed paper upload shows **zero `chat_completion` calls**.

### Order of operations

```
PDF bytes
  │
  ├─ 0. wait_for_result(analysis_key)      → load cached analysis (no LLM)
  ├─ 1. metadata                           → REUSE analysis["meta"]      (else extract_metadata)
  ├─ 2. title_override
  ├─ 3. Google Drive PDF upload            → ~1–2s network
  ├─ 4. summary                            → REUSE analysis["summary"]   (else summarize_paper)*
  ├─ 5. embed_paper                        → SKIPPED unless litellm_embed_model is set
  ├─ 6. Neo4j Paper node (409 if duplicate PDF exists)
  ├─ 7. Authors + affiliations             → REUSE analysis["affiliations"] (else extract_affiliations_with_litellm)
  ├─ 7b. Author enrichment                 → ORCID + S2 HTTP (not LLM, 24h cooldown)
  ├─ 8. Topics (S2 from meta + AI)         → REUSE analysis["ai_topics"]  (else suggest_topics)
  ├─ 9. Claims                             → REUSE analysis["claims"]     (else extract_claims)  [paper only]
  ├─ 10. Project link                      [optional]
  ├─ 11. References                        → REUSE analysis["references"] (else extract_references) [paper only]
  └─ 12. Figures + tables                  → REUSE preprocess cache; save images to Drive [paper only]
```

\* Summary is reused **only when the user kept default `summary_instructions`** (the
precompute always uses defaults). If the user edits the instructions in the modal,
Upload re-runs `summarize_paper` — the **one intentional** LLM call at upload time.

**Dominant remaining cost:** Step 12 uploads each extracted figure image to Google
Drive and writes `Figure`/`Table` nodes. This is the bulk of the perceived Upload
time (~10–15s for a figure-heavy paper) and is **not** precomputed by design.

### Step 12 — Figures and tables (normative)

| Condition | Behavior |
|-----------|----------|
| `document_type` is `book` or `lecture_deck` | Skip step 12 |
| `preprocess_key` set and cache `ready` | `wait_for_result` → `consume_result` → save figures (Drive) + tables (Neo4j). **Do not** call `extract_figures` again |
| `preprocess_key` set but cache not ready | Block up to `docling_ready_timeout` (default 600s) waiting for cache; then same as ready |
| No key or cache `error` / timeout | Run `extract_figures` once on upload (fallback) |
| Cache miss | Same as fallback |

**Save:** `save_figures_and_tables` — figures to Drive + `Figure` nodes; tables to `Table` nodes (markdown).

**Docling MUST run at most once per successful path:** either preprocess OR upload fallback, never both for the same upload when cache hits.

---

## Stage 4 — Onboarding (client)

After upload returns `IngestOut`:

1. References (optional review)
2. Tags
3. Project
4. People / source

No Docling. No metadata re-parse.

---

## What is precomputed, and what each click does

**While the file sits in the queue (no clicks):** the backend runs Docling
(`preprocess`) and the full LLM analysis (`preanalyze`) once each, in the
background, and caches both on disk. The row turns **green** only when both are
`ready`.

| Click | What happens | LLM calls |
|-------|--------------|-----------|
| **Drop PDF(s)** | Queue rows created; `parse` + `preprocess` + `preanalyze` fire automatically | All LLM work runs **here**, in the background, once per file |
| **Click a green row** | Opens the review modal; tags come from precomputed `tag_suggestions` | **None** |
| **Click “Upload” (default summary)** | Reuse cached meta/summary/topics/claims/refs/affiliations → Drive PDF upload → Neo4j writes → author enrichment (HTTP) → save figure images to Drive | **None** |
| **Click “Upload” (edited summary instructions)** | Same as above but `summarize_paper` re-runs with the new instructions | **Exactly one** (summary) |
| **Onboarding steps** (refs/tags/project/people) | Pure Neo4j writes | **None** |

**So when you click Upload on a green row with default settings, no LLM runs.** The
seconds you see are: ~1–2s Drive PDF upload, a moment of Neo4j writes + ORCID/S2
HTTP enrichment, and ~10–15s uploading the figure/table images to Google Drive
(Step 12). If Upload ever feels like it's “thinking” longer, it means the row was
**not** fully green (precompute not finished or cache lost) and Upload is doing the
LLM work inline as a fallback.

---

## Duplicate and edge cases

| Scenario | Expected behavior |
|----------|-------------------|
| Same PDF dropped twice in queue | Same `preprocess_key`/`analysis_key`; single Docling + single analysis job |
| Upload while preprocess/preanalyze still running | Upload waits on the cache(s) (preprocess up to 300s, analysis up to 180s); on timeout, runs the missing step inline |
| Preprocess error | Upload runs Docling inline once |
| Preanalyze error / no `analysis_key` | Upload runs the missing LLM steps inline (metadata/summary/topics/claims/refs/affiliations) |
| Leave page and return | Queue restored from IndexedDB; rows re-verified and precompute re-fired if backend cache was lost |
| Book / lecture deck | Preprocess/preanalyze may still run client-side; upload skips figures, summary, refs, claims |
| Paper already in library (has PDF) | Stage 1 duplicate check → queue `duplicate` |
| Duplicate is existing reference stub (no PDF) | Stage 1 remains `ready`; on upload, enrich existing Paper node in place (preserve references/links) |
| Second upload same DOI | 409 on upload |
| Stub enrich (URL ingest, no PDF) | Upload replaces summary; preprocess_key usually absent → inline Docling |
| Embeddings | Disabled when `litellm_embed_model` is empty (current default) — Step 5 is skipped entirely |

---

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/papers/parse` | Metadata for modal |
| POST | `/papers/preprocess` | Start / join Docling job |
| GET | `/papers/preprocess/{key}` | Poll Docling status |
| POST | `/papers/preanalyze` | Start / join LLM analysis job |
| GET | `/papers/preanalyze/{key}` | Poll analysis status (+ `tag_suggestions` when ready) |
| GET | `/papers/check-duplicate` | DOI/title duplicate |
| POST | `/papers/upload` | Full ingest (reuses both caches) |

---

## Validation checklist

Use this when changing upload code:

- [ ] Dropping a PDF starts **parse + preprocess + preanalyze** without waiting for user click
- [ ] Dropping the same file twice does not start two Docling jobs or two analysis jobs (same hash)
- [ ] A row turns green only when status `ready` **and** preprocess `ready` **and** preanalyze `ready`
- [ ] Upload with a `ready` `analysis_key` makes **zero LLM calls** (verify via logs: no `chat_completion`), except when the user edited summary instructions (then exactly one)
- [ ] Upload with valid `preprocess_key` does not call `extract_figures` when cache is `ready`
- [ ] Upload reuses `meta`, `summary`, `ai_topics`, `claims`, `references`, `affiliations` from the analysis cache
- [ ] Upload saves **tables** as well as figures for papers
- [ ] Embeddings (Step 5) are skipped when `litellm_embed_model` is empty
- [ ] Leaving and returning to the page restores the queue and re-fires precompute if the backend cache was lost
- [ ] Duplicate reference stubs (no PDF) are not blocked in queue and are enriched in place on upload
- [ ] Book/lecture deck upload skips figures, tables, summary, refs, claims
- [ ] `extract_metadata` falls back on upload only when no analysis cache is present (raw_text for summary)
- [ ] Cache entry removed after successful consume (no stale reuse across different papers with same bytes is intentional: same PDF = same assets)

---

## Configuration

| Env / setting | Effect |
|---------------|--------|
| `INGEST_PREPROCESS_DIR` | Docling figure/table cache directory |
| `INGEST_ANALYSIS_DIR` | LLM analysis cache directory |
| `DOCLING_CONCURRENCY` | Max concurrent Docling jobs (default 1; single GPU) |
| `PREANALYZE_CONCURRENCY` | Max concurrent analysis jobs (default 1; single GPU) |
| `docling_mode`, `docling_serve_url`, `inference_manager_url` | Where Docling runs |
| `docling_ready_timeout` | Max wait on upload for in-flight preprocess |
| `litellm_embed_model` | Embedding model; **empty disables Step 5** (current default) |
| User `figureCaptionMethod` | Passed to `/papers/preprocess` |
