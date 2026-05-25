"""Claude and Ollama AI services — summarization and chat."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Generator

import httpx
import anthropic
from config import settings
from services.user_ai_config import get_effective_ai_config
from services.web_search import WEB_SEARCH_TOOL, WEB_SEARCH_TOOL_OLLAMA, search_web

log = logging.getLogger(__name__)

# Prompts live in <project_root>/prompts/ — loaded fresh on every call so
# you can edit them without restarting the backend.
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# Personal Anthropic API — always use the canonical base URL, never the
# ANTHROPIC_BASE_URL env var (which may be set to a corporate proxy with
# surrounding newlines, causing httpx URL validation errors).
_ANTHROPIC_BASE_URL = "https://api.anthropic.com"


def _personal_client() -> anthropic.Anthropic:
    """Return an Anthropic client for the personal API key with SSL settings applied."""
    cfg = get_effective_ai_config()
    api_key = (cfg.get("anthropic_api_key") or "").strip()
    if not api_key:
        raise ValueError("Personal Anthropic key is not configured for this user.")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=_ANTHROPIC_BASE_URL,
        http_client=httpx.Client(verify=_ssl_verify()),
    )


def _work_client() -> anthropic.Anthropic:
    """Return Anthropic work client for the effective user config."""
    cfg = get_effective_ai_config()
    work_key = (cfg.get("anthropic_work_api_key") or "").strip()
    if not work_key:
        raise ValueError("Work Anthropic key is not configured for this user.")
    work_kwargs: dict[str, Any] = {
        "api_key": work_key,
        "http_client": httpx.Client(verify=_ssl_verify()),
    }
    work_base = (cfg.get("anthropic_work_base_url") or "").strip()
    if work_base:
        work_kwargs["base_url"] = work_base
    return anthropic.Anthropic(**work_kwargs)


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


def _ssl_verify():
    """Return the httpx SSL verify value based on settings."""
    if not settings.ssl_verify:
        return False
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return True


def summarize_paper(text: str, title: str = "", custom_instructions: str | None = None) -> str:
    """Return a markdown summary of *text* using Claude.

    If *custom_instructions* is provided it replaces the instructional section of
    the default prompt while still appending the paper title and text automatically.
    Falls back to a short notice if text is empty.
    """
    if not text or not text.strip():
        return "_No text could be extracted from this paper._"

    if custom_instructions and custom_instructions.strip():
        prompt = (
            f"{custom_instructions.strip()}\n\n"
            f"Paper title: {title or '(unknown)'}\n\n"
            f"Paper text:\n{text[:600000]}"
        )
    else:
        prompt = _load_prompt("summary.txt").format(
            title=title or "(unknown)",
            text=text[:600000],
        )

    def _call(client: anthropic.Anthropic, prompt_text: str) -> str | None:
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt_text}],
        )
        if msg.content and msg.stop_reason != "refusal":
            return msg.content[0].text
        log.warning("summarize_paper: stop_reason=%s content=%s", msg.stop_reason, bool(msg.content))
        return None

    # Strategy A: personal API with full text
    result = _call(_personal_client(), prompt)

    # Strategy B: personal API with truncated text (avoids refusals from garbled PDF content)
    if result is None:
        short_prompt = prompt[:20000]
        log.info("summarize_paper: retrying personal API with truncated prompt (%d chars)", len(short_prompt))
        result = _call(_personal_client(), short_prompt)

    # Strategy C: Work API (Palantir gateway) — may have different content policy
    cfg = get_effective_ai_config()
    if result is None and (cfg.get("anthropic_work_api_key") or "").strip():
        log.info("summarize_paper: trying Work API")
        result = _call(_work_client(), prompt)

    if result is None:
        return "_Summary could not be generated (Claude refused the content). The extracted PDF text may contain garbled or problematic characters._"
    return result


def suggest_topics(title: str, abstract: str = "", summary: str = "") -> list[str]:
    """Return a list of research topic names for a paper using Claude Haiku."""
    import json, re

    if not title and not abstract and not summary:
        return []

    context_parts = []
    if abstract:
        context_parts.append(f"Abstract:\n{abstract[:3000]}")
    if summary:
        context_parts.append(f"Summary:\n{summary[:2000]}")
    context = "\n\n".join(context_parts) or "(no abstract or summary available — infer from title only)"

    prompt = _load_prompt("topics.txt").format(title=title or "(unknown)", context=context)

    client = _personal_client()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    # Extract JSON even if Claude wraps it in markdown fences
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return []
    raw = json.loads(match.group())
    return [t.strip() for t in (raw.get("topics") or []) if t.strip()]


def _run_claude_with_tools(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
) -> str:
    """Agentic loop: run Claude with the web_search tool until it stops calling tools."""
    tools = [WEB_SEARCH_TOOL]
    while True:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        if response.stop_reason == "tool_use":
            # Collect tool calls and execute them
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "web_search":
                    query = block.input.get("query", "")
                    max_r = int(block.input.get("max_results", 5))
                    results = search_web(query, max_results=max_r)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(results),
                        }
                    )
            # Feed results back
            messages = list(messages)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            # Final text response
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""


def chat_with_paper(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* about a paper using its full text as context.
    Claude can also search the web for related information."""
    system = _load_prompt("chat_system.txt").format(
        title=paper_title or "(unknown)",
        text=paper_text[:60000],
    )
    client = _personal_client()
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})
    return _run_claude_with_tools(client, "claude-opus-4-6", system, messages)


