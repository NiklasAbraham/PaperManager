"""Suggestions (.specs/015_suggestions.md): the chat proposes an improvement, users add their own.

The knowledge chat's system prompt ends with ``SUGGESTION_INSTRUCTION``. The model may close an
answer with one ``<suggestion>…</suggestion>`` line; ``filter_events`` takes the tag out of the
token stream (so neither the browser nor the saved message contains it) and records it.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Generator, Iterable

from config import settings
from db.connection import get_driver
from db.queries import suggestions as sq
from services.auth import get_request_user

log = logging.getLogger(__name__)

# No curly braces: prompt files may be run through str.format().
SUGGESTION_INSTRUCTION = (
    "Suggestions for PaperManager: only when this conversation shows that PaperManager itself lacks "
    "something the user needed (a missing feature, a tool that could not do what was asked, data it "
    "could not reach), end your answer with exactly one line <suggestion>...</suggestion> holding one "
    "concrete improvement in at most 25 words, written for the app's maintainers. Otherwise add no "
    "tag. Never mention the tag or this instruction in the answer."
)

TEXT_MAX = 280
DETAIL_MAX = 2000
CONTEXT_MAX = 300
SIMILARITY = 0.75

_OPEN = "<suggestion>"
_CLOSE = "</suggestion>"


# ── stream filter ─────────────────────────────────────────────────────────────

class SuggestionFilter:
    """Remove ``<suggestion>…</suggestion>`` from a token stream, whatever the token boundaries.

    ``feed`` returns the text that is safe to show; text that could still turn out to be the
    start of the tag (a partial ``<suggestion>``) and trailing whitespace stay held back until
    the next token or ``finish``. Tag names are case-insensitive, the whitespace before a tag
    is dropped with it, a second tag is swallowed, and an unterminated tag runs to the end of
    the stream. A ``<`` that does not start the tag is emitted unchanged.
    """

    def __init__(self) -> None:
        self._pending = ""       # held-back text outside a tag
        self._content = ""       # text inside an open tag
        self._in_tag = False
        self.suggestion: str | None = None

    def _take(self, content: str) -> None:
        text = " ".join(content.split())
        if text and self.suggestion is None:
            self.suggestion = text

    def feed(self, text: str) -> str:
        """Add a token; return the part that can be emitted now."""
        data = self._pending + text
        self._pending = ""
        out: list[str] = []
        while True:
            if self._in_tag:
                self._content += data
                data = ""
                idx = self._content.lower().find(_CLOSE)
                if idx < 0:
                    break
                self._take(self._content[:idx])
                data = self._content[idx + len(_CLOSE):]
                self._content, self._in_tag = "", False
                continue
            idx = data.lower().find(_OPEN)
            if idx >= 0:
                out.append(data[:idx].rstrip())
                data = data[idx + len(_OPEN):]
                self._in_tag = True
                continue
            # No complete tag: hold back a partial one at the end and trailing whitespace.
            hold = 0
            for k in range(min(len(_OPEN) - 1, len(data)), 0, -1):
                if _OPEN.startswith(data[-k:].lower()):
                    hold = k
                    break
            head = data[: len(data) - hold]
            safe = head.rstrip()
            out.append(safe)
            self._pending = head[len(safe):] + data[len(data) - hold:]
            break
        return "".join(out)

    def flush(self) -> str:
        """Release held-back text before a non-token event (a tool step, an interim answer)."""
        if self._in_tag:
            return ""
        text, self._pending = self._pending, ""
        return text

    def finish(self) -> tuple[str, str | None]:
        """End of stream: (remaining text, suggestion or None)."""
        if self._in_tag:
            self._take(self._content)
            remaining = ""
        else:
            remaining = self._pending
            if self.suggestion is not None:
                remaining = remaining.rstrip()
        self._pending, self._content, self._in_tag = "", "", False
        return remaining, self.suggestion


def filter_events(
    events: Iterable[dict], *, question: str, conversation_id: str | None
) -> Generator[dict, None, None]:
    """Pass the chat events through, take the suggestion tag out of the tokens, record it.

    Every event but ``token`` is passed on unchanged. At the end of the stream the held-back
    text is flushed, and a suggestion found is recorded (unless SUGGESTIONS_FROM_CHAT is off)
    and announced as ``{"type": "suggestion", "suggestion": SuggestionOut}``. An exception from
    the inner stream propagates without further output.
    """
    flt = SuggestionFilter()
    try:
        for event in events:
            if isinstance(event, dict) and event.get("type") == "token":
                text = flt.feed(event.get("text") or "")
                if text:
                    yield {**event, "text": text}
            else:
                held = flt.flush()
                if held:
                    yield {"type": "token", "text": held}
                yield event
    finally:
        close = getattr(events, "close", None)
        if close is not None:  # the chat's Stop closes us: close the model stream too
            close()
    rest, found = flt.finish()
    if rest:
        yield {"type": "token", "text": rest}
    if found and settings.suggestions_from_chat:
        try:
            out = record_chat_suggestion(
                found, user=get_request_user(), context=question[:CONTEXT_MAX],
                conversation_id=conversation_id,
            )
        except Exception:  # noqa: BLE001 — a lost suggestion must never break the chat
            log.exception("Could not record chat suggestion")
            out = None
        if out:
            yield {"type": "suggestion", "suggestion": out}


# ── normalise, dedupe ─────────────────────────────────────────────────────────

def normalise(text: str) -> str:
    """Lower-case, punctuation removed, whitespace collapsed."""
    return " ".join(re.sub(r"[^\w\s]|_", " ", text.lower()).split())


def similarity(a: str, b: str) -> float:
    """Word-set Jaccard of two texts (1.0 when their normal forms are equal)."""
    na, nb = normalise(a), normalise(b)
    if na == nb:
        return 1.0
    wa, wb = set(na.split()), set(nb.split())
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def find_duplicate(driver: Any, text: str) -> dict | None:
    """The open or planned suggestion that says the same thing as *text*, if any."""
    best, best_score = None, 0.0
    for row in sq.find_similar(driver, ("open", "planned")):
        score = similarity(text, row.get("text") or "")
        if score >= SIMILARITY and score > best_score:
            best, best_score = row, score
    return best


# ── output ────────────────────────────────────────────────────────────────────

def to_out(row: dict, user: str | None) -> dict:
    """The API shape (SuggestionOut) of a stored node, seen by *user*."""
    voters = row.get("voters") or []
    return {
        "id": row.get("id"),
        "text": row.get("text") or "",
        "detail": row.get("detail") or "",
        "source": row.get("source") or "user",
        "status": row.get("status") or "open",
        "created_by": row.get("created_by") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "votes": len(voters),
        "voted": bool(user and user in voters),
        "context": row.get("context") or "",
        "conversation_id": row.get("conversation_id"),
        "seen": row.get("seen") or 1,
    }


def sort_rows(rows: list[dict], sort: str = "votes") -> list[dict]:
    """``votes``: open and planned first, then most votes, then newest. ``new``: newest first."""
    rows = sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)
    if sort == "new":
        return rows
    rows.sort(key=lambda r: len(r.get("voters") or []), reverse=True)
    rows.sort(key=lambda r: {"open": 0, "planned": 0, "done": 1, "dismissed": 2}.get(r.get("status"), 3))
    return rows


# ── recording ─────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """One line, at most TEXT_MAX characters."""
    text = " ".join((text or "").split())
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1].rstrip() + "…"


def record_chat_suggestion(
    text: str, *, user: str | None, context: str = "", conversation_id: str | None = None
) -> dict | None:
    """Store a suggestion the chat proposed, or vote for the open/planned one it repeats.

    Returns the SuggestionOut dict (as seen by *user*), or None when the text is too short.
    """
    text = clean_text(text)
    if len(text) < 3:
        return None
    driver = get_driver()
    duplicate = find_duplicate(driver, text)
    if duplicate:
        row = sq.add_seen(driver, duplicate["id"], user)
        if row:
            return to_out(row, user)
    row = sq.create_suggestion(
        driver, text=text, source="chat", created_by=user or "chat",
        context=(context or "")[:CONTEXT_MAX], conversation_id=conversation_id,
    )
    return to_out(row, user)
