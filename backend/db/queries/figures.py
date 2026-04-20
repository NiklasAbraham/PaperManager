"""Neo4j queries for Figure nodes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_figure(driver: Driver, data: dict) -> dict:
    """Create a Figure node linked to its Paper and return the node dict."""
    fig_id = str(uuid.uuid4())
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})
            CREATE (f:Figure {
                id: $id,
                paper_id: $paper_id,
                figure_number: $figure_number,
                caption: $caption,
                drive_file_id: $drive_file_id,
                page_number: $page_number,
                created_at: $created_at
            })
            CREATE (p)-[:HAS_FIGURE]->(f)
            RETURN f
            """,
            id=fig_id,
            paper_id=data["paper_id"],
            figure_number=data.get("figure_number"),
            caption=data.get("caption"),
            drive_file_id=data["drive_file_id"],
            page_number=data.get("page_number", 0),
            created_at=now,
        )
        record = result.single()
        return dict(record["f"]) if record else {}


def list_figures(driver: Driver, paper_id: str) -> list[dict]:
    """Return all figures for a paper ordered by page then figure number."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_FIGURE]->(f:Figure)
            RETURN f
            ORDER BY f.page_number ASC, f.figure_number ASC
            """,
            paper_id=paper_id,
        )
        return [dict(r["f"]) for r in result]


def get_figure(driver: Driver, figure_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run(
            "MATCH (f:Figure {id: $id}) RETURN f",
            id=figure_id,
        )
        record = result.single()
        return dict(record["f"]) if record else None


def delete_figures_for_paper(driver: Driver, paper_id: str) -> int:
    """Delete all figures for a paper. Returns count deleted."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_FIGURE]->(f:Figure)
            WITH f, f.id AS fid
            DETACH DELETE f
            RETURN count(fid) AS deleted
            """,
            paper_id=paper_id,
        )
        record = result.single()
        return record["deleted"] if record else 0