def chat_with_paper_work(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* using the work/Foundry Anthropic gateway.
    Claude can also search the web for related information."""
    client = _work_client()
    system = _load_prompt("chat_system.txt").format(
        title=paper_title or "(unknown)",
        text=paper_text[:60000],
    )
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})
    return _run_claude_with_tools(client, "claude-opus-4-6", system, messages)


def chat_with_paper_ollama(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* about a paper using Ollama (local LLM).
    Uses tool calling to allow web searches when the model supports it."""
    import ollama

    system = _load_prompt("chat_system.txt").format(
        title=paper_title or "(unknown)",
        text=paper_text[:12000],  # smaller context window for local models
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in (history or []):
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    # Agentic tool-use loop (supported by llama3.1+ models)
    max_iterations = 5  # safety cap
    for _ in range(max_iterations):
        try:
            response = ollama.chat(
                model=settings.ollama_model,
                messages=messages,
                tools=[WEB_SEARCH_TOOL_OLLAMA],
            )
        except Exception as exc:
            # If the model doesn't support tools, fall back to plain chat
            log.warning("Ollama tool-calling failed, falling back to plain chat | %s", exc)
            response = ollama.chat(model=settings.ollama_model, messages=messages)
            return response["message"]["content"].strip()

        msg = response["message"]
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return (msg.get("content") or "").strip()

        # Execute tool calls
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name") == "web_search":
                args = fn.get("arguments") or {}
                query = args.get("query", "")
                max_r = int(args.get("max_results", 5))
                results = search_web(query, max_results=max_r)
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(results),
                    }
                )

    # If we exhausted iterations just return the last content
    return (response["message"].get("content") or "").strip()


# ── Knowledge Chat (cross-library, streaming) ─────────────────────────────────

CONTEXT_WINDOW = 200_000  # Claude Opus 4.6 token limit

# Tool definition for live Cypher queries
CYPHER_TOOL: dict[str, Any] = {
    "name": "run_cypher",
    "description": (
        "Execute a read-only Cypher query against the Neo4j graph database. "
        "Use this to retrieve counts, find specific papers or authors, traverse "
        "relationships, or gather any structured data that is not in the pre-loaded "
        "paper context. Only MATCH/RETURN queries are permitted — no write operations."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A read-only Cypher query. Must use MATCH and RETURN. "
                    "Always include a LIMIT clause. Never use CREATE, MERGE, SET, "
                    "DELETE, DETACH DELETE, or REMOVE."
                ),
            },
            "description": {
                "type": "string",
                "description": "Short human-readable description of what this query fetches (shown in the UI as a reasoning step).",
            },
        },
        "required": ["query", "description"],
    },
}

# Tool definition for semantic vector search
SEMANTIC_SEARCH_TOOL: dict[str, Any] = {
    "name": "semantic_search",
    "description": (
        "Find papers by semantic similarity to a free-text query. "
        "Use this when keyword or tag matching would miss papers that express the same "
        "concept with different terminology (e.g. 'attention mechanism' vs 'scaled dot-product similarity'). "
        "Returns papers ranked by cosine similarity to the embedded query."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text query to embed and match against paper embeddings.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of results to return, between 1 and 20. Defaults to 10.",
            },
            "description": {
                "type": "string",
                "description": "Short human-readable label for the UI reasoning step.",
            },
        },
        "required": ["query", "description"],
    },
}

