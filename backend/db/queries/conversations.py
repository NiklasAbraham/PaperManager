"""Neo4j queries for Conversation and Message nodes."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens_approx(text: str) -> int:
    return max(1, len(text) // 4)


def create_conversation(driver: Driver, title: str) -> dict:
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            CREATE (c:Conversation {
                id: $id, title: $title,
                created_at: $now, updated_at: $now,
                compacted: false
            }) RETURN c
            """,
            id=str(uuid.uuid4()), title=title, now=now,
        )
        return dict(result.single()["c"])


def update_conversation_timestamp(driver: Driver, conv_id: str) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (c:Conversation {id: $id}) SET c.updated_at = $now",
            id=conv_id, now=_now(),
        )


def add_message(
    driver: Driver,
    conv_id: str,
    role: str,
    content: str,
    paper_ids: list[str],
    tokens_used: int = 0,
) -> dict:
    now = _now()
    msg_id = str(uuid.uuid4())
    with driver.session() as session:
        # Create message and link to conversation
        result = session.run(
            """
            MATCH (c:Conversation {id: $conv_id})
            CREATE (m:Message {
                id: $msg_id, role: $role, content: $content,
                tokens_used: $tokens, created_at: $now
            })
            CREATE (c)-[:HAS_MESSAGE]->(m)
            RETURN m
            """,
            conv_id=conv_id, msg_id=msg_id, role=role,
            content=content, tokens=tokens_used, now=now,
        )
        msg = dict(result.single()["m"])

        # Link to referenced papers
        for pid in paper_ids:
            session.run(
                """
                MATCH (m:Message {id: $mid}), (p:Paper {id: $pid})
                MERGE (m)-[:REFERENCES]->(p)
                """,
                mid=msg_id, pid=pid,
            )

    update_conversation_timestamp(driver, conv_id)
    msg["paper_refs"] = paper_ids
    return msg


def list_conversations(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Conversation)
            OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
            RETURN c, count(m) AS message_count
            ORDER BY c.updated_at DESC
            """
        )
        rows = []
        for r in result:
            d = dict(r["c"])
            d["message_count"] = r["message_count"]
            rows.append(d)
        return rows


def get_messages(driver: Driver, conv_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Conversation {id: $id})-[:HAS_MESSAGE]->(m:Message)
            OPTIONAL MATCH (m)-[:REFERENCES]->(p:Paper)
            WITH m, collect(p.id) AS paper_refs
            ORDER BY m.created_at ASC
            RETURN m, paper_refs
            """,
            id=conv_id,
        )
        rows = []
        for r in result:
            d = dict(r["m"])
            d["paper_refs"] = r["paper_refs"]
            rows.append(d)
        return rows


def compact_conversation(driver: Driver, conv_id: str, summary_content: str) -> dict:
    """Replace all messages with a single system summary message (legacy path)."""
    now = _now()
    msg_id = str(uuid.uuid4())
    with driver.session() as session:
        session.run(
            "MATCH (c:Conversation {id: $id})-[:HAS_MESSAGE]->(m:Message) DETACH DELETE m",
            id=conv_id,
        )
        result = session.run(
            """
            MATCH (c:Conversation {id: $conv_id})
            CREATE (m:Message {
                id: $msg_id, role: 'system',
                content: $content, tokens_used: $tokens,
                created_at: $now
            })
            CREATE (c)-[:HAS_MESSAGE]->(m)
            SET c.compacted = true, c.updated_at = $now
            RETURN m
            """,
            conv_id=conv_id, msg_id=msg_id,
            content=summary_content,
            tokens=len(summary_content) // 4,
            now=now,
        )
        msg = dict(result.single()["m"])
        msg["paper_refs"] = []
        return msg


