"""Knowledge Chat — cross-library graph-aware chat with SSE streaming."""
from __future__ import annotations
import json
import logging
import re
from typing import Any, Generator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from db.connection import get_driver
from db.queries.conversations import (
    create_conversation, add_message, list_conversations,
    get_messages, compact_conversation, delete_conversation,
)
from models.schemas import KnowledgeChatRequest, ConversationOut, MessageOut
from services.ai import knowledge_chat_stream, estimate_tokens, summarize_paper, CONTEXT_WINDOW

log = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge-chat", tags=["knowledge-chat"])

# ── SSE helpers ────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ── @mention parsing ──────────────────────────────────────────────────────────

_MENTION_RE = re.compile(r"@(project|tag|topic|paper):([^\s@,]+)", re.IGNORECASE)

# Paper colour palette for context bar (cycled)
_PAPER_COLORS = [
    "#7c3aed", "#2563eb", "#0891b2", "#059669",
    "#d97706", "#dc2626", "#7c3aed", "#9333ea",
]


def _parse_mentions(text: str) -> list[tuple[str, str]]:
    """Return list of (type, value) tuples from @mentions in text."""
    return [(m.group(1).lower(), m.group(2)) for m in _MENTION_RE.finditer(text)]


def _fetch_papers_for_mention(
    session, mention_type: str, value: str
) -> tuple[list[dict], str, str]:
    """
    Run the appropriate Cypher query for a mention type.
    Returns (papers, cypher_query, description).
    Papers are dicts with keys: id, title, abstract, summary.
    """
    value_clean = value.replace("-", " ").lower()

    if mention_type == "tag":
        cypher = (
            "MATCH (p:Paper)-[:TAGGED]->(:Tag {name: $val}) "
            "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
            "LIMIT 20"
        )
        desc = f"Fetching papers tagged '{value}'"
        result = session.run(cypher, val=value)

    elif mention_type == "topic":
        cypher = (
            "MATCH (p:Paper)-[:ABOUT]->(:Topic) WHERE toLower(t.name) CONTAINS $val "
            "WITH p LIMIT 20 "
            "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary"
        )
        # Simpler approach: exact name match first, then fallback to contains
        cypher = (
            "MATCH (p:Paper)-[:ABOUT]->(t:Topic) "
            "WHERE toLower(t.name) CONTAINS $val "
            "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
            "LIMIT 20"
        )
        desc = f"Fetching papers about topic '{value}'"
        result = session.run(cypher, val=value_clean)

    elif mention_type == "project":
        cypher = (
            "MATCH (proj:Project)-[:CONTAINS]->(p:Paper) "
            "WHERE toLower(proj.name) CONTAINS $val "
            "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
            "LIMIT 30"
        )
        desc = f"Fetching papers in project '{value}'"
        result = session.run(cypher, val=value_clean)

    elif mention_type == "paper":
        cypher = (
            "MATCH (p:Paper) "
            "WHERE toLower(p.title) CONTAINS $val "
            "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
            "LIMIT 5"
        )
        desc = f"Fetching paper matching '{value}'"
        result = session.run(cypher, val=value_clean)

    else:
        return [], "", ""

    papers = [dict(r) for r in result]
    return papers, cypher, desc


def _fallback_all_papers(session) -> list[dict]:
    """When no @mentions, use the 10 most recently added papers."""
    cypher = (
        "MATCH (p:Paper) WHERE NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'}) "
        "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
        "ORDER BY p.created_at DESC LIMIT 10"
    )
    return [dict(r) for r in session.run(cypher)]


# ── SSE stream generator ──────────────────────────────────────────────────────

