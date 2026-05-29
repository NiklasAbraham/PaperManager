# AI Pipelines

All AI calls, which models they use, and where they run in the code.

---

## Models

| Model | Provider | Used for |
|---|---|---|
| `claude-opus-4-6` | Anthropic | Paper summarisation, single-paper chat, knowledge chat, cross-paper synthesis, research gap analysis |
| `claude-haiku-4-5-20251001` | Anthropic | Abstract extraction, reference extraction, topic suggestion, claim extraction, chapter summarisation, conversation compaction, figure captioning (claude-vision mode) |
| `llama3.2:3b` | Ollama (local) | Metadata extraction (layer 2), tag suggestion, chapter detection, figure captions (default), affiliation extraction, Cypher assist, merge duplicate scan |
| `nomic-embed-text` | Ollama (local) | 768-dim paper embedding vectors for semantic similarity search |

All Anthropic calls can be routed through an enterprise Foundry gateway via `ANTHROPIC_WORK_API_KEY` + `ANTHROPIC_WORK_BASE_URL`.

---

## Metadata Extraction (PDF Upload) — `services/pdf_parser.py`

Layer chain; stops at first success:

```
Layer 1a: DOI/arXiv ID in text → Semantic Scholar API → CrossRef (fallback)
Layer 1b: S2 title search (if title found, no DOI)
Layer 2:  Ollama llama3.2:3b on raw_text[:3000]
Layer 3:  Regex heuristics (first line = title, year regex)
Abstract fallback: ABSTRACT_RE regex → Claude Haiku
```

The `metadata_source` property records which layer succeeded.

---

## Paper Summarisation — `services/ai.py`

Triggers: PDF upload, `POST /backfill/summary`, `POST /papers/{id}/regenerate-summary`.

- Input: `abstract` + `raw_text`
- Prompt: `prompts/summary.txt` (problem / method / findings / relevance)
- Model: **Claude Opus 4.6**
- Output: `summary` string saved to Paper node

---

## Topic Suggestion — `services/ai.py`

Triggers: upload, `POST /papers/{id}/topics/suggest`, backfill.

- Input: `title` + `abstract`
- Prompt: `prompts/topics.txt`
- Model: **Claude Haiku**
- Output: 3–6 title-case topic strings → `MERGE Topic` + `ABOUT` relationships

---

## Tag Suggestion — `services/ai.py`

Triggers: upload modal (optional step), `POST /tags/suggest`.

- Input: `title` + `abstract`
- Model: **Ollama llama3.2:3b**
- Output: list of tag names from seeded vocabulary

---

## Reference Extraction — `services/references.py`

Triggers: `GET /papers/{id}/extract-references`, `POST /papers/{id}/references`.

```
Strategy A: Semantic Scholar /references API (requires DOI)
Strategy B: Regex on REFERENCES section of raw_text
Strategy C: Claude Haiku on last 30% of raw_text (when A+B < 3 results)
```

Each reference → `Paper` stub node tagged `from-references`, linked via `CITES`.

---

## Claim Extraction — `services/ai.py`

Triggers: PDF upload (if enabled in Settings), `POST /papers/{id}/claims/extract`, `POST /backfill/claims`.

- Input: `raw_text` + `title`
- Prompt: `prompts/claims.txt`
- Model: **Claude Haiku**
- Output: `[{text, type}]` — types: `finding`, `method`, `limitation`, `contribution`
- Stored as `Claim` nodes linked via `HAS_CLAIM`

Claims are **not** injected directly into Knowledge Chat context — Claude pulls them on demand via `run_cypher` when it needs evidence-level detail.

---

## Paper Embedding — `services/embeddings.py`

Triggers: PDF upload (if enabled), `POST /backfill/embeddings`.

- Input: `title` + `abstract`
- Model: **Ollama nomic-embed-text** (768-dim)
- Output: vector stored on `Paper.embedding`
- Enables vector similarity search via `paper_embeddings` index

Requires: `ollama pull nomic-embed-text`.

---

