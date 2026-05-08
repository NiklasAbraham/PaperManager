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
    get_messages, compact_conversation, compact_conversation_sliding_window,
    delete_conversation, get_paper_context_snippets,
)
from models.schemas import KnowledgeChatRequest, ConversationOut, MessageOut
from services.ai import knowledge_chat_stream, estimate_tokens, summarize_paper, CONTEXT_WINDOW

log = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge-chat", tags=["knowledge-chat"])

# ── SSE helpers ────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ── @mention parsing ──────────────────────────────────────────────────────────

_MENTION_RE = re.compile(r"@(project|tag|topic|paper|blog|person):([^\s@,]+)", re.IGNORECASE)

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

    elif mention_type == "blog":
        cypher = (
            "MATCH (bp:BlogPost)-[:FROM_BLOG]->(b:Blog) "
            "WHERE toLower(b.name) CONTAINS $val OR toLower(bp.title) CONTAINS $val "
            "RETURN bp.id AS id, bp.title AS title, bp.description AS abstract, bp.summary AS summary "
            "LIMIT 20"
        )
        desc = f"Fetching blog posts matching '{value}'"
        result = session.run(cypher, val=value_clean)

    elif mention_type == "person":
        # value can be a tag name (e.g. "known-personally") or a person's name
        # First try as a tag on Person nodes → get their papers
        # Then try as a person name match
        cypher = (
            "MATCH (paper:Paper)-[:AUTHORED_BY|INVOLVES]->(person:Person) "
            "WHERE (person)-[:TAGGED]->(:Tag {name: $val}) "
            "   OR toLower(person.name) CONTAINS $name_val "
            "RETURN DISTINCT paper.id AS id, paper.title AS title, "
            "       paper.abstract AS abstract, paper.summary AS summary "
            "LIMIT 30"
        )
        desc = f"Fetching papers by people matching '{value}'"
        result = session.run(cypher, val=value, name_val=value_clean)

    else:
        return [], "", ""

    papers = [dict(r) for r in result]
    return papers, cypher, desc


