"""Neo4j queries for User nodes and attribution relationships."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_create_user(driver: Driver, name: str) -> dict:
    with driver.session() as session:
        result = session.run(
            """
            MERGE (u:User {name: $name})
            ON CREATE SET u.id = $id, u.created_at = $now
            RETURN u
            """,
            name=name,
            id=str(uuid.uuid4()),
            now=_now(),
        )
        return dict(result.single()["u"])


def list_users(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User)
            OPTIONAL MATCH (u)-[:ADDED]->(p:Paper)
            OPTIONAL MATCH (u)-[:STARTED]->(c:Conversation)
            RETURN u, count(DISTINCT p) AS paper_count, count(DISTINCT c) AS conversation_count
            ORDER BY u.name
            """
        )
        rows = []
        for r in result:
            d = dict(r["u"])
            d["paper_count"] = r["paper_count"]
            d["conversation_count"] = r["conversation_count"]
            rows.append(d)
        return rows


def link_paper_added_by(driver: Driver, paper_id: str, user_name: str) -> None:
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid})
            MERGE (u:User {name: $name})
            ON CREATE SET u.id = $uid, u.created_at = $now
            MERGE (u)-[:ADDED]->(p)
            """,
            pid=paper_id,
            name=user_name,
            uid=str(uuid.uuid4()),
            now=_now(),
        )


def link_conversation_started_by(driver: Driver, conv_id: str, user_name: str) -> None:
    with driver.session() as session:
        session.run(
            """
            MATCH (c:Conversation {id: $cid})
            MERGE (u:User {name: $name})
            ON CREATE SET u.id = $uid, u.created_at = $now
            MERGE (u)-[:STARTED]->(c)
            """,
            cid=conv_id,
            name=user_name,
            uid=str(uuid.uuid4()),
            now=_now(),
        )


def link_note_written_by(driver: Driver, note_id: str, user_name: str) -> None:
    with driver.session() as session:
        session.run(
            """
            MATCH (n:Note {id: $nid})
            MERGE (u:User {name: $name})
            ON CREATE SET u.id = $uid, u.created_at = $now
            MERGE (u)-[:WROTE]->(n)
            """,
            nid=note_id,
            name=user_name,
            uid=str(uuid.uuid4()),
            now=_now(),
        )


def get_paper_added_by(driver: Driver, paper_id: str) -> str | None:
    """Return the name of the user who added this paper, or None."""
    with driver.session() as session:
        result = session.run(
            "MATCH (u:User)-[:ADDED]->(p:Paper {id: $id}) RETURN u.name AS name LIMIT 1",
            id=paper_id,
        ).single()
        return result["name"] if result else None


def get_conversation_started_by(driver: Driver, conv_id: str) -> str | None:
    with driver.session() as session:
        result = session.run(
            "MATCH (u:User)-[:STARTED]->(c:Conversation {id: $id}) RETURN u.name AS name LIMIT 1",
            id=conv_id,
        ).single()
        return result["name"] if result else None


def get_user_conversations_for_ask(driver: Driver, user_name: str, limit: int = 200) -> list[dict]:
    """Return all messages from a user's conversations, newest first, for Claude synthesis."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $name})-[:STARTED]->(c:Conversation)-[:HAS_MESSAGE]->(m:Message)
            OPTIONAL MATCH (c)-[:ABOUT_PAPER]->(p:Paper)
            RETURN m.content AS content, m.role AS role, m.created_at AS ts,
                   c.title AS conv_title, p.title AS paper_title
            ORDER BY m.created_at DESC
            LIMIT $limit
            """,
            name=user_name,
            limit=limit,
        )
        return [dict(r) for r in result]
