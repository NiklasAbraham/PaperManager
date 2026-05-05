"""Claude and Ollama AI services — summarization and chat."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import anthropic
from config import settings
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
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        base_url=_ANTHROPIC_BASE_URL,
        http_client=httpx.Client(verify=_ssl_verify()),
    )


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
            f"Paper text (first 8000 words):\n{text[:40000]}"
        )
    else:
        prompt = _load_prompt("summary.txt").format(
            title=title or "(unknown)",
            text=text[:40000],
        )

    client = _personal_client()
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


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
    if not settings.anthropic_work_api_key:
        raise ValueError("Work Anthropic key (ANTHROPIC_WORK_API_KEY) is not configured.")

    kwargs: dict[str, Any] = {
        "api_key": settings.anthropic_work_api_key,
        "http_client": httpx.Client(verify=_ssl_verify()),
    }
    if settings.anthropic_work_base_url:
        kwargs["base_url"] = settings.anthropic_work_base_url

    client = anthropic.Anthropic(**kwargs)
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


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def knowledge_chat_stream(
    question: str,
    history: list[dict[str, Any]],
    papers: list[dict[str, Any]],
    model: str = "claude",
    use_web: bool = True,
) -> Any:
    """Stream a knowledge-chat response as an anthropic MessageStream.

    *papers* is a list of dicts with keys: id, title, abstract, summary.
    Caller is responsible for building the system prompt via _load_prompt.
    Returns the anthropic stream context manager (use with `with` statement).
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

    # Pre-search for web context if enabled
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

    messages: list[dict[str, Any]] = list(history)
    messages.append({"role": "user", "content": question})

    if model == "claude-work":
        if not settings.anthropic_work_api_key:
            raise ValueError("Work API key not configured.")
        client = anthropic.Anthropic(
            api_key=settings.anthropic_work_api_key,
            base_url=settings.anthropic_work_base_url or None,
            default_headers={"Authorization": f"Bearer {settings.anthropic_work_api_key}"},
            http_client=httpx.Client(verify=_ssl_verify()),
        )
        claude_model = "claude-sonnet-4-6"
    else:
        client = _personal_client()
        claude_model = "claude-sonnet-4-6"

    return client.messages.stream(
        model=claude_model,
        max_tokens=2048,
        system=system,
        messages=messages,
    )


def summarize_chapter(title: str, text: str, model: str | None = None) -> str:
    """Return a markdown summary of a book/lecture chapter.

    Routes to Anthropic when model starts with 'claude-', otherwise Ollama.
    """
    if not text or not text.strip():
        return "_No text available for this chapter._"

    effective_model = model or settings.ollama_model
    prompt = _load_prompt("chapter_summary.txt").format(
        title=title or "(untitled chapter)",
        text=text[:20000] if effective_model.startswith("claude-") else text[:8000],
    )

    if effective_model.startswith("claude-"):
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



def extract_claims(text: str, title: str) -> list[dict]:
    """
    Uses Claude Haiku to extract claims from paper text.
    Returns list of {"text": str, "type": str}.
    Returns [] on any error (non-fatal — called best-effort on upload).
    """
    import json, re
    if not text or not text.strip():
        return []
    prompt = _load_prompt("claims.txt").format(
        title=title or "(unknown)",
        text=text[:40000],
    )
    try:
        client = _personal_client()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group())
        return [c for c in (data.get("claims") or []) if c.get("text")]
    except Exception as exc:
        log.warning("extract_claims failed (non-fatal) | %s", exc)
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
