"""Neo4j queries for User nodes and attribution relationships."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from neo4j import Driver
from typing import Optional


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
            OPTIONAL MATCH (u)-[:WROTE]->(n:Note)
            RETURN u,
                   count(DISTINCT p) AS paper_count,
                   count(DISTINCT c) AS conversation_count,
                   count(DISTINCT n) AS note_count
            ORDER BY u.name
            """
        )
        rows = []
        for r in result:
            d = dict(r["u"])
            d["paper_count"] = r["paper_count"]
            d["conversation_count"] = r["conversation_count"]
            d["note_count"] = r["note_count"]
            d["connection_count"] = r["paper_count"] + r["conversation_count"] + r["note_count"]
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


def delete_user(driver: Driver, name: str) -> bool:
    with driver.session() as session:
        result = session.run(
            "MATCH (u:User {name: $name}) DETACH DELETE u RETURN count(u) AS deleted",
            name=name,
        )
        return (result.single() or {}).get("deleted", 0) > 0


def create_user_with_password(driver: Driver, name: str, password_hash: str, is_admin: bool = False) -> dict:
    """Create a new user with a password hash."""
    with driver.session() as session:
        result = session.run(
            """
            CREATE (u:User {
                id: $id,
                name: $name,
                password_hash: $password_hash,
                is_admin: $is_admin,
                created_at: $now
            })
            RETURN u
            """,
            id=str(uuid.uuid4()),
            name=name,
            password_hash=password_hash,
            is_admin=is_admin,
            now=_now(),
        )
        return dict(result.single()["u"])


def get_user_by_name(driver: Driver, name: str) -> Optional[dict]:
    """Get a user by name, including password hash for authentication."""
    with driver.session() as session:
        result = session.run(
            "MATCH (u:User {name: $name}) RETURN u",
            name=name,
        )
        row = result.single()
        return dict(row["u"]) if row else None


def get_user_ai_keys(driver: Driver, name: str) -> dict:
    """Get user-scoped AI key settings (raw values, may be empty)."""
    user = get_user_by_name(driver, name)
    if not user:
        return {}
    return {
        "anthropic_api_key": (user.get("anthropic_api_key") or "").strip(),
        "anthropic_work_api_key": (user.get("anthropic_work_api_key") or "").strip(),
        "anthropic_work_base_url": (user.get("anthropic_work_base_url") or "").strip(),
    }


def update_user_ai_keys(
    driver: Driver,
    name: str,
    anthropic_api_key: Optional[str],
    anthropic_work_api_key: Optional[str],
    anthropic_work_base_url: Optional[str],
) -> bool:
    """Update user-scoped AI key settings. Empty values clear the corresponding field."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $name})
            SET u.anthropic_api_key = $anthropic_api_key,
                u.anthropic_work_api_key = $anthropic_work_api_key,
                u.anthropic_work_base_url = $anthropic_work_base_url
            RETURN count(u) AS updated
            """,
            name=name,
            anthropic_api_key=(anthropic_api_key or "").strip() or None,
            anthropic_work_api_key=(anthropic_work_api_key or "").strip() or None,
            anthropic_work_base_url=(anthropic_work_base_url or "").strip() or None,
        )
        return (result.single() or {}).get("updated", 0) > 0


def update_user_password(driver: Driver, name: str, password_hash: str) -> bool:
    """Update a user's password."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $name})
            SET u.password_hash = $password_hash
            RETURN count(u) AS updated
            """,
            name=name,
            password_hash=password_hash,
        )
        return (result.single() or {}).get("updated", 0) > 0


def set_user_admin(driver: Driver, name: str, is_admin: bool = True) -> bool:
    """Set or remove admin status for a user."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $name})
            SET u.is_admin = $is_admin
            RETURN count(u) AS updated
            """,
            name=name,
            is_admin=is_admin,
        )
        return (result.single() or {}).get("updated", 0) > 0


def is_user_admin(driver: Driver, name: str) -> bool:
    """Check if a user has admin privileges."""
    user = get_user_by_name(driver, name)
    return user.get("is_admin", False) if user else False


