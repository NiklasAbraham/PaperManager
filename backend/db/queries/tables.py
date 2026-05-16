"""Neo4j queries for Table nodes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_table(driver: Driver, data: dict) -> dict:
    """Create a Table node linked to its Paper and return the node dict."""
    tbl_id = str(uuid.uuid4())
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})
            CREATE (t:Table {
                id: $id,
                paper_id: $paper_id,
                table_number: $table_number,
                caption: $caption,
                markdown_content: $markdown_content,
                page_number: $page_number,
                created_at: $created_at
            })
            CREATE (p)-[:HAS_TABLE]->(t)
            RETURN t
            """,
            id=tbl_id,
            paper_id=data["paper_id"],
            table_number=data.get("table_number"),
            caption=data.get("caption"),
            markdown_content=data.get("markdown_content", ""),
            page_number=data.get("page_number", 0),
            created_at=now,
        )
        record = result.single()
        return dict(record["t"]) if record else {}


def list_tables(driver: Driver, paper_id: str) -> list[dict]:
    """Return all tables for a paper ordered by page then table number."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_TABLE]->(t:Table)
            RETURN t
            ORDER BY t.page_number ASC, coalesce(t.table_number, 9999) ASC
            """,
            paper_id=paper_id,
        )
        return [dict(r["t"]) for r in result]


def delete_tables_for_paper(driver: Driver, paper_id: str) -> int:
    """Delete all tables for a paper. Returns count deleted."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_TABLE]->(t:Table)
            WITH t, t.id AS tid
            DETACH DELETE t
            RETURN count(tid) AS deleted
            """,
            paper_id=paper_id,
        )
        record = result.single()
        return record["deleted"] if record else 0