# Tool definition for loading full paper text on demand
LOAD_FULL_TEXT_TOOL: dict[str, Any] = {
    "name": "load_full_text",
    "description": (
        "Load the complete extracted text of a specific paper from the database. "
        "Use this when the abstract and summary are insufficient to answer the question — "
        "for example, when the user asks about specific methods, equations, experimental "
        "details, pseudocode, or hyperparameters that are only in the full paper body. "
        "paper_id must be a UUID from the pre-loaded paper context. "
        "Call this at most 3 times per query."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": "The UUID id of the paper to load (from the pre-loaded context).",
            },
            "reason": {
                "type": "string",
                "description": "One sentence explaining why the full text is needed.",
            },
        },
        "required": ["paper_id", "reason"],
    },
}

# Regex to block write operations
_CYPHER_WRITE_RE = re.compile(
    r"\b(CREATE|MERGE|SET\s+\w|DELETE|DETACH\s+DELETE|REMOVE|DROP)\b",
    re.IGNORECASE,
)


def _safe_value(v: Any) -> Any:
    """Convert a Neo4j driver value to a JSON-serialisable Python object."""
    try:
        from neo4j.graph import Node, Relationship, Path
        if isinstance(v, Node):
            return {k: _safe_value(val) for k, val in v.items() if k != "raw_text"}
        if isinstance(v, (Relationship, Path)):
            return str(v)
    except ImportError:
        pass
    if isinstance(v, list):
        return [_safe_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _safe_value(val) for k, val in v.items() if k != "raw_text"}
    return v


def _run_cypher_safe(driver: Any, query: str) -> list[dict[str, Any]]:
    """Execute *query* against Neo4j with safety constraints.

    Blocks write operations, enforces a result LIMIT of 50, and strips
    ``raw_text`` properties from every returned value.
    Returns a list of row dicts or a single-element error list.
    """
    if _CYPHER_WRITE_RE.search(query):
        return [{"error": "Write operations are not permitted in Knowledge Chat."}]

    # Append LIMIT if not present
    if not re.search(r"\bLIMIT\s+\d+", query, re.IGNORECASE):
        query = query.rstrip().rstrip(";") + " LIMIT 50"

    try:
        with driver.session() as session:
            result = session.run(query)
            rows = []
            for record in result:
                row = {k: _safe_value(v) for k, v in record.items() if k != "raw_text"}
                rows.append(row)
            return rows[:50]
    except Exception as exc:
        return [{"error": str(exc)}]


