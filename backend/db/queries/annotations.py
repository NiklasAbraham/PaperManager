import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_annotations(driver: Driver, paper_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $pid})-[:HAS_ANNOTATION]->(a:Annotation)
            RETURN a ORDER BY a.page_number ASC, a.created_at ASC
            """,
            pid=paper_id,
        )
        return [dict(record["a"]) for record in result]


def create_annotation(
    driver: Driver,
    paper_id: str,
    page_number: int,
    highlighted_text: str,
    color: str,
    note: str,
    position_json: str,
) -> dict:
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $pid})
            CREATE (a:Annotation {
                id: $id,
                page_number: $page_number,
                highlighted_text: $highlighted_text,
                color: $color,
                note: $note,
                position_json: $position_json,
                created_at: $now,
                updated_at: $now
            })
            CREATE (p)-[:HAS_ANNOTATION]->(a)
            RETURN a
            """,
            pid=paper_id,
            id=str(uuid.uuid4()),
            page_number=page_number,
            highlighted_text=highlighted_text,
            color=color,
            note=note,
            position_json=position_json,
            now=now,
        )
        return dict(result.single()["a"])


def update_annotation(
    driver: Driver,
    annotation_id: str,
    note: str | None,
    color: str | None,
) -> dict | None:
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Annotation {id: $id})
            SET a.note = coalesce($note, a.note),
                a.color = coalesce($color, a.color),
                a.updated_at = $now
            RETURN a
            """,
            id=annotation_id,
            note=note,
            color=color,
            now=now,
        )
        record = result.single()
        return dict(record["a"]) if record else None


def delete_annotation(driver: Driver, annotation_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Annotation {id: $id})
            DETACH DELETE a
            RETURN count(*) AS deleted
            """,
            id=annotation_id,
        )
        record = result.single()
        return bool(record and record["deleted"] > 0)
