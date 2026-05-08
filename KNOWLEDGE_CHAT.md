# Knowledge Chat — How It Works

A technical reference for how every piece of the Knowledge Chat pipeline fits together and what is actually running when you send a message.

---

## Overview

When you ask a question, the backend runs a **multi-phase pipeline**:

```
1. Parse @mentions          →  targeted graph retrieval
2. Fetch context papers      →  BM25 fulltext + vector similarity fallback
3. Enrich with notes/convs   →  attach your notes and past conversation excerpts
4. Build token budget        →  estimate context size, route model if needed
5. Agentic tool-use loop     →  Claude calls run_cypher / semantic_search as needed
6. Stream final answer       →  tokens streamed to frontend via SSE
7. Persist to graph          →  message saved, conversation updated
```

Everything runs over **Server-Sent Events** (SSE). The frontend displays each phase as a step card as it arrives.

---

## Phase 1 — @mention parsing

You can scope context explicitly by typing `@type:value` anywhere in your question:

| Syntax | What it fetches |
|---|---|
| `@tag:interpretability` | All papers tagged "interpretability" (up to 20) |
| `@topic:transformers` | Papers linked to Topic nodes containing "transformers" |
| `@project:thesis` | Papers in any project whose name contains "thesis" |
| `@paper:attention-is-all` | Papers whose title contains "attention is all" |
| `@person:lecun` | Papers authored by or involving people named "lecun" |
| `@blog:distill` | Blog posts from a blog whose name contains "distill" |

Multiple `@mentions` can be combined. Each resolves independently and results are merged and deduplicated by paper ID.

---

## Phase 2 — Hybrid retrieval (no @mentions)

When you ask a plain question without any `@mention`, the backend runs **hybrid retrieval**:

### Primary: vector similarity search
Your question is embedded with `nomic-embed-text` (768-dim, local Ollama) and matched against the `paper_embeddings` vector index in Neo4j using cosine similarity. Papers with `score > 0.55` are included (up to 10).

### Secondary: recency fallback
The 10 most recently added papers are fetched as a fallback to fill gaps when the vector index is cold (e.g. papers uploaded before embeddings were generated).

### Blog posts
The 5 most recently imported blog posts are always appended.

All three sets are deduplicated by ID before being sent to Claude.

> **To get full value from hybrid retrieval**, run `POST /backfill/embeddings` once from the Settings page to embed all existing papers. New uploads are embedded automatically.

---

## Phase 3 — Context enrichment

For each retrieved paper, the backend attaches:
- Your **personal note** for that paper (if any)
- Excerpts from **previous Knowledge Chat conversations** that discussed that paper — either the compacted working-memory block or the last 3 exchanges verbatim

This means Claude knows not just what the paper says, but what *you* have already concluded about it.

---

## Phase 4 — Token budget and model routing

Before calling Claude, the backend estimates the total context in tokens:

```
total = system_prompt + all_paper_texts + conversation_history + your_question
```

**If `total > 40 000 tokens` and you are using the personal Claude key**: the request is automatically routed to `claude-opus-4-6` instead of `claude-sonnet-4-6`. Opus handles multi-document synthesis at large contexts substantially better.

You can change the threshold in **Settings → Knowledge Chat → Route large context to Opus**.

---

## Phase 5 — Agentic tool-use loop

This is the core of inference. Claude receives:
- A structured system prompt with your profile (Tübingen, math/CS/physics, expert)
- The complete Neo4j schema
- The pre-loaded paper context block
- Two tools it can call: `run_cypher` and `semantic_search`

Claude is instructed to **state its retrieval intent in prose before calling any tool** (ReAct-style planning). This reduces redundant tool calls.

### Tool: `run_cypher`
Claude can run any read-only Cypher query against your live graph.

**Hard constraints enforced by the backend:**
- Write operations (`CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`) are blocked with a `403` error
- `LIMIT 50` is enforced — results are capped even if Claude omits the clause
- `raw_text` is stripped from all results (too large)
- A safety regex scans for write keywords before execution

**What Claude uses it for:**
- Count papers by topic, author, year
- Find co-authorships, citation chains
- Look up specific claims or annotations
- Check graph structure the pre-loaded context doesn't contain

**Frontend**: every `run_cypher` call appears as a collapsible step card showing the exact Cypher query and the number of rows returned.

### Tool: `semantic_search`
Claude can request a vector similarity search against `paper_embeddings` directly.