def _condense_paper_for_budget(title: str, raw_text: str, target_tokens: int) -> str:
    """Use Claude Haiku to condense *raw_text* to approximately *target_tokens* tokens.

    Preserves equations, numerical results, and method details while dropping
    boilerplate sections (intro motivation, related work, conclusion restatements).
    """
    target_words = max(300, target_tokens * 3)
    prompt = (
        f"Create a dense technical summary of the following paper in approximately {target_words} words.\n"
        "Preserve: all mathematical formulas (in LaTeX notation), specific numerical results and "
        "metrics (AUC, RMSE, accuracy, etc.), method names, architecture details, training "
        "procedures, dataset names and sizes, hyperparameters.\n"
        "Omit: introduction motivation, related work discussion, conclusion restatements, "
        "acknowledgements, references list.\n\n"
        f"Title: {title}\n\nText:\n{raw_text[:80000]}"
    )
    msg = _personal_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=min(4096, target_tokens + 200),
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def knowledge_chat_stream(
    question: str,
    history: list[dict[str, Any]],
    papers: list[dict[str, Any]],
    model: str = "claude",
    use_web: bool = True,
    driver: Any = None,
):
    """Agentic generator for knowledge-chat with live Cypher tool access.

    Yields event dicts consumed directly by the SSE router:
      {"type": "status",  "text": str}
      {"type": "step",    "description": str, "cypher": str|None, "count": int|None}
      {"type": "token",   "text": str}

    The model may call ``run_cypher`` zero or more times before composing
    its final answer.  Each tool call is executed against Neo4j, yielded as
    a step event so the frontend can display the reasoning trace, and its
    results are fed back into the conversation before the next call.
    """
    def _paper_block(p: dict) -> str:
        parts = [f"### {p.get('title', 'Untitled')}"]
        if p.get("abstract"):
            parts.append(f"Abstract: {p['abstract']}")
        if p.get("summary"):
            parts.append(f"Summary: {p['summary']}")
        if p.get("_note"):
            parts.append(f"My note on this paper:\n{p['_note']}")
        if p.get("_conversations"):
            parts.append(f"Previous chat history about this paper:\n{p['_conversations']}")
        return "\n".join(parts)

    # ── Web pre-search ────────────────────────────────────────────────────────
    web_context = ""
    if use_web:
        yield {"type": "status", "text": "Searching the web..."}
        try:
            web_context = _fetch_web_context(question, history)
        except Exception as exc:
            log.warning("Knowledge chat web pre-search failed (non-fatal) | %s", exc)
        yield {"type": "status", "text": ""}

    # ── Build system prompt ───────────────────────────────────────────────────
    papers_block = "\n\n".join(_paper_block(p) for p in papers)
    system = _load_prompt("knowledge_chat_system.txt").replace("{papers_block}", papers_block)
    if web_context:
        system += f"\n\n## Recent Web Context\n{web_context}"

    # ── Select client ─────────────────────────────────────────────────────────
    if model == "claude-work":
        cfg = get_effective_ai_config()
        work_key = (cfg.get("anthropic_work_api_key") or "").strip()
        if not work_key:
            raise ValueError("Work API key not configured for this user.")
        work_base = (cfg.get("anthropic_work_base_url") or "").strip()
        client = anthropic.Anthropic(
            api_key=work_key,
            base_url=work_base or None,
            default_headers={"Authorization": f"Bearer {work_key}"},
            http_client=httpx.Client(verify=_ssl_verify()),
        )
    else:
        client = _personal_client()

    # ── Model routing: use Opus when context is large ────────────────────────
    estimated_ctx = (
        estimate_tokens(system)
        + sum(estimate_tokens(m.get("content", "")) for m in history)
        + estimate_tokens(question)
    )
    if model == "claude" and estimated_ctx > 40_000:
        claude_model = "claude-opus-4-6"
        log.info("knowledge_chat: routing to claude-opus-4-6 (estimated ctx=%d tokens)", estimated_ctx)
    else:
        claude_model = "claude-sonnet-4-6"

    tools = [CYPHER_TOOL, SEMANTIC_SEARCH_TOOL, LOAD_FULL_TEXT_TOOL] if driver is not None else []

    # ── Agentic tool-use loop (non-streaming) ─────────────────────────────────
    # Phase 1: let Claude call run_cypher / semantic_search as many times as
    # it needs.  Each tool call is executed, the result is fed back, and a step
    # event is yielded so the frontend can show the reasoning trace.  The loop
    # exits when Claude returns stop_reason != "tool_use".
    messages: list[dict[str, Any]] = list(history)
    messages.append({"role": "user", "content": question})

    had_tool_calls = False

    while True:
        response = client.messages.create(
            model=claude_model,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=tools if tools else anthropic.NOT_GIVEN,
        )

        if response.stop_reason != "tool_use":
            # No more tool calls — Claude is ready to write its final answer.
            if not had_tool_calls:
                # No tool calls at all → stream for better responsiveness
                with client.messages.stream(
                    model=claude_model,
                    max_tokens=16000,
                    system=system,
                    messages=messages,
                ) as stream:
                    for text in stream.text_stream:
                        yield {"type": "token", "text": text}
            else:
                # Tool calls happened → chunk the already-computed final text
                CHUNK = 40
                final_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                        break
                for i in range(0, len(final_text), CHUNK):
                    yield {"type": "token", "text": final_text[i : i + CHUNK]}
            break

        # ── Execute tool calls ────────────────────────────────────────────────
        had_tool_calls = True
        tool_results: list[dict[str, Any]] = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            desc: str = block.input.get("description", "Running tool")

            if block.name == "run_cypher":
                query: str = block.input.get("query", "")
                rows = _run_cypher_safe(driver, query) if driver else [{"error": "No DB driver available"}]
                yield {
                    "type": "step",
                    "description": desc,
                    "cypher": query,
                    "count": len(rows) if not (len(rows) == 1 and "error" in rows[0]) else None,
                }
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(rows),
                })

            elif block.name == "semantic_search":
                sem_query: str = block.input.get("query", "")
                limit: int = min(int(block.input.get("limit", 10)), 20)
                if driver and sem_query:
                    try:
                        from services.embeddings import embed_text as _embed_text
                        emb = _embed_text(sem_query)
                        with driver.session() as _sess:
                            _result = _sess.run(
                                "CALL db.index.vector.queryNodes('paper_embeddings', $k, $emb) "
                                "YIELD node AS p, score "
                                "WHERE score > 0.60 "
                                "RETURN p.id AS id, p.title AS title, p.year AS year, "
                                "p.abstract AS abstract, p.summary AS summary, score "
                                "ORDER BY score DESC",
                                k=limit,
                                emb=emb,
                            )
                            sem_rows = [
                                {k: _safe_value(v) for k, v in r.items() if k != "raw_text"}
                                for r in _result
                            ][:limit]
                    except Exception as exc:
                        log.warning("semantic_search tool failed | %s", exc)
                        sem_rows = [{"error": str(exc)}]
                else:
                    sem_rows = [{"error": "Vector search unavailable"}]

                yield {
                    "type": "step",
                    "description": desc,
                    "cypher": f"[vector search] {sem_query}",
                    "count": len(sem_rows) if not (len(sem_rows) == 1 and "error" in sem_rows[0]) else None,
                }
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(sem_rows),
                })

            elif block.name == "load_full_text":
                lft_paper_id: str = block.input.get("paper_id", "")
                lft_title = lft_paper_id  # fallback label

                if driver and lft_paper_id:
                    try:
                        with driver.session() as _sess:
                            row = _sess.run(
                                "MATCH (p:Paper {id: $id}) RETURN p.raw_text AS raw_text, p.title AS title",
                                id=lft_paper_id,
                            ).single()
                        if row and row["raw_text"]:
                            raw = row["raw_text"]
                            lft_title = row["title"] or lft_paper_id
                            raw_tokens = estimate_tokens(raw)
                            budget_tokens = 15_000
                            if raw_tokens <= budget_tokens:
                                lft_content = raw
                                tok_label = f"{raw_tokens:,} tokens"
                            else:
                                lft_content = _condense_paper_for_budget(lft_title, raw, budget_tokens)
                                tok_label = f"condensed to ~{estimate_tokens(lft_content):,} tokens"
                        else:
                            lft_content = "[Full text not available for this paper]"
                            tok_label = "no text stored"
                    except Exception as exc:
                        log.warning("load_full_text tool failed | %s", exc)
                        lft_content = f"[Error loading full text: {exc}]"
                        tok_label = "error"
                else:
                    lft_content = "[Full text unavailable — no database connection]"
                    tok_label = "unavailable"

                yield {
                    "type": "step",
                    "description": f"Loading full text: {lft_title[:60]} ({tok_label})",
                    "cypher": None,
                    "count": None,
                }
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": lft_content,
                })

        if not tool_results:
            # No recognised tools in this response — break to avoid infinite loop
            break

        # Feed tool results back into the conversation and loop
        messages = list(messages)
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


