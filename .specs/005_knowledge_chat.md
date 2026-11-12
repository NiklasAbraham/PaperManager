# Knowledge Chat

A technical reference for how the Knowledge Chat pipeline works end-to-end.

---

## Overview

Endpoint: `POST /knowledge-chat/stream` (SSE)

When you send a message, the backend runs a multi-phase pipeline:

```
1. Parse @mentions          →  targeted graph retrieval
2. Fetch context papers      →  hybrid vector + recency retrieval
3. Enrich with notes/convs   →  attach your notes and past conversation excerpts
4. Build token budget        →  estimate context size, route model if needed
5. Agentic tool-use loop     →  Claude calls run_cypher / semantic_search as needed
6. Stream final answer       →  every model round streamed to the frontend via SSE
7. Persist to graph          →  message saved with its tool trace, conversation updated
```

The frontend displays each scope step and tool call as a row above the answer as it arrives (see "Tool trace").

---

## Interface

`frontend/src/pages/KnowledgeChat.tsx`, components in `frontend/src/components/kchat/`. The layout follows the
thesis desk (a local Claude Code chat the concept and structure cards were first built for), in the app's light violet:

| Part | Component | What it does |
|---|---|---|
| Conversation list | `ConversationList.tsx` | Newest first, search over titles, `+ New`, rename and delete on hover; forks nested under the conversation they came from |
| Transcript | `KnowledgeChat.tsx` | Reading-width column; questions in a tinted bubble; the tool trace above each answer; under each answer the Sources row, the papers that were in context, `✦ Visualise`, `copy`, and `retry` on a failed or stopped last answer |
| Tool trace | `ToolCall.tsx`, `types.ts` | One collapsed row per scope step and tool call (label, one-line summary of the input, count, status dot); expanded: the Cypher query or input JSON, the result preview, paper chips, figure thumbnails, web links. Prose the model wrote before a tool call (`interim`) shows as a muted line between the rows. `applyEvent()` folds the stream into text + trace |
| Sources | `sources.ts`, `TurnSources.tsx` | `answerSources()` merges per paper id what the answer did with it: cited (a `/paper/<id>` link in the text), read (`load_full_text`), figures, attached, found (returned by `semantic_search` / `run_cypher`); ranked in that order, 10 chips then `+N`, chips are links to `/paper/<id>` (click opens the preview, Ctrl/Cmd-click the page). Then web pages and the number of searches. Scope papers are not sources (they are under "N in context") |
| Branch lane | `BranchLane.tsx` | A git-style line beside the transcript: a dot per question, a curve where a strand was forked; hover a stretch to see its question, click a knob to open a strand |
| Context strip | `KnowledgeChat.tsx` | Tokens used of the context window, split into system prompt, papers, history, question and answer; unfolds to the papers in context |
| Composer | `Composer.tsx` | `@project:` / `@topic:` / `@tag:` / `@paper:` / `@person:` / `@user:` autocomplete, the mentions shown as scope chips, `+ paper` to attach library papers by id, web and concept toggles, model choice, Stop |
| Preview pane | `PreviewPane.tsx` | Opens a cited paper (title, year, venue, summary, abstract, figures, `Open in library`, `PDF`) or a figure, beside the chat |
| Answer rendering | `Markdown.tsx` | GFM, KaTeX (`\(` / `\[` normalised to `$`, rendered as HTML and MathML), highlighted code, library figures (`/papers/<id>/figures/<fid>/image` only), figure strips, `[title](/paper/<id>)` citations as chips that open the preview, ```` ```concept ```` and ```` ```structure ```` blocks as cards. Works without the chat page around it (the single-paper chat in `ChatPanel.tsx` uses it): images then open in a new tab and citations are plain links |
| Copy as TeX | `copyTex.ts` | One document-level copy listener: a selection holding rendered maths copies as `$...$` / `$$...$$` from KaTeX's MathML annotation |
| Figure strips | `figureStrips.ts`, `FigureStrip.tsx`, `strip.css` | A rehype plugin wraps three or more images in a row (consecutive lines, or paragraphs with only an image) into one strip; `![title](/papers/<id>/figures/*)` alone on a line becomes a strip of all that paper's figures (`GET /papers/{id}/figures`). Thumbnails are labelled by the part of the alt texts that differs; a click opens a lightbox (←/→, Esc, `beside the chat`) |