## Single-Paper Chat — `services/ai.py`

Endpoint: `POST /papers/{id}/chat`

The full `raw_text` (truncated to model limit) is included in context. Model selected per-request:
- **Claude Opus 4.6** — default (personal API key)
- **Claude Work** — enterprise Foundry gateway
- **Ollama** — fully local

System prompt: `prompts/chat_system.txt`.

---

## Figure Extraction & Captioning — `services/figure_extractor.py`

Endpoint: `POST /papers/{id}/figures/extract`

```
PDF from Google Drive → Docling: extract page images + figure regions
  → Caption method (from Settings):
      docling  → Docling structural caption
      ollama   → Ollama llama3.2:3b (prompts/figure_captions.txt)
      claude-vision → Claude Haiku Vision
  → Upload PNG to Google Drive
  → Save Figure node in Neo4j
```

---

## Figure Vision Chat

Endpoint: `POST /papers/{id}/figures/{fig_id}/chat`

Figure PNG retrieved from Google Drive, sent to Claude with the user's question. Uses **Claude Haiku** (vision-capable).

---

## Chapter Detection — `services/book_chapter_parser.py`

Endpoint: `POST /papers/{id}/chapters/detect`

```
Strategy 1: Docling structural chapter detection
Strategy 2: Regex on raw_text headings (if Docling finds nothing)
Strategy 3: Ollama AI (use_ai=true only)
→ Create Chapter nodes
→ Ollama summarises each chapter
```

Chapter chat uses `prompts/chapter_chat_system.txt` with **Claude Haiku**.
Chapter summaries use `prompts/chapter_summary.txt` with **Ollama**.

---

## Affiliation Extraction — `services/pdf_parser.py`

Runs during paper upload when author affiliations are missing.

- Input: `raw_text[:2000]`
- Prompt: `prompts/author_affiliations.txt`
- Model: **Ollama llama3.2:3b**
- Output: author → affiliation mapping → update `Person.affiliation`

---

## Cross-Paper Synthesis — `services/ai.py`

Endpoint: `POST /synthesis`

- Input: `paper_ids` + `question` (+ optional web search)
- Prompt: `prompts/synthesis.txt`
- Model: **Claude Opus 4.6**
- Output: synthesis text

---

## Research Gap Analysis — `services/ai.py`

Endpoint: `POST /research-gaps`

- Input: `topic` + `paper_ids` or `project_id` (+ optional web search)
- Prompt: `prompts/research_gaps.txt`
- Model: **Claude Opus 4.6**
- Output: gap analysis text

---

## Duplicate Detection (Merge Scan) — `routers/merge.py`

Endpoint: `POST /merge/scan`

- Input: all papers (title + doi)
- Finds candidate pairs by string similarity
- Prompt: `prompts/merge_scan.txt`
- Model: **Ollama** or **Claude** (batches of 30 pairs)
- Output: scored duplicate pairs (similarity 0–1 + reason)

---

## Literature Search Keywords — `services/literature_search.py`

`prompts/literature_search_keywords.txt` (or a project's stored keywords) is used to query arXiv, PubMed, and bioRxiv. Results streamed via SSE.

---

## Prompt Templates

All prompts in `prompts/` — loaded fresh on each call, edit without restarting.

| File | Pipeline |
|---|---|
| `summary.txt` | Paper summarisation |
| `topics.txt` | Topic suggestion |
| `chat_system.txt` | Single-paper Q&A |
| `knowledge_chat_system.txt` | Multi-paper knowledge chat |
| `figure_captions.txt` | Figure caption generation |
| `author_affiliations.txt` | Affiliation extraction |
| `claims.txt` | Claim extraction |
| `synthesis.txt` | Cross-paper synthesis |
| `research_gaps.txt` | Research gap analysis |
| `chapter_summary.txt` | Chapter summarisation |
| `chapter_chat_system.txt` | Chapter Q&A |
| `literature_search_keywords.txt` | Default literature search keywords |
| `merge_scan.txt` | Duplicate detection |
