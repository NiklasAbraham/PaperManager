# Ingestion Workflow

How papers enter the library, what runs when, and why.

---

## PDF Upload (queue)

### Stage 1 — Parse + preprocess + preanalyze (immediate, on drop)

Three requests start as soon as you drop a file. Nothing is saved.

**1a — Metadata** (`POST /papers/parse`)

| Step | What runs | Cost |
|------|-----------|------|
| Extract raw text | pypdf | local, fast |
| Find DOI / arXiv ID | regex on first page | local, fast |
| Metadata lookup | Semantic Scholar → CrossRef API | network |
| LiteLLM fallback | first 3 000 chars | local, ~2 s |
| Heuristics fallback | first-line title, year regex | local, instant |
| Abstract extraction | regex → Claude Haiku if needed | conditional |

**1b — Layout** (`POST /papers/preprocess`)

| Step | What runs | Cost |
|------|-----------|------|
| Docling | figures + tables (once per PDF hash) | GPU / slow |

**1c — Analysis** (`POST /papers/preanalyze`) — the heavy LLM work, precomputed

| Step | What runs | Cost |
|------|-----------|------|
| summary | `summarize_paper` (default instructions) | LLM |
| ai_topics | `suggest_topics` | LLM |
| claims | `extract_claims` | LLM |
| references | `extract_references` | LLM / network |
| affiliations | `extract_affiliations_with_litellm` | LLM |
| tag_suggestions | `suggest_tags_litellm` | LLM |

Result: metadata pre-fills the modal; figures/tables **and** the full LLM analysis
are cached on disk (keyed by PDF SHA-256). **No paper is created.**

The queue row turns **green ("Ready — click to review")** only once metadata,
layout, **and** analysis are all ready — meaning Upload will be a pure save with no
LLM work. The queue is persisted to IndexedDB and re-verified on return.

Normative spec: `.specs/009_upload_queue_workflow.md`

---

### Stage 2 — Confirm (modal, user-driven)

You open the modal, verify the pre-filled metadata, and **pick the document type**.
Document type controls what runs in Stage 3:

| Type | Summary | Figures | References |
|------|---------|---------|------------|
| Paper (default) | ✓ | ✓ | ✓ |
| Book | ✗ | ✗ | ✗ |
| Lecture deck | ✗ | ✗ | ✗ |

Nothing is saved until you click **Upload →**.

---

### Stage 3 — Upload (triggered on confirm)

Triggered by: `POST /papers/upload`
Runs synchronously — the modal spinner shows while this completes.

```
PDF bytes
  │
  ├─ 0. load cached analysis      → analysis_key → result.json (no LLM)
  │
  ├─ 1. metadata                  → REUSE cached meta (else extract_metadata)
  │
  ├─ 2. title_override            → apply any title edit from the modal
  │
  ├─ 3. Drive upload              → stores PDF, returns drive_file_id
  │
  ├─ 4. summary                   → REUSE cached summary                     [PAPER only]
  │       re-runs summarize_paper ONLY if you edited the instructions
  │
  ├─ 5. embed_paper               → skipped unless litellm_embed_model is set
  │
  ├─ 6. save to Neo4j             → Paper node created (or stub enriched)
  │       duplicate check: 409 if paper with drive_file_id already exists
  │
  ├─ 7. link authors              → Person nodes, REUSE cached affiliations, S2 IDs
  │       7b. enrichment          → ORCID + S2 HTTP (not LLM, 24h cooldown)
  │
  ├─ 8. link topics              → Semantic Scholar topics + REUSE cached AI topics
  │
  ├─ 9. claims                   → REUSE cached claims                       [PAPER only]
  │
  ├─ 10. references              → REUSE cached references                   [PAPER only]
  │
  └─ 12. figures + tables        → reuse Stage 1b cache; upload images to Drive  [PAPER only]
```

**With a fully-precomputed (green) row, Upload makes _no_ LLM calls** — everything
is reused from the analysis cache. The only intentional LLM call is the summary, and
only if you edited the summary instructions in the modal.

**Where the Upload time goes:** ~1–2 s Drive PDF upload + Neo4j writes + ORCID/S2
enrichment, then ~10–15 s uploading figure/table images to Google Drive (step 12).
That last step is the bulk of the wait and is not precomputed by design.

**Docling runs at most once per PDF:** during Stage 1b (queue) when possible; upload step 12 only runs Docling if preprocess failed or was skipped.

---

### Stage 4 — Onboarding (modal, user-driven)

After the upload completes the modal walks through:

1. **References** — review extracted references, uncheck any to skip
2. **Tags** — AI-suggested + your existing tags, add custom ones
3. **Project** — optionally assign to a project
4. **People** — link supervisor / colleague / who shared it

These steps are purely interactive and make no AI calls.

---

## Why extract_metadata runs twice

Stage 1 (`/papers/parse`) extracts metadata to pre-fill the modal.
Stage 3 (`/papers/upload`) needs to re-run it because the raw text is required for the summary and is too large to pass through the frontend. The Stage 1 result is discarded client-side after filling the form.

**Consequence:** Ollama + S2 API calls happen twice per paper. Summary and figures happen once.

---

## URL Ingest

Triggered by: `POST /papers/from-url-full`

```
URL
  │
  ├─ resolve metadata (arXiv API / S2 / CrossRef / PubMed)
  │
  ├─ download PDF (arXiv / bioRxiv only — others blocked by Cloudflare)
  │
  ├─ [if PDF available]
  │     ├─ extract_metadata from PDF
  │     ├─ Drive upload
  │     ├─ summarize_paper (full text)
  │     ├─ save to Neo4j
  │     ├─ extract references
  │     └─ extract figures
  │
  └─ [if no PDF]
        ├─ summarize_paper (abstract only — shorter, weaker)
        └─ save to Neo4j (no drive_file_id, no raw_text)
```

Modal still shows refs → tags → project → people onboarding after this completes.

---

## Duplicate handling

| Scenario | Outcome |
|----------|---------|
| Same DOI / title in queue, not yet uploaded | Both show "Ready". First to upload wins; second gets 409 in the modal. |
| Paper already in library (has PDF) | Caught in Stage 1 duplicate check → queue row shows "Already in your library" |
| Paper exists as a stub (URL-ingested, no PDF) | Upload enriches the stub with full text, new summary, figures. Old abstract-based summary is replaced. |

The stub enrichment case is the **only scenario where a summary is regenerated** — and it's intentional: the full-text summary from Stage 3 is better than the abstract-only summary from URL ingest.

---

## Book / Lecture Deck

When you select Book or Lecture Deck in the modal:

- Steps 4, 9, 10, 11 (summary, claims, references, figures) are all skipped
- Tags `book` or `lecture_deck` are applied automatically
- Chapter structure can be detected afterwards via **Chapters** tab on the paper detail page

---

## Manual operations (on-demand, never automatic)

These only run when you explicitly trigger them from the paper detail page:

| Action | Endpoint | What it does |
|--------|----------|--------------|
| Regenerate summary | `POST /{id}/regenerate-summary` | Re-runs Claude summary on stored raw_text |
| Re-extract abstract | `POST /{id}/reextract-abstract` | Regex + Claude Haiku on raw_text |
| Re-extract references | `GET /{id}/ai-extract-references` | Forces Claude Haiku reference extraction |
| Extract figures | triggered from Figures tab | Re-runs Docling / pypdf pipeline |