**Requires**: `nomic-embed-text` running in Ollama (`ollama pull nomic-embed-text`).

**What Claude uses it for:**
- "Find papers similar to this concept" when keyword search would miss synonyms
- Expanding context beyond the pre-loaded papers when it suspects a gap
- Cross-lingual or paraphrase-style retrieval

Results include title, year, abstract, summary, and cosine score. Score threshold: `0.60`.

**Frontend**: appears as a step card labelled `[vector search] <query>`.

The loop continues until Claude returns `stop_reason != "tool_use"`. An infinite-loop guard breaks if a round produces no actionable tool results.

---

## Phase 6 — Final answer streaming

After all tool calls are done:
- **If no tool calls were made**: Claude's final answer is streamed token by token (true SSE streaming, low latency)
- **If tool calls were made**: the final answer is already computed (non-streaming API is used in the agentic loop), so it is chunked at 40 characters per SSE event to simulate streaming

---

## Phase 7 — Persistence

After the answer is complete:
- User message + assistant answer saved as `Message` nodes in Neo4j
- Both messages linked to the paper IDs that were used as context
- Conversation created automatically on the first turn (title = first 60 chars of your question)

---

## Conversation compaction

Long conversations are compacted via **sliding-window memory** (Settings page → "Compact" button per conversation, or manually via `POST /knowledge-chat/conversations/{id}/compact`).

The compaction strategy:
1. Claude Haiku extracts **structured working memory** from the older messages:
   ```json
   {
     "papers_discussed": ["Attention Is All You Need", ...],
     "key_findings": ["BERT outperforms GPT on GLUE by 7.4 points", ...],
     "open_questions": ["Does scaling override architecture choice?"],
     "decisions": ["Focus thesis on sparse attention mechanisms"]
   }
   ```
2. Claude Haiku writes a **3–5 sentence prose summary** of what was concluded
3. The last `N` messages (default 6, configurable in Settings) are kept verbatim
4. All older messages are replaced with a single `system` message containing the JSON block + prose summary

This means specific paper titles, numbers, and claims are not lost — they live in the structured JSON even after compaction.

---

## Claims in context

Every paper can have `Claim` nodes attached via `(Paper)-[:HAS_CLAIM]->(Claim)`. Claims are extracted at upload time using Claude Haiku (enabled by default, toggle in **Settings → Inference**).

Claims are **not currently injected directly into the Knowledge Chat context block** — but Claude can query them via `run_cypher`:
```cypher
MATCH (p:Paper {id: "..."})-[:HAS_CLAIM]->(c:Claim)
RETURN c.text, c.claim_type, c.confidence
LIMIT 20
```

This is intentional: injecting all claims would bloat the context. Claude pulls them on demand when it needs evidence-level detail.

---

## Settings that affect inference

| Setting | Location | Effect |
|---|---|---|
| Default model | Settings → Knowledge Chat | Starting model for all chats |
| Web search | Settings → Knowledge Chat | Enables Anthropic web tool (if supported) |
| Opus threshold | Settings → Knowledge Chat | Token count above which Sonnet → Opus |
| Compaction window | Settings → Knowledge Chat | How many messages stay verbatim |
| Extract claims on upload | Settings → Inference | Haiku extracts claims from each new paper |
| Claims model | Settings → Inference | Which model runs claim extraction |
| Generate embeddings on upload | Settings → Inference | Whether `nomic-embed-text` runs at upload time |

---

## One-time setup checklist

1. `ollama pull nomic-embed-text` — required for vector search to work
2. Restart the backend — the `paper_embeddings` vector index is created on startup
3. **Settings → Library Maintenance → Generate embeddings** — backfill embeddings for existing papers (one-time, takes ~1–2 min per 100 papers depending on Ollama speed)
4. **Settings → Library Maintenance → Extract claims** — optional backfill for claims on existing papers

After these steps, every question benefits from hybrid semantic retrieval and Claude can use `semantic_search` as a tool during inference.

---

## What is NOT happening (common misconceptions)

- Claude does **not** read full PDF text during chat — it reads the structured summary, abstract, your note, and any data it retrieves via tool calls
- Cypher queries run **live against your graph** — results are always current, not cached from upload time
- The pre-loaded context papers are a **first-pass guess** at relevance — Claude expands them via tool calls if needed
- Model routing happens **per request**, not per session — a long conversation with many papers loaded can switch models mid-session