def compact_conversation_sliding_window(
    driver: Driver,
    conv_id: str,
    working_memory_json: str,
    prose_summary: str,
    keep_last_n: int = 6,
) -> dict:
    """Sliding-window compaction: keep the last *keep_last_n* messages verbatim and
    replace all older messages with a single system message containing a structured
    JSON working memory block followed by a prose summary.

    This preserves specific paper titles, numbers, and claims discussed earlier in
    the conversation, which a pure prose summarisation would elide.
    """
    now = _now()
    all_msgs = get_messages(driver, conv_id)
    if not all_msgs:
        return {}

    # Messages to delete: everything except the last keep_last_n
    to_delete = all_msgs[:-keep_last_n] if len(all_msgs) > keep_last_n else []

    system_content = (
        f"## Working memory (structured)\n\n```json\n{working_memory_json}\n```\n\n"
        f"## Summary of earlier conversation\n\n{prose_summary}"
    )
    system_id = str(uuid.uuid4())

    with driver.session() as session:
        # Delete old messages
        for msg in to_delete:
            session.run(
                "MATCH (m:Message {id: $id}) DETACH DELETE m",
                id=msg["id"],
            )
        # Insert the system compaction message at the head of the conversation
        session.run(
            """
            MATCH (c:Conversation {id: $conv_id})
            CREATE (m:Message {
                id: $msg_id, role: 'system',
                content: $content, tokens_used: $tokens,
                created_at: $now
            })
            CREATE (c)-[:HAS_MESSAGE]->(m)
            SET c.compacted = true, c.updated_at = $now
            """,
            conv_id=conv_id, msg_id=system_id,
            content=system_content,
            tokens=len(system_content) // 4,
            now=now,
        )

    # Return the new system message
    result_msg = {
        "id": system_id, "role": "system",
        "content": system_content, "paper_refs": [],
    }
    return result_msg


def delete_conversation(driver: Driver, conv_id: str) -> None:
    with driver.session() as session:
        session.run(
            """
            MATCH (c:Conversation {id: $id})
            OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
            DETACH DELETE c, m
            """,
            id=conv_id,
        )


def rename_conversation(driver: Driver, conv_id: str, title: str) -> dict:
    with driver.session() as session:
        result = session.run(
            "MATCH (c:Conversation {id: $id}) SET c.title = $title RETURN c",
            id=conv_id, title=title,
        )
        row = result.single()
        return dict(row["c"]) if row else {}


# ── Per-paper conversations ────────────────────────────────────────────────────

def create_paper_conversation(driver: Driver, paper_id: str, title: str) -> dict:
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})
            CREATE (c:Conversation {
                id: $id, title: $title, type: 'paper',
                created_at: $now, updated_at: $now,
                compacted: false
            })
            CREATE (c)-[:ABOUT_PAPER]->(p)
            RETURN c
            """,
            id=str(uuid.uuid4()), paper_id=paper_id, title=title, now=now,
        )
        row = result.single()
        if not row:
            raise ValueError(f"Paper {paper_id} not found")
        return dict(row["c"])


def list_paper_conversations(driver: Driver, paper_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Conversation)-[:ABOUT_PAPER]->(p:Paper {id: $paper_id})
            OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
            OPTIONAL MATCH (u:User)-[:STARTED]->(c)
            RETURN c, count(m) AS message_count, u.name AS started_by
            ORDER BY c.updated_at DESC
            """,
            paper_id=paper_id,
        )
        rows = []
        for r in result:
            d = dict(r["c"])
            d["message_count"] = r["message_count"]
            d["started_by"] = r["started_by"]
            rows.append(d)
        return rows


def get_paper_context_snippets(driver: Driver, paper_id: str) -> dict:
    """Return note content + compacted conversation summaries for a paper (for knowledge chat context)."""
    with driver.session() as session:
        # Note
        note_result = session.run(
            "MATCH (n:Note)-[:ABOUT]->(p:Paper {id: $id}) RETURN n.content AS content",
            id=paper_id,
        ).single()
        note = note_result["content"] if note_result else None

        # Conversation summaries (compacted ones) or recent messages
        conv_result = session.run(
            """
            MATCH (c:Conversation)-[:ABOUT_PAPER]->(p:Paper {id: $id})
            OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
            WITH c, m ORDER BY m.created_at ASC
            WITH c, collect(m) AS messages
            RETURN c.title AS title, c.compacted AS compacted,
                   [msg IN messages | {role: msg.role, content: msg.content}] AS messages
            ORDER BY c.updated_at DESC
            LIMIT 5
            """,
            id=paper_id,
        )
        conversations = [dict(r) for r in conv_result]

    return {"note": note, "conversations": conversations}
