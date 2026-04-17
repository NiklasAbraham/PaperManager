import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_paper(driver: Driver, data: dict) -> dict:
    paper_id = str(uuid.uuid4())
    props = {
        "id": paper_id,
        "title": data.get("title", ""),
        "year": data.get("year"),
        "doi": data.get("doi"),
        "abstract": data.get("abstract"),
        "summary": data.get("summary"),
        "drive_file_id": data.get("drive_file_id"),
        "raw_text": data.get("raw_text"),
        "citation_count": data.get("citation_count"),
        "metadata_source": data.get("metadata_source"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    with driver.session() as session:
        result = session.run(
            "CREATE (p:Paper $props) RETURN p",
            props=props,
        )
        return dict(result.single()["p"])


def get_paper(driver: Driver, paper_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper {id: $id}) RETURN p",
            id=paper_id,
        )
        record = result.single()
        return dict(record["p"]) if record else None


def list_papers(driver: Driver, skip: int = 0, limit: int = 20) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper) RETURN p ORDER BY p.created_at DESC SKIP $skip LIMIT $limit",
            skip=skip,
            limit=limit,
        )
        return [dict(r["p"]) for r in result]


def update_paper(driver: Driver, paper_id: str, data: dict) -> dict | None:
    data["updated_at"] = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $id})
            SET p += $props
            RETURN p
            """,
            id=paper_id,
            props=data,
        )
        record = result.single()
        return dict(record["p"]) if record else None


def delete_paper(driver: Driver, paper_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper {id: $id}) DETACH DELETE p RETURN count(p) AS deleted",
            id=paper_id,
        )
        return result.single()["deleted"] > 0
