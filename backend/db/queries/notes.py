import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_paper_note(driver: Driver, paper_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper {id: $pid})-[:HAS_NOTE]->(n:Note) RETURN n",
            pid=paper_id,
        )
        record = result.single()
        return dict(record["n"]) if record else None


def upsert_note(driver: Driver, paper_id: str, content: str) -> dict:
    """Create note if it doesn't exist, update content if it does."""
    now = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $pid})
            MERGE (p)-[:HAS_NOTE]->(n:Note)
            ON CREATE SET n.id = $id, n.created_at = $now
            SET n.content = $content, n.updated_at = $now
            RETURN n
            """,
            pid=paper_id,
            id=str(uuid.uuid4()),
            content=content,
            now=now,
        )
        return dict(result.single()["n"])


def set_mentions(driver: Driver, note_id: str, person_names: list[str], topic_names: list[str]):
    """Replace all MENTIONS relationships on this note."""
    # Use separate sessions per operation to ensure each write is committed.
    with driver.session() as session:
        session.run(
            "MATCH (n:Note {id: $id})-[r:MENTIONS]->() DELETE r",
            id=note_id,
        ).consume()

    for name in person_names:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (p:Person)
                WHERE toLower(p.name) = toLower($name)
                   OR toLower(p.name) CONTAINS toLower($name)
                RETURN p.id AS pid
                ORDER BY size(p.name) ASC
                LIMIT 1
                """,
                name=name,
            )
            record = result.single()
            if not record:
                continue
        with driver.session() as session:
            session.run(
                """
                MATCH (n:Note {id: $nid}), (p:Person {id: $pid})
                MERGE (n)-[:MENTIONS]->(p)
                """,
                nid=note_id,
                pid=record["pid"],
            ).consume()

    for name in topic_names:
        with driver.session() as session:
            session.run(
                """
                MERGE (t:Topic {name: $name})
                ON CREATE SET t.id = $id
                WITH t
                MATCH (n:Note {id: $nid})
                MERGE (n)-[:MENTIONS]->(t)
                """,
                name=name,
                id=str(uuid.uuid4()),
                nid=note_id,
            ).consume()
