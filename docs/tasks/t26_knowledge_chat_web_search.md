# T26 — Knowledge Chat with Web Search

**Phase:** 7 — Discovery & Intelligence
**Depends on:** Web search service from T22-web-search (already implemented in `backend/services/web_search.py`)
**Touches:** `backend/services/ai.py`, `backend/routers/knowledge_chat.py` (if it exists, else find the streaming endpoint), `frontend/src/` (minor — status indicator)

## Goal
The knowledge chat (cross-library chat) can already synthesise across your paper collection. This task adds web search so you can ask "what's new in this area since the papers I have?" and Claude will search the web for context beyond your library.

---

## Current state
`knowledge_chat_stream()` in `backend/services/ai.py` builds a system prompt from all your papers and streams a response. It does **not** use tools — it's a plain streaming call.

## Approach: pre-search pass before streaming

Adding tools to a streaming response is complex (tool_use blocks arrive mid-stream, requiring a secondary call). Instead:

1. **Pre-search pass** (non-streaming, fast): Run Claude Haiku on the user's question to generate 1–3 web search queries, execute them, and collect results.
2. **Inject results** into the knowledge chat system prompt as an extra `## Recent Web Context` section.
3. **Stream** the final answer as before — same SSE path, no breaking changes.

This is simple, robust, and keeps latency low because the pre-search runs in parallel with any UI "Searching…" indicator.

---

## Backend changes — `backend/services/ai.py`

### New helper: `_generate_search_queries`

```python
def _generate_search_queries(question: str, history: list[dict]) -> list[str]:
    """
    Use Claude Haiku to extract up to 3 search queries from the user's question.
    Returns [] if the question is clearly answerable from library context alone
    (e.g. 'summarise paper X', 'what do my papers say about Y').

    Prompt: "Given this research question, suggest up to 3 web search queries
    that would find relevant recent papers, blog posts, or news. If no web
    search is needed (the question is about the user's own library), return [].
    Return JSON: {\"queries\": [\"...\", \"...\"]}
    Question: {question}"
    """
```

### New helper: `_fetch_web_context`

```python
def _fetch_web_context(question: str, history: list[dict]) -> str:
    """
    Runs _generate_search_queries(), executes each via search_web(),
    formats results with format_results_for_prompt().
    Returns empty string if no queries generated or all searches fail.
    """
```

### Modify `knowledge_chat_stream`

```python
def knowledge_chat_stream(
    question: str,
    history: list[dict],
    papers: list[dict],
    model: str = "claude",
    use_web: bool = True,          # NEW param — default True
) -> Any:
    ...
    # NEW: pre-search
    web_context = ""
    if use_web:
        try:
            web_context = _fetch_web_context(question, history)
        except Exception as exc:
            log.warning("Knowledge chat web pre-search failed (non-fatal) | %s", exc)

    papers_block = "\n\n".join(_paper_block(p) for p in papers)
    system = _load_prompt("knowledge_chat_system.txt").format(papers_block=papers_block)

    # Inject web context if available
    if web_context:
        system += f"\n\n## Recent Web Context\n{web_context}"

    # Rest unchanged — stream as before
    ...
```

### Update `prompts/knowledge_chat_system.txt`

Add one line after the existing instructions:
```
If ## Recent Web Context is present below, use it to supplement your library knowledge with current information from the web.
```

---

## SSE streaming event for UI feedback (optional but recommended)

In the streaming endpoint, emit a special event before starting the stream:

```python
# In the route handler, before streaming:
if use_web:
    yield f"data: {json.dumps({'type': 'status', 'text': 'Searching the web...'})}\n\n"
web_context = _fetch_web_context(question, history)
yield f"data: {json.dumps({'type': 'status', 'text': ''})}\n\n"  # clear status
# then start the Claude stream
```

This requires finding the SSE route (likely in `backend/routers/knowledge_chat.py` or similar).

---

## Frontend changes

### Find the knowledge chat streaming component

Search for the component that renders the knowledge/library chat (likely in `frontend/src/pages/` or a `KnowledgeChat` component). Add:

- Listen for `type: "status"` SSE events and display `text` in a small status line below the input:
  ```
  🔍 Searching the web...
  ```
  Clear it when an empty status event arrives or the first content token appears.

If the SSE parsing is already in place, this is a small addition to the event handler.

---

## Done when
- [ ] `knowledge_chat_stream` accepts `use_web` parameter (default `True`)
- [ ] Pre-search runs before streaming and injects results into system prompt
- [ ] Question clearly about own library (e.g. "what do my papers say?") skips web search
- [ ] Chat still streams correctly with web context injected
- [ ] UI shows "Searching the web…" indicator while pre-search runs
- [ ] `use_web=False` still works (library-only mode)
- [ ] No latency regression when web context is empty (fast skip)