def rename_user(driver: Driver, old_name: str, new_name: str) -> dict | None:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (u:User {name: $old_name})
            SET u.name = $new_name
            RETURN u
            """,
            old_name=old_name,
            new_name=new_name,
        )
        row = result.single()
        return dict(row["u"]) if row else None


def merge_users(
    driver: Driver,
    user_a: str,
    user_b: str,
    keep_name: str,
    password_source_name: str,
) -> dict:
    """Merge two users into one and keep password from selected source user."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:User {name: $user_a})
            MATCH (b:User {name: $user_b})
            WITH a, b,
                 COUNT { (a)-[:ADDED]->() } + COUNT { (a)-[:STARTED]->() } + COUNT { (a)-[:WROTE]->() } AS a_connections,
                 COUNT { (b)-[:ADDED]->() } + COUNT { (b)-[:STARTED]->() } + COUNT { (b)-[:WROTE]->() } AS b_connections
            RETURN a, b, a_connections, b_connections
            """,
            user_a=user_a,
            user_b=user_b,
        ).single()

        if not result:
            raise ValueError("One or both users do not exist")

        a_node = dict(result["a"])
        b_node = dict(result["b"])
        a_connections = int(result["a_connections"])
        b_connections = int(result["b_connections"])

        if keep_name not in (user_a, user_b):
            raise ValueError("keep_name must be one of the selected users")
        if password_source_name not in (user_a, user_b):
            raise ValueError("password_source_name must be one of the selected users")

        keep_user = a_node if keep_name == user_a else b_node
        remove_name = user_b if keep_name == user_a else user_a
        password_source = a_node if password_source_name == user_a else b_node

        password_hash = password_source.get("password_hash")
        if not password_hash:
            raise ValueError(f"Selected password source user '{password_source_name}' has no password")

        keep_is_admin = bool(keep_user.get("is_admin", False)) or bool(
            (b_node if keep_name == user_a else a_node).get("is_admin", False)
        )

        move_papers = session.run(
            """
            MATCH (keep:User {name: $keep_name})
            MATCH (remove:User {name: $remove_name})-[:ADDED]->(p:Paper)
            WITH keep, collect(DISTINCT p) AS papers
            FOREACH (p IN papers | MERGE (keep)-[:ADDED]->(p))
            RETURN size(papers) AS moved_papers
            """,
            keep_name=keep_name,
            remove_name=remove_name,
        ).single()

        move_conversations = session.run(
            """
            MATCH (keep:User {name: $keep_name})
            MATCH (remove:User {name: $remove_name})-[:STARTED]->(c:Conversation)
            WITH keep, collect(DISTINCT c) AS conversations
            FOREACH (c IN conversations | MERGE (keep)-[:STARTED]->(c))
            RETURN size(conversations) AS moved_conversations
            """,
            keep_name=keep_name,
            remove_name=remove_name,
        ).single()

        move_notes = session.run(
            """
            MATCH (keep:User {name: $keep_name})
            MATCH (remove:User {name: $remove_name})-[:WROTE]->(n:Note)
            WITH keep, collect(DISTINCT n) AS notes
            FOREACH (n IN notes | MERGE (keep)-[:WROTE]->(n))
            RETURN size(notes) AS moved_notes
            """,
            keep_name=keep_name,
            remove_name=remove_name,
        ).single()

        session.run(
            """
            MATCH (keep:User {name: $keep_name})
            SET keep.password_hash = $password_hash,
                keep.is_admin = $is_admin
            """,
            keep_name=keep_name,
            password_hash=password_hash,
            is_admin=keep_is_admin,
        )

        session.run(
            """
            MATCH (remove:User {name: $remove_name})
            DETACH DELETE remove
            """,
            remove_name=remove_name,
        )

        return {
            "kept_user": keep_name,
            "removed_user": remove_name,
            "kept_connection_count": a_connections if keep_name == user_a else b_connections,
            "removed_connection_count": b_connections if keep_name == user_a else a_connections,
            "moved_papers": int(move_papers["moved_papers"] if move_papers else 0),
            "moved_conversations": int(move_conversations["moved_conversations"] if move_conversations else 0),
            "moved_notes": int(move_notes["moved_notes"] if move_notes else 0),
            "password_source": password_source_name,
        }


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
