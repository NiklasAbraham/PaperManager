"""Neo4j queries for Chapter nodes (book support)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_chapter(driver: Driver, data: dict) -> dict:
    """Create a Chapter node linked to its Paper and return the node dict."""
    chapter_id = str(uuid.uuid4())
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})
            CREATE (c:Chapter {
                id: $id,
                paper_id: $paper_id,
                number: $number,
                title: $title,
                level: $level,
                text: $text,
                summary: $summary,
                start_page: $start_page,
                end_page: $end_page,
                created_at: $created_at,
                updated_at: $updated_at
            })
            CREATE (p)-[:HAS_CHAPTER]->(c)
            RETURN c
            """,
            id=chapter_id,
            paper_id=data["paper_id"],
            number=data.get("number", 0),
            title=data.get("title", ""),
            level=data.get("level", 1),
            text=data.get("text", ""),
            summary=data.get("summary"),
            start_page=data.get("start_page"),
            end_page=data.get("end_page"),
            created_at=now,
            updated_at=now,
        )
        record = result.single()
        return dict(record["c"]) if record else {}


def list_chapters(driver: Driver, paper_id: str) -> list[dict]:
    """Return all chapters for a paper ordered by number."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_CHAPTER]->(c:Chapter)
            RETURN c
            ORDER BY c.number ASC
            """,
            paper_id=paper_id,
        )
        return [dict(r["c"]) for r in result]


def get_chapter(driver: Driver, chapter_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run(
            "MATCH (c:Chapter {id: $id}) RETURN c",
            id=chapter_id,
        )
        record = result.single()
        return dict(record["c"]) if record else None


def update_chapter(driver: Driver, chapter_id: str, data: dict) -> dict | None:
    data["updated_at"] = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Chapter {id: $id})
            SET c += $props
            RETURN c
            """,
            id=chapter_id,
            props=data,
        )
        record = result.single()
        return dict(record["c"]) if record else None


def delete_chapters_for_paper(driver: Driver, paper_id: str) -> int:
    """Delete all chapters for a paper. Returns count deleted."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_CHAPTER]->(c:Chapter)
            WITH c, c.id AS cid
            DETACH DELETE c
            RETURN count(cid) AS deleted
            """,
            paper_id=paper_id,
        )
        record = result.single()
        return record["deleted"] if record else 0
