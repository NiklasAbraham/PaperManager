"""Shared tag-suggestion logic (LiteLLM/Gemma primary path).

Used by both the /tags/suggest endpoint and the queue analysis precompute so
suggestions can be computed once, in the background, and reused at upload time.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

_SKIP = {
    "pdf-upload", "from-url", "from-references", "bulk-import", "debug",
    "from-linkedin", "from-twitter", "from-email", "from-conference",
    "from-newsletter", "from-google-scholar", "from-google", "from-ai-chat",
    "from-arxiv", "from-colleague",
}


def build_prompt(title: str, abstract: str | None, candidate_tags: list[str]) -> str:
    abstract_block = f"Abstract:\n{abstract}" if abstract else "(no abstract available)"
    tag_list = ", ".join(candidate_tags) if candidate_tags else "(none yet)"
    return (
        "You are helping organise academic papers in a personal research library.\n\n"
        f"Available tags in this library:\n{tag_list}\n\n"
        f"Paper to tag:\nTitle: {title}\n{abstract_block}\n\n"
        "Task:\n"
        "1. From the available tags above, pick the most relevant ones for this paper (ideally 3–6).\n"
        "2. If fewer than 4 existing tags fit well, suggest additional NEW tag names (total ≥ 4).\n"
        "   New tags: lowercase, hyphen-separated, max 60 chars each.\n\n"
        'Return ONLY valid JSON with exactly two keys:\n'
        '  "existing": [list of chosen tags from the available list]\n'
        '  "new": [list of brand-new tag names, or empty list]\n\n'
        "No explanation, no markdown fences, just the JSON object."
    )


def parse_response(raw_text: str, existing_tags: list[str]) -> tuple[list[str], list[str]]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    raw = json.loads(m.group() if m else text)
    existing_set = set(existing_tags)
    valid_existing = [t for t in (raw.get("existing") or []) if t in existing_set]
    new_tags = [
        t.lower().replace(" ", "-")[:60]
        for t in (raw.get("new") or [])
        if t and t.lower().replace(" ", "-")[:60] not in existing_set
    ]
    return valid_existing, new_tags


def suggest_tags_litellm(title: str, abstract: str | None, existing_tags: list[str]) -> dict | None:
    """Suggest tags via LiteLLM/Gemma. Returns None if the call fails (caller may fall back)."""
    candidate_tags = [t for t in existing_tags if t not in _SKIP]
    prompt = build_prompt(title, abstract, candidate_tags)
    try:
        from services.litellm_client import chat_completion

        raw = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
        valid_existing, new_tags = parse_response(raw, existing_tags)
        log.debug("Tag suggestion via LiteLLM | existing=%d new=%d", len(valid_existing), len(new_tags))
        return {"existing": valid_existing, "new": new_tags, "all_tags": existing_tags}
    except Exception as e:
        log.warning("LiteLLM tag suggestion failed | %s", e)
        return None