def _stream(body: KnowledgeChatRequest) -> Generator[str, None, None]:
    driver = get_driver()

    # Step 1: parse mentions
    mentions = _parse_mentions(body.question)
    yield _sse({"type": "step", "description": "Parsing @mentions in your question",
                "cypher": None, "count": len(mentions)})

    # Step 2: fetch papers per mention
    papers_by_id: dict[str, dict] = {}
    with driver.session() as session:
        if mentions:
            for mtype, mval in mentions:
                papers, cypher, desc = _fetch_papers_for_mention(session, mtype, mval)
                yield _sse({
                    "type": "step",
                    "description": desc,
                    "cypher": cypher,
                    "count": len(papers),
                })
                for p in papers:
                    if p["id"] not in papers_by_id:
                        papers_by_id[p["id"]] = p
        else:
            cypher = (
                "MATCH (p:Paper) WHERE NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'}) "
                "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
                "ORDER BY p.created_at DESC LIMIT 10"
            )
            yield _sse({
                "type": "step",
                "description": "No @mentions — using 10 most recent papers as context",
                "cypher": cypher,
                "count": None,
            })
            papers = _fallback_all_papers(session)
            for p in papers:
                papers_by_id[p["id"]] = p

    all_papers = list(papers_by_id.values())

    # Step 3: compute token estimates
    sys_tokens = estimate_tokens(
        open(__import__("pathlib").Path(__file__).parent.parent.parent / "prompts" /
             "knowledge_chat_system.txt").read()
    ) + 200  # buffer for papers_block header

    history_tokens = sum(estimate_tokens(m["content"]) for m in body.history)
    question_tokens = estimate_tokens(body.question)

    paper_infos = []
    for i, p in enumerate(all_papers):
        text = " ".join(filter(None, [p.get("title"), p.get("abstract"), p.get("summary")]))
        tok = estimate_tokens(text)
        paper_infos.append({
            "id": p["id"],
            "title": p.get("title") or "Untitled",
            "tokens": tok,
            "color": _PAPER_COLORS[i % len(_PAPER_COLORS)],
        })

    papers_tokens = sum(pi["tokens"] for pi in paper_infos)
    total_tokens = sys_tokens + papers_tokens + history_tokens + question_tokens

    yield _sse({
        "type": "context",
        "papers": paper_infos,
        "token_totals": {
            "system": sys_tokens,
            "papers": papers_tokens,
            "history": history_tokens,
            "question": question_tokens,
            "total": total_tokens,
            "limit": CONTEXT_WINDOW,
        },
    })

    # Step 4: create/load conversation, save user message
    conv_id = body.conversation_id
    if not conv_id:
        title = body.question[:60] + ("…" if len(body.question) > 60 else "")
        conv = create_conversation(driver, title)
        conv_id = conv["id"]

    paper_ids = [p["id"] for p in all_papers]
    add_message(driver, conv_id, "user", body.question, paper_ids, question_tokens)

    # Step 5: stream Claude response
    yield _sse({"type": "step", "description": "Sending to Claude…", "cypher": None, "count": None})

    full_answer = ""
    try:
        stream_cm = knowledge_chat_stream(
            question=body.question,
            history=[{"role": m["role"], "content": m["content"]} for m in body.history],
            papers=all_papers,
            model=body.model,
        )
        with stream_cm as stream:
            for text in stream.text_stream:
                full_answer += text
                yield _sse({"type": "token", "text": text})
    except Exception as exc:
        log.error("knowledge_chat_stream error | %s", exc)
        yield _sse({"type": "error", "message": str(exc)})
        return

    # Step 6: save assistant message and emit done
    answer_tokens = estimate_tokens(full_answer)
    msg = add_message(driver, conv_id, "assistant", full_answer, paper_ids, answer_tokens)

    yield _sse({
        "type": "done",
        "conversation_id": conv_id,
        "message_id": msg["id"],
    })


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/stream")
def stream_chat(body: KnowledgeChatRequest):
    return StreamingResponse(
        _stream(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationOut])
def get_conversations():
    return list_conversations(get_driver())


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def get_conv_messages(conv_id: str):
    msgs = get_messages(get_driver(), conv_id)
    if msgs is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return msgs


@router.post("/conversations/{conv_id}/compact", response_model=MessageOut)
def compact(conv_id: str):
    """Summarise the conversation into a single system message."""
    msgs = get_messages(get_driver(), conv_id)
    if not msgs:
        raise HTTPException(status_code=404, detail="Conversation not found or empty")
    full_text = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in msgs)
    try:
        summary = summarize_paper(full_text, title="Conversation summary")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Summarisation failed: {exc}")
    return compact_conversation(get_driver(), conv_id, summary)


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conv(conv_id: str):
    delete_conversation(get_driver(), conv_id)
