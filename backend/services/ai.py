"""Claude and Ollama AI services — summarization and chat."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import anthropic
from config import settings

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


def chat_with_paper(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* about a paper using its full text as context."""
    system = _load_prompt("chat_system.txt").format(
        title=paper_title or "(unknown)",
        text=paper_text[:60000],
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


def chat_with_paper_work(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* using the work/Foundry Anthropic gateway."""
    if not settings.anthropic_work_api_key:
        raise ValueError("Work Anthropic key (ANTHROPIC_WORK_API_KEY) is not configured.")

    kwargs: dict[str, Any] = {
        "api_key": settings.anthropic_work_api_key,
        "http_client": httpx.Client(verify=_ssl_verify()),
    }
    if settings.anthropic_work_base_url:
        kwargs["base_url"] = settings.anthropic_work_base_url

    client = anthropic.Anthropic(**kwargs)

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})

    system = _load_prompt("chat_system.txt").format(
        title=paper_title or "(unknown)",
        text=paper_text[:60000],
    )
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def chat_with_paper_ollama(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* about a paper using Ollama (local LLM)."""
    import ollama

    system = _load_prompt("chat_system.txt").format(
        title=paper_title or "(unknown)",
        text=paper_text[:12000],  # smaller context window for local models
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for msg in (history or []):
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    response = ollama.chat(model=settings.ollama_model, messages=messages)
    return response["message"]["content"].strip()


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
) -> Any:
    """Stream a knowledge-chat response as an anthropic MessageStream.

    *papers* is a list of dicts with keys: id, title, abstract, summary.
    Caller is responsible for building the system prompt via _load_prompt.
    Returns the anthropic stream context manager (use with `with` statement).
    """
    papers_block = "\n\n".join(
        f"### {p.get('title', 'Untitled')}\n"
        + (f"Abstract: {p['abstract']}\n" if p.get("abstract") else "")
        + (f"Summary: {p['summary']}" if p.get("summary") else "")
        for p in papers
    )
    system = _load_prompt("knowledge_chat_system.txt").format(papers_block=papers_block)

    messages: list[dict[str, Any]] = list(history)
    messages.append({"role": "user", "content": question})

    if model == "claude-work":
        if not settings.anthropic_work_api_key:
            raise ValueError("Work API key not configured.")
        client = anthropic.Anthropic(
            api_key=settings.anthropic_work_api_key,
            base_url=settings.anthropic_work_base_url or None,
            http_client=httpx.Client(verify=_ssl_verify()),
        )
    else:
        client = _personal_client()

    return client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=system,
        messages=messages,
    )


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