Papers attached in the composer travel as `paper_ids` on the request and are always put first in context.

## Concept cards

The per-paper concept pipeline (`services/concepts.py`, `prompts/concept_*.txt`) also runs on answers
(`services/chat_concepts.py`): every `## ` section of the answer plays the part of a PDF page, detection picks at most
four ideas (one per type first), and a spec is generated for each, with the pipeline's model routing (Claude Code on the
subscription when the user may use it, otherwise the API key). The cards are stored on the `Message` node
(`concepts_json`, `concepts_status`, `concepts_error`) with the index of the section they explain, and render at the end of
that section. `sections.ts` mirrors the backend's `split_sections` (fence-aware), and both are tested.

- `✦ Visualise` under an answer, or `concepts · auto` in the composer for every answer longer than a few paragraphs, calls
  `POST /knowledge-chat/messages/{id}/visualise`; the job runs in a background thread and the page polls
  `GET /knowledge-chat/messages/{id}/concepts`. A job lost to a restart reads as failed and can be started again.
- An animation or graph that fails in the browser shows `fix`, which sends the error to
  `POST /knowledge-chat/messages/{id}/concepts/{index}/repair` (the pipeline's repair prompt).
- The model may also write a card itself as a ```` ```concept ```` block with an inline spec (formula, graph, 2d-text).
- Animations run in the sandboxed iframe of `components/concepts/` (no same-origin, no network) with pause, 0.5×, 1×, 2×
  and replay; the sandbox runs a virtual clock so every spec obeys the speed.

## 3D structures

A ```` ```structure ```` block renders a 3Dmol.js card (`components/kchat/structure/`, ported from the desk). 3Dmol.js is
vendored in `frontend/public/vendor/3dmol/` (BSD-3-Clause) and loaded on the first structure; nothing is fetched from a
CDN. The block holds a PDB id (`6VXX`), `AF-<UniProt>` for an AlphaFold DB model, or a JSON spec (`types.ts` documents
every field) with models (`pdb`, `afdb`, `ccd` for an RCSB chemical component, `pubchem` for a PubChem CID, or inline
`data` + `format` sdf / mol2 / pdb / cif; chains, colour by chain / spectrum / pLDDT / role, `chainColors`, opacity,
superposition by Cα with `align` `to` / `chain` / `toChain` / `offset`), highlights (model, chain, residues, residue
names, atoms, het groups; cartoon, sticks, spheres or surface; `hidden`), `focus`, a caption, multi-model entries
played as frames (`frames`) and `distances` drawn as a strip chart under the player. A small molecule (SDF / MOL2) is
made one het group (`asLigand()`: chain L, residue 1, resn from a 1-3 character title, else LIG). A spec that parses
but is invalid shows an error card. The card has surface, dim, spin, reset,
a taller stage, fullscreen and PNG; hovering names the residue and B-factor, clicking collects residues into a copyable
list; pLDDT colouring shows its legend.

Coordinates come from `GET /knowledge-chat/structures?pdb=<id>`, `?afdb=<accession>`, `?ccd=<code>` or
`?pubchem=<cid>` (`services/structures.py`): the RCSB mmCIF, the AlphaFold DB model named by its prediction API, the
RCSB ideal SDF of a chemical component (title line set to the code), or PubChem's 3D SDF, fetched once and cached in
`/data/structures` (`STRUCTURE_CACHE_DIR` to change). Ids are validated before any request; inline `data` needs none.

## Strands (forks)

Hovering a question offers `⑂ edit` (copy the conversation up to just before it and put its text back in the composer)
and `⑂ strand` (copy it up to that answer and continue there). `POST /knowledge-chat/conversations/{id}/fork` with
`keep` (questions to inherit) copies the messages, their paper links and concept cards into a new conversation with
`parent_id`, `fork_at` and `fork_kind`; the first question asked in it becomes its `branch_label`. The original is never
changed. Deleting a parent leaves its strands as top-level conversations.

## Tool trace, stop and retry

Every step event carries, besides `kind` (`scope`, `attach`, `cypher`, `search`, `fulltext`, `figures`, `web`),
`description`, `cypher` and `count`: `tool` (`mention`, `attach`, `run_cypher`, `semantic_search`, `load_full_text`,
`list_figures`, `WebSearch`, `web_presearch`), `input` (the arguments as the model sent them), `result` (what went back
to the model, cut at 4,000 characters), `is_error`, `papers` (the library papers the call touched or returned, at most
30; for `run_cypher` read from rows with a paper id and title), `links` (web steps) and `figures` (`list_figures`).
Built in `execute_library_tool()` (`services/ai.py`), so the API-key loop and the Claude Code path share them.

`{"type": "interim"}` says the text streamed since the previous interim was prose written before a tool call, not the
answer: the page moves it into the trace as `{kind: "text", text}` and starts the answer afresh. The router stores the
answer's steps in order (scope and attach steps too, not the two filler steps "Parsing @mentions…" and "Sending to
Claude…", which are still sent for older pages) as `steps_json` on the assistant `Message`, at most ~200 KB (result
previews dropped oldest first); `GET .../messages` returns them as `steps`, forks copy them.

