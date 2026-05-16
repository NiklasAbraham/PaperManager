# Ingestion Workflow

How papers enter the library, what runs when, and why.

---

## PDF Upload (queue)

### Stage 1 — Parse (immediate, on drop)

Triggered by: `POST /papers/parse`
Runs in background as soon as you drop the file. Nothing is saved.

| Step | What runs | Cost |
|------|-----------|------|
| Extract raw text | pypdf / pdfminer | local, fast |
| Find DOI / arXiv ID | regex on first page | local, fast |
| Metadata lookup | Semantic Scholar → CrossRef API | network |
| Ollama fallback | `llama3.2:3b` on first 3 000 chars | local, ~2 s |
| Heuristics fallback | first-line title, year regex | local, instant |
| Abstract extraction | regex → Claude Haiku if needed | conditional |

Result: title, authors, year, DOI, abstract are pre-filled in the modal.
**No paper is created. No summary. No figures.**

The queue row shows "Ready — click to review" once this finishes.

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
  ├─ 1. extract_metadata          → title / authors / year / DOI / abstract
  │       (same pipeline as Stage 1, runs again — raw text needed for summary)
  │
  ├─ 2. title_override            → apply any title edit from the modal
  │
  ├─ 3. Drive upload              → stores PDF, returns drive_file_id
  │
  ├─ 4. summarize_paper           → Claude opus-4 on full raw text          [PAPER only]
  │       uses your custom summary instructions if set
  │
  ├─ 5. embed_paper               → Ollama embedding (skip if disabled)
  │
  ├─ 6. save to Neo4j             → Paper node created (or stub enriched)
  │       duplicate check: 409 if paper with drive_file_id already exists
  │
  ├─ 7. link authors              → Person nodes, affiliations, S2 IDs
  │
  ├─ 8. link topics               → Semantic Scholar topics + AI suggestions
  │
  ├─ 9. extract claims            → Claude Haiku                            [PAPER only]
  │
  ├─ 10. extract references       → S2 API → regex → Claude Haiku fallback  [PAPER only]
  │
  └─ 11. extract figures          → Docling layout model → pypdf fallback    [PAPER only]
          captions: Ollama (default) | Claude vision | Docling built-in
```

**AI summary runs exactly once — here, step 4.**
It never ran during Stage 1 (parse) or during queue waiting.

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
