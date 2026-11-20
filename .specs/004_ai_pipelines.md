# AI Pipelines

All AI calls, which models they use, and where they run in the code.

---

## Models

| Model | Provider | Used for |
|---|---|---|
| `claude-opus-4-6` | Anthropic | Paper summarisation, single-paper chat, knowledge chat, cross-paper synthesis, research gap analysis |
| `claude-haiku-4-5-20251001` | Anthropic | Abstract extraction, reference extraction, topic suggestion, claim extraction, chapter summarisation, conversation compaction, figure captioning (claude-vision mode) |
| `llama3.2:3b` | Ollama (local) | Metadata extraction (layer 2), tag suggestion, chapter detection, figure captions (default), affiliation extraction, Cypher assist, merge duplicate scan |
| `BAAI/bge-small-en-v1.5` (default of `EMBED_MODEL`) | local, `transformers` on the CPU | Embedding vectors of titles and abstracts: library semantic search, the paper feed, similar papers, the conference explorer (see "Embeddings and the vector store") |
| `LITELLM_EMBED_MODEL` (empty = off) | LiteLLM proxy | Legacy `Paper.embedding` vector used by the knowledge chat's semantic tool |

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

## Embeddings and the vector store — `services/vectorstore/`, `services/conferences/embedder.py`

No language-model API is involved. `embedder.py` loads one Hugging Face model per id (`transformers` + `torch`, CPU,
`trust_remote_code=False`) and embeds a text with the model's document prefix, truncation at 256 tokens, CLS or mean
pooling and L2 normalisation. The model comes from `vectorstore/model_config.py`:

- `EMBED_MODEL` (default `BAAI/bge-small-en-v1.5`, 384-dim, CLS pooling); dimension, pooling and prefixes are known for
  a few models (`KNOWN`: bge, e5, MiniLM, MPNet, SPECTER2, `J0nasW/sciembed-full`), any other model needs `EMBED_DIM`
  (and `EMBED_POOLING`, prefixes).
- `CONFERENCE_EMBED_MODEL` for the conference explorer's saved vectors, read first by that role; empty follows
  `EMBED_MODEL`.
- What is embedded for a paper: title, a newline, then the abstract (or the cleaned summary), cut to 1,500 characters
  (`semantic.paper_text`, `TEXT_FORMAT = "title-abstract-1"`).

Consumers: library search (`library` namespace, hybrid and semantic modes, `.specs/012_search.md`), the optional paper
feed (`feed`, `feed_library`, and a numpy logistic regression on top, `.specs/018_paper_feed.md`), similar papers
(`POST /search/similar`, MCP `find_similar_papers`, `papers_like`; `.specs/020_similar_search.md`) and the conference
explorer. Each namespace stores the model it was built with and is *stale* when the configured model differs: search
then falls back to keywords and the namespace is rebuilt in the background (or adopted from a prepared generation made
by `scripts/vectors_export.py` -> `embed_bulk.py` on a GPU machine -> `vectors_import.py`; `vectors_rollback.py` goes
back). Details: `.specs/019_vector_store.md`. `scripts/embedder_benchmark.py` compares models on a library.

### Legacy `Paper.embedding` — `services/embeddings.py`

Triggers: PDF upload when `LITELLM_EMBED_MODEL` is set, `POST /backfill/embeddings`.

- Input: `title` + `abstract` (+ `summary`)
- Model: the LiteLLM embeddings API with `LITELLM_EMBED_MODEL` (empty by default: switched off)
- Output: vector stored on `Paper.embedding`; the Neo4j index `paper_embeddings` is declared with 768 dimensions
- Used only by the knowledge chat's `semantic_search` tool and its retrieval step, which skip it silently when it fails

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

## Project Concept Map — `services/concept_map.py`, `routers/concept_map.py`

Endpoints: `POST /projects/{id}/concept-map/build` (`{force, paper_ids}`; background job, 3 papers in parallel), `GET /projects/{id}/concept-map/status`, `GET /projects/{id}/concept-map` (papers with authors and citation counts, concepts, DISCUSSES rows, aggregated concept relations, CITES edges inside the project).

- Input: title, year, authors, abstract, summary, claims (raw text only if none of these exist), plus the 250 most-used concept names already in the project so the model reuses them
- Prompt: `prompts/concept_map.txt`
- Model: **Gemma** via LiteLLM (240 s timeout: the proxy cold-starts)
- Output: 6–15 concepts (name, aliases, kind, definition, role, what the paper does with it) and typed relations between them, stored as `MapConcept` / `DISCUSSES` / `CONCEPT_LINK` (see data model). Saves are serialised so two papers cannot create the same concept twice.
- Automatic: a sweeper thread (`start_auto_mapping`, every 10 min, `CONCEPT_MAP_AUTO=false` turns it off) maps every project paper without concepts once it has a summary (or is 30 min old), whatever way it arrived; it also resumes builds a restart interrupted. Papers whose extraction timed out are retried on later sweeps, up to 3 attempts (`Paper.concept_map_attempts`); other failures wait for a manual build. At most 2 Gemma calls run at once across all projects (the proxy times out above that).
- Frontend: `/projects/:id/map` — force graph of concepts (colour = kind, size = papers), papers (size = citations), optional authors; filters by author, year, kind, minimum papers per concept; overview list per kind.

## Quick Tour — `services/paper_tour.py`, `routers/paper_tour.py`

Endpoints: `POST /papers/{id}/tour` (background; 503 when the subscription is not set up), `GET /papers/{id}/tour` (cached tour, running flag, last error).

- Input: stored summary, the paper's `MapConcept`s (role + what it does with them), pypdf page texts (≤ 60 pages × 5,000 chars)
- Prompt: `prompts/paper_tour.txt`
- Model: **Sonnet via Claude Code on the subscription only** (`CLAUDE_CODE_OAUTH_TOKEN` + `CLAUDE_CODE_USERS`); no API-key fallback by design
- Output: overview, what to skip, 6–12 stops `{page, title, kind, anchor (verbatim), explanation, concepts}`; anchors are re-located in the page texts (`anchor_found`). Stored as `Paper.tour_json` / `tour_at`.
- Frontend: Tour tab in the paper view; stops are drawn as PDF marks (same mechanism as Concepts), ← / → step through them.

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
| `concept_map.txt` | Project concept map |
| `paper_tour.txt` | Quick tour of a paper |