Stop: the router keeps a `threading.Event` per running question (`_running`); `POST /knowledge-chat/stop` sets it, the
producer stops reading the model between two events, closes the model generator, saves the text so far with
`stopped: true` (or marks the question `answer_error: "Stopped."` when nothing was written) and sends `done` with
`stopped`. A dropped connection without Stop still lets the answer finish and be saved. Retry: `retry_of` makes the
router call `delete_last_turn()` (the question and every later non-system message, only if no later question exists)
before answering again; otherwise the stream sends one error.

## Shared with the desk

The chat machinery is ported from Niklas's desk chat and kept close to it so the two can be synced file by file:
`Markdown.tsx` (desk `Markdown.tsx`), `copyTex.ts` (desk `copyTex.ts`, unchanged but for `replaceMath` exported),
`structure/*` (desk `components/structure/*`; PaperManager adds `afdb`, `ccd`, `pubchem`, inline `data` and the pLDDT
legend instead of repository paths), `ConceptBlock` / `ConceptCard` and `components/concepts/` (desk
`components/concepts/`, same speeds 0.25×-2×), `BranchLane.tsx` (desk `BranchLane.tsx`), `ToolCall.tsx` (desk
`Chat.tsx` `ToolCall`), `TurnSources.tsx` and `sources.ts` (desk `Chat.tsx` `TurnSources`, `sources.ts`). Figure
strips are described in the desk's prompt but built here first. Not shared: anything private to the desk (its modes,
tools, inbox, calendar, permissions, subagents, uploads, dictation, token ledger).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/knowledge-chat/stream` | Ask (SSE: `step`, `status`, `context`, `conversation`, `token`, `interim`, `done`, `error`); `retry_of` = id of the last question to replace |
| POST | `/knowledge-chat/stop` | `{user_message_id}`: stop that running answer; the part written so far is saved with `stopped` |
| GET | `/knowledge-chat/conversations` | Knowledge Chat conversations (per-paper chats are listed on their paper) |
| PATCH / DELETE | `/knowledge-chat/conversations/{id}` | Rename / delete |
| GET | `/knowledge-chat/conversations/{id}/messages` | Messages with cited papers and concept cards |
| POST | `/knowledge-chat/conversations/{id}/compact` | Sliding-window compaction |
| POST | `/knowledge-chat/conversations/{id}/fork` | New strand |
| POST / GET | `/knowledge-chat/messages/{id}/visualise`, `.../concepts` | Concept cards for an answer |
| POST | `/knowledge-chat/messages/{id}/concepts/{index}/repair` | Regenerate one card with its error |
| GET | `/knowledge-chat/structures` | Cached RCSB / AlphaFold DB / CCD / PubChem coordinates |

All routes require a login.

---

## Phase 1 — @mention Parsing

Scope context explicitly by typing `@type:value` anywhere in your question:

| Syntax | What it fetches |
|---|---|
| `@tag:interpretability` | All papers tagged "interpretability" (up to 20) |
| `@topic:transformers` | Papers linked to Topic nodes containing "transformers" |
| `@project:thesis` | Papers in any project whose name contains "thesis" |
| `@paper:attention-is-all` | Papers whose title contains "attention is all" |
| `@person:lecun` | Papers authored by or involving people named "lecun" |
| `@blog:distill` | Blog posts from a blog whose name contains "distill" |

Multiple `@mentions` can be combined. Each resolves independently; results are merged and deduplicated by paper ID.

---

## Phase 2 — Hybrid Retrieval (no @mentions)

When no `@mention` is present, the backend runs **hybrid retrieval**:

### Primary: Vector Similarity Search
Your question is embedded with `nomic-embed-text` (768-dim, local Ollama) and matched against the `paper_embeddings` vector index in Neo4j using cosine similarity. Papers with `score > 0.55` are included (up to 10).

### Secondary: Recency Fallback
The 10 most recently added papers are fetched as a fallback (fills gaps when the vector index is cold, e.g. papers uploaded before embeddings were generated).

### Blog Posts
The 5 most recently imported blog posts are always appended.

All three sets are deduplicated by ID before being sent to Claude.

> **To get full value from hybrid retrieval**: run `POST /backfill/embeddings` once from the Settings page to embed all existing papers. New uploads are embedded automatically.

---

## Phase 3 — Context Enrichment

For each retrieved paper, the backend attaches:
- Your **personal note** for that paper (if any)
- Excerpts from **previous Knowledge Chat conversations** that discussed that paper — either the compacted working-memory block or the last 3 exchanges verbatim

This means Claude knows not just what the paper says but what *you* have already concluded about it.

---

## Phase 4 — Token Budget and Model Routing

Before calling Claude, the backend estimates total context in tokens:

```
total = system_prompt + all_paper_texts + conversation_history + your_question
```

**If `total > 40 000 tokens`** and you are using the personal Claude key: the request is automatically routed to `claude-opus-4-6` instead of `claude-sonnet-4-6`. Opus handles multi-document synthesis at large contexts substantially better.

Threshold configurable in **Settings → Knowledge Chat → Route large context to Opus**.

---

## Phase 5 — Agentic Tool-Use Loop

This is the core of inference. Claude receives:
- A structured system prompt (`prompts/knowledge_chat_system.txt`): an expert register, how the chat renders maths,
  citations (`[title](/paper/<id>)`), figures, ```` ```concept ```` and ```` ```structure ```` blocks, and when to use them
- The complete Neo4j schema
- The pre-loaded paper context block (each paper with its `id` and year)
- Four tools: `run_cypher`, `semantic_search`, `load_full_text` and `list_figures` (a paper's extracted figures with
  their image URLs, to embed one in the answer)

The `litellm` model gets one completion through the LiteLLM proxy with the same system prompt, without tools. The
`claude-code` model runs on the Claude subscription through the Agent SDK with the same library tools (and WebSearch).

Claude is instructed to **state its retrieval intent in prose before calling any tool** (ReAct-style planning) to reduce redundant tool calls.

### Tool: `run_cypher`
Claude can run read-only Cypher queries against your live graph.

**Hard constraints enforced by the backend:**
- Write operations (`CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`) blocked with `403`
- `LIMIT 50` enforced — results capped even if Claude omits the clause
- `raw_text` stripped from all results (too large)
- Safety regex scans for write keywords before execution

**What Claude uses it for:**
- Count papers by topic, author, year
- Find co-authorships, citation chains
- Look up specific claims or annotations
- Check graph structure not in the pre-loaded context

Frontend: every `run_cypher` call appears as a collapsible step card showing the exact Cypher query and rows returned.

### Tool: `semantic_search`
Claude can request a vector similarity search against `paper_embeddings`.

**Requires**: `nomic-embed-text` running in Ollama.

**What Claude uses it for:**
- "Find papers similar to this concept" when keyword search misses synonyms
- Expanding context beyond pre-loaded papers when it suspects a gap
- Cross-lingual or paraphrase-style retrieval

Results include title, year, abstract, summary, and cosine score (threshold: `0.60`).

Frontend: appears as a step card labelled `[vector search] <query>`.

The loop continues until Claude returns `stop_reason != "tool_use"`. An infinite-loop guard breaks if a round produces no actionable tool results.

---

## Phase 6 — Final Answer Streaming

Every model round is one streamed request (`_stream_round()`, the only place the API-key path calls the model; it
returns the final message with its `usage`). Text reaches the browser as it is written; when a round ends in tool
calls, the router is told with `interim` (see "Tool trace") and the tools run. At most 8 rounds; the last one is sent
with `tool_choice: none`, so the model has to answer. Before, a question without tool calls was asked twice (once to
check for tool use, once to stream) and an answer after tool calls was chunked from a finished text.

---

## Phase 7 — Persistence

After the answer is complete:
- User message + assistant answer saved as `Message` nodes in Neo4j; the answer carries its tool trace (`steps_json`) and, if stopped, `stopped: true`
- Both messages linked to the paper IDs used as context
- Conversation auto-created on first turn (title = first 60 chars of your question)

---

## Conversation Compaction

Long conversations are compacted via **Settings → compact button per conversation** or `POST /knowledge-chat/conversations/{id}/compact`.

**Strategy:**
1. Claude Haiku extracts structured working memory from older messages:
   ```json
   {
     "papers_discussed": ["Attention Is All You Need", ...],
     "key_findings": ["BERT outperforms GPT on GLUE by 7.4 points", ...],
     "open_questions": ["Does scaling override architecture choice?"],
     "decisions": ["Focus thesis on sparse attention mechanisms"]
   }
   ```
2. Claude Haiku writes a 3–5 sentence prose summary of what was concluded
3. The last N messages (default 6, configurable) are kept verbatim
4. Older messages replaced with a single `system` message containing the JSON block + prose summary

Specific paper titles, numbers, and claims are preserved in the structured JSON even after compaction.

---

## Claims in Context

`Claim` nodes (`(Paper)-[:HAS_CLAIM]->(Claim)`) are **not injected directly** into the Knowledge Chat context block — doing so would bloat the context. Claude pulls them on demand via `run_cypher`:

```cypher
MATCH (p:Paper {id: "..."})-[:HAS_CLAIM]->(c:Claim)
RETURN c.text, c.claim_type, c.confidence
LIMIT 20
```

---

## Settings That Affect Inference

| Setting | Location | Effect |
|---|---|---|
| Default model | Settings → Knowledge Chat | Starting model for all chats |
| Web search | Settings → Knowledge Chat | Enables Anthropic web tool |
| Opus threshold | Settings → Knowledge Chat | Token count above which Sonnet → Opus |
| Compaction window | Settings → Knowledge Chat | How many messages stay verbatim |
| Extract claims on upload | Settings → Inference | Haiku extracts claims from each new paper |
| Generate embeddings on upload | Settings → Inference | Whether nomic-embed-text runs at upload time |

---

## One-Time Setup Checklist

1. `ollama pull nomic-embed-text` — required for vector search
2. Restart the backend — `paper_embeddings` vector index created on startup
3. **Settings → Library Maintenance → Generate embeddings** — backfill existing papers
4. **Settings → Library Maintenance → Extract claims** — optional claim backfill

---

## Common Misconceptions

- Claude does **not** read full PDF text during chat — it reads structured summary, abstract, your note, and any data it retrieves via tool calls
- Cypher queries run **live** against your graph — results are always current
- Pre-loaded context papers are a **first-pass guess** — Claude expands via tool calls if needed
- Model routing happens **per request** — a single session can switch models mid-conversation