def summarize_chapter(title: str, text: str, model: str | None = None) -> str:
    """Return a markdown summary of a book/lecture chapter.

    Routes to work gateway when model=='claude-work', personal Anthropic when
    model starts with 'claude-', otherwise Ollama.
    """
    if not text or not text.strip():
        return "_No text available for this chapter._"

    effective_model = model or settings.ollama_model
    use_claude = effective_model == "claude-work" or effective_model.startswith("claude-")
    prompt = _load_prompt("chapter_summary.txt").format(
        title=title or "(untitled chapter)",
        text=text[:20000] if use_claude else text[:8000],
    )

    if effective_model == "claude-work":
        work_client = _work_client()
        message = work_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    elif effective_model.startswith("claude-"):
        client = _personal_client()
        message = client.messages.create(
            model=effective_model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    else:
        import ollama
        response = ollama.chat(
            model=effective_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"].strip()


def chat_with_chapter(
    chapter_title: str,
    chapter_text: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* about a specific chapter using Claude."""
    system = _load_prompt("chapter_chat_system.txt").format(
        title=chapter_title or "(untitled chapter)",
        text=chapter_text[:30000],
    )
    client = _personal_client()
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def detect_chapters_with_ai(title: str, text: str) -> list[dict]:
    """
    Use Ollama to propose a chapter structure from a book/lecture PDF text.
    Returns a list of dicts: [{number, title, level}, ...].
    Falls back to [] on any error.
    """
    import json, re, ollama

    if not text or not text.strip():
        return []

    prompt = (
        "You are a book indexer. Given the following text from a book or lecture deck, "
        "identify the main chapters (and sub-chapters if clearly present). "
        "Return a JSON object with key 'chapters', each item having: "
        "number (int), title (str), level (1=chapter, 2=sub-chapter).\n\n"
        f"Document title: {title or '(unknown)'}\n\n"
        f"Document text (first 6000 words):\n{text[:15000]}"
    )
    response = ollama.chat(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response["message"]["content"].strip()
    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group())
        chapters = data.get("chapters") or []
        return [
            {
                "number": int(c.get("number", i + 1)),
                "title": str(c.get("title", f"Chapter {i + 1}")),
                "level": int(c.get("level", 1)),
            }
            for i, c in enumerate(chapters)
            if c.get("title")
        ]
    except Exception:
        return []


def extract_affiliations_with_ollama(author_names: list[str], text: str) -> dict[str, str | None]:
    """Use Ollama to extract institutional affiliations for authors from paper text.
    Returns {author_name: affiliation_or_None}.
    """
    import json as _json
    import ollama

    if not author_names:
        return {}

    prompt = _load_prompt("author_affiliations.txt").format(
        author_names="\n".join(f"- {n}" for n in author_names),
        text=text[:4000],  # first 4000 chars — affiliations are always in the header
    )
    try:
        response = ollama.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        raw = _json.loads(response["message"]["content"])
        result: dict[str, str | None] = {}
        for entry in raw.get("affiliations") or []:
            name = entry.get("name", "").strip()
            aff = entry.get("affiliation") or None
            if name:
                result[name] = aff
        return result
    except Exception as exc:
        log.warning("Ollama affiliation extraction failed: %s", exc)
        return {}


# ── Blog post AI ───────────────────────────────────────────────────────────────

def summarize_blog_post(content: str, title: str = "") -> str:
    """Summarize a blog post using Claude Haiku (fast, cheap)."""
    if not content or not content.strip():
        return "_No content available to summarize._"

    prompt = (
        f"Summarize the following blog post concisely in 3-5 bullet points. "
        f"Focus on the key ideas, insights, and takeaways. "
        f"Use markdown formatting.\n\n"
        f"Title: {title or '(unknown)'}\n\n"
        f"Content:\n{content[:30000]}"
    )

    client = _personal_client()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def chat_with_blog_post(
    content: str,
    title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer a question about a blog post using its content as context."""
    system = (
        f"You are an expert assistant helping the user understand a blog post.\n\n"
        f"Blog post title: {title or '(unknown)'}\n\n"
        f"Blog post content:\n{content[:60000]}\n\n"
        f"Answer the user's questions about this blog post concisely and accurately. "
        f"If the answer is not in the blog post, say so."
    )

    client = _personal_client()
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return response.content[0].text


# ── Research Gap Finder (T29) ─────────────────────────────────────────────────

def find_research_gaps(
    topic: str,
    papers: list[dict],   # list of {title, abstract, summary, year}
    model: str = "claude",
) -> str:
    """
    Analyze research gaps using the specified model with web_search tool enabled.
    Returns markdown analysis string.
    
    Args:
        topic: Research topic or question
        papers: List of papers with title, abstract, summary, year
        model: "claude" (personal), "claude-work", or "ollama"
    """
    def _paper_block(p: dict) -> str:
        parts = [f"- **{p.get('title', 'Untitled')}** ({p.get('year', '?')})"]
        if p.get("abstract"):
            parts.append(f"  {p['abstract'][:300]}")
        return "\n".join(parts)

    papers_block = "\n".join(_paper_block(p) for p in papers) or "(no papers in library for this topic)"
    system_prompt = _load_prompt("research_gaps.txt").format(
        topic=topic,
        n=len(papers),
        papers_block=papers_block,
    )
    
    # Route to appropriate model
    if model == "claude-work":
        client = _work_client()
        return _run_claude_with_tools(
            client,
            "claude-opus-4-6",
            "You are a research strategist with web search capabilities.",
            [{"role": "user", "content": system_prompt}],
            max_tokens=2048,
        )
    elif model == "ollama":
        # Ollama doesn't support tool calling as robustly, so we'll use a simpler approach
        import ollama
        response = ollama.chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": "You are a research strategist analyzing research gaps. Provide structured analysis with sections: Coverage Summary, Identified Gaps, Recommended Next Reads, and Open Questions."},
                {"role": "user", "content": system_prompt}
            ],
        )
        return response["message"]["content"].strip()
    else:  # "claude" (personal)
        client = _personal_client()
        return _run_claude_with_tools(
            client,
            "claude-opus-4-6",
            "You are a research strategist with web search capabilities.",
            [{"role": "user", "content": system_prompt}],
            max_tokens=2048,
        )


def extract_claims(text: str, title: str, model: str | None = None) -> list[dict]:
    """
    Extract claims from paper text using Claude Haiku or Ollama.
    Routes to Anthropic when model starts with 'claude-', otherwise Ollama.
    Returns list of {"text": str, "type": str}.
    Returns [] on any error (non-fatal — called best-effort on upload).
    """
    import json, re
    if not text or not text.strip():
        return []
    
    effective_model = model or settings.ollama_model
    prompt = _load_prompt("claims.txt").format(
        title=title or "(unknown)",
        text=text[:40000] if effective_model.startswith("claude-") else text[:12000],
    )
    
    try:
        if effective_model.startswith("claude-"):
            client = _personal_client()
            message = client.messages.create(
                model=effective_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
        else:
            # Use Ollama
            import ollama
            response = ollama.chat(
                model=effective_model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            raw = response["message"]["content"].strip()
        
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group())
        return [c for c in (data.get("claims") or []) if c.get("text")]
    except Exception as exc:
        log.warning("extract_claims failed (non-fatal) | model=%s | %s", effective_model, exc)
        return []



def _generate_search_queries(question: str, history: list[dict]) -> list[str]:
    """
    Use Claude Haiku to extract up to 3 search queries from the user's question.
    Returns [] if the question is clearly answerable from library context alone
    (e.g. 'summarise paper X', 'what do my papers say about Y').
    """
    import json, re
    
    prompt = f"""Given this research question, suggest up to 3 web search queries
that would find relevant recent papers, blog posts, or news. If no web
search is needed (the question is about the user's own library), return an empty list.
Return JSON: {{"queries": ["...", "..."]}}

Question: {question}"""
    
    try:
        client = _personal_client()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group())
        queries = data.get("queries") or []
        return [q.strip() for q in queries if q.strip()][:3]
    except Exception as exc:
        log.warning("_generate_search_queries failed | %s", exc)
        return []


def _fetch_web_context(question: str, history: list[dict]) -> str:
    """
    Runs _generate_search_queries(), executes each via search_web(),
    formats results with format_results_for_prompt().
    Returns empty string if no queries generated or all searches fail.
    """
    from services.web_search import search_web, format_results_for_prompt
    
    queries = _generate_search_queries(question, history)
    if not queries:
        return ""
    
    all_results = []
    for query in queries:
        results = search_web(query, max_results=5)
        all_results.extend(results)
    
    if not all_results:
        return ""
    
    return format_results_for_prompt(all_results)


def synthesize_papers(
    papers: list[dict],        # list of {title, abstract, summary, raw_text (optional)}
    question: str,
    use_web: bool = True,
) -> str:
    """
    Builds a synthesis prompt from the selected papers.
    Each paper contributes its abstract + summary (not full raw_text — too large).
    Optionally uses web search via _run_claude_with_tools().
    Returns markdown synthesis string.
    """
    def _paper_block(p: dict) -> str:
        parts = [f"### {p.get('title', 'Untitled')}"]
        if p.get("year"):
            parts[0] += f" ({p['year']})"
        if p.get("abstract"):
            parts.append(f"**Abstract:** {p['abstract'][:1500]}")
        if p.get("summary"):
            parts.append(f"**Summary:** {p['summary'][:2000]}")
        return "\n".join(parts)

    papers_block = "\n\n".join(_paper_block(p) for p in papers)
    prompt = _load_prompt("synthesis.txt").format(
        n=len(papers),
        question=question,
        papers_block=papers_block,
    )

    client = _personal_client()
    if use_web:
        return _run_claude_with_tools(
            client, "claude-opus-4-6",
            "You are a research synthesis expert.", 
            [{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
    else:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