def _fallback_all_papers(session, question: str = "") -> list[dict]:
    """When no @mentions, retrieve papers via hybrid retrieval.

    Primary: semantic vector search on the user's question (top 10 by cosine similarity).
    Secondary: 10 most recently added papers (recency fallback).
    Blog posts: 5 most recently imported posts.
    All three sets are merged and deduplicated by id.
    """
    papers_by_id: dict[str, dict] = {}

    # Semantic retrieval — best effort, falls back silently if embeddings unavailable
    if question:
        try:
            from services.embeddings import embed_text as _embed_text
            emb = _embed_text(question)
            result = session.run(
                "CALL db.index.vector.queryNodes('paper_embeddings', 10, $emb) "
                "YIELD node AS p, score "
                "WHERE score > 0.55 "
                "AND NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'}) "
                "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
                "ORDER BY score DESC",
                emb=emb,
            )
            for r in result:
                row = dict(r)
                papers_by_id[row["id"]] = row
        except Exception as exc:
            log.debug("Semantic pre-fetch failed (non-fatal) | %s", exc)

    # Recency fallback — fills gaps when vector index is cold or sparse
    cypher_papers = (
        "MATCH (p:Paper) WHERE NOT (p)-[:TAGGED]->(:Tag {name: 'from-references'}) "
        "RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary "
        "ORDER BY p.created_at DESC LIMIT 10"
    )
    for r in session.run(cypher_papers):
        row = dict(r)
        if row["id"] not in papers_by_id:
            papers_by_id[row["id"]] = row

    # Blog posts
    cypher_posts = (
        "MATCH (bp:BlogPost) WHERE bp.imported = true "
        "RETURN bp.id AS id, bp.title AS title, bp.description AS abstract, bp.summary AS summary "
        "ORDER BY bp.created_at DESC LIMIT 5"
    )
    posts = [dict(r) for r in session.run(cypher_posts)]

    return list(papers_by_id.values()) + posts


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
            yield _sse({
                "type": "step",
                "description": "No @mentions — using hybrid retrieval (semantic + recency) for context",
                "cypher": None,
                "count": None,
            })
            papers = _fallback_all_papers(session, question=body.question)
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

    # Enrich papers with their notes + conversation summaries
    with driver.session() as session:
        for p in all_papers:
            snippets = get_paper_context_snippets(driver, p["id"])
            if snippets.get("note"):
                p["_note"] = snippets["note"]
            if snippets.get("conversations"):
                conv_texts = []
                for conv in snippets["conversations"]:
                    msgs = conv.get("messages") or []
                    if not msgs:
                        continue
                    if conv.get("compacted") and msgs:
                        conv_texts.append(f"[Conversation: {conv['title']}]\n{msgs[0]['content']}")
                    else:
                        excerpt = "\n".join(
                            f"{m['role'].upper()}: {m['content'][:400]}"
                            for m in msgs[-6:]  # last 3 exchanges
                        )
                        conv_texts.append(f"[Conversation: {conv['title']}]\n{excerpt}")
                if conv_texts:
                    p["_conversations"] = "\n\n".join(conv_texts)

    paper_infos = []
    for i, p in enumerate(all_papers):
        text_parts = [p.get("title"), p.get("abstract"), p.get("summary"),
                      p.get("_note"), p.get("_conversations")]
        text = " ".join(filter(None, text_parts))
        tok = estimate_tokens(text)
        paper_infos.append({
            "id": p["id"],
            "title": p.get("title") or "Untitled",
            "tokens": tok,
            "color": _PAPER_COLORS[i % len(_PAPER_COLORS)],
            "has_note": bool(p.get("_note")),
            "has_conversations": bool(p.get("_conversations")),
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

    # Step 5: stream Claude response (agentic — may yield step + token events)
    yield _sse({"type": "step", "description": "Sending to Claude…", "cypher": None, "count": None})

    full_answer = ""
    try:
        for event in knowledge_chat_stream(
            question=body.question,
            history=[{"role": m["role"], "content": m["content"]} for m in body.history],
            papers=all_papers,
            model=body.model,
            use_web=body.use_web,
            driver=driver,
        ):
            if event.get("type") == "token":
                full_answer += event.get("text", "")
            yield _sse(event)
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
    """Sliding-window compaction: keep the last 6 messages verbatim and replace
    older messages with a structured working-memory JSON block + prose summary.
    This preserves specific paper titles, numbers, and claims that a pure
    prose summary would elide."""
    import json as _json
    import re as _re
    from services.ai import _personal_client, _load_prompt

    msgs = get_messages(get_driver(), conv_id)
    if not msgs:
        raise HTTPException(status_code=404, detail="Conversation not found or empty")

    # Build a compact transcript of the messages to be summarised (all but last 6)
    msgs_to_summarise = msgs[:-6] if len(msgs) > 6 else msgs
    transcript = "\n\n".join(
        f"{m['role'].upper()}: {m['content'][:600]}" for m in msgs_to_summarise
    )

    # Extract structured working memory via Claude Haiku
    extraction_prompt = (
        "Extract a structured working memory from this research conversation. "
        "Return a JSON object with exactly these keys:\n"
        '  "papers_discussed": [list of paper titles mentioned],\n'
        '  "key_findings": [specific empirical claims or numbers noted],\n'
        '  "open_questions": [unresolved questions or threads],\n'
        '  "decisions": [conclusions or directions agreed upon]\n'
        "Return only the JSON object, no other text.\n\n"
        f"Conversation:\n{transcript[:8000]}"
    )
    prose_prompt = (
        "Write a 3-5 sentence summary of the following research conversation, "
        "focusing on what was established and what remains open.\n\n"
        f"Conversation:\n{transcript[:8000]}"
    )

    try:
        client = _personal_client()
        wm_response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": extraction_prompt}],
        )
        wm_text = wm_response.content[0].text.strip()
        # Validate JSON; fall back to empty structure on parse failure
        match = _re.search(r"\{.*\}", wm_text, _re.DOTALL)
        working_memory_json = match.group() if match else "{}"
        _json.loads(working_memory_json)  # validate

        prose_response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prose_prompt}],
        )
        prose_summary = prose_response.content[0].text.strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Compaction failed: {exc}")

    return compact_conversation_sliding_window(
        get_driver(), conv_id,
        working_memory_json=working_memory_json,
        prose_summary=prose_summary,
        keep_last_n=6,
    )


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conv(conv_id: str):
    delete_conversation(get_driver(), conv_id)
