"""Claude AI services — summarization and chat."""
from __future__ import annotations

from typing import Any

import anthropic
from config import settings

_SUMMARY_PROMPT = """\
You are a research assistant helping to summarize academic papers.

Given the following paper text, write a concise summary covering:
1. **Problem**: What problem does this paper address?
2. **Method**: What approach or method do they use?
3. **Key findings**: What are the main results or contributions?
4. **Relevance**: Who would benefit from reading this?

Keep the summary under 300 words. Use plain language where possible.

Paper title: {title}

Paper text (first 8000 words):
{text}"""


def summarize_paper(text: str, title: str = "") -> str:
    """Return a markdown summary of *text* using Claude.

    Falls back to a short notice if text is empty.
    """
    if not text or not text.strip():
        return "_No text could be extracted from this paper._"

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": _SUMMARY_PROMPT.format(
                    title=title or "(unknown)",
                    text=text[:40000],
                ),
            }
        ],
    )
    return message.content[0].text


_CHAT_SYSTEM = """\
You are a research assistant helping to understand a specific academic paper.
Answer questions about this paper based on its content.
If the answer is not in the paper, say so clearly.

Paper title: {title}

Paper text:
{text}"""


def chat_with_paper(
    paper_text: str,
    paper_title: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer *question* about a paper using its full text as context.

    *history* is a list of ``{"role": "user"|"assistant", "content": str}``
    dicts representing prior turns in the conversation.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=_CHAT_SYSTEM.format(
            title=paper_title or "(unknown)",
            text=paper_text[:60000],
        ),
        messages=messages,
    )
    return response.content[0].text
