import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_project(driver: Driver, data: dict) -> dict:
    props = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", ""),
        "description": data.get("description"),
        "status": data.get("status", "active"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    with driver.session() as session:
        result = session.run("CREATE (p:Project $props) RETURN p", props=props)
        return dict(result.single()["p"])


def get_project(driver: Driver, project_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run("MATCH (p:Project {id: $id}) RETURN p", id=project_id)
        record = result.single()
        return dict(record["p"]) if record else None


def list_projects(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (proj:Project)
            OPTIONAL MATCH (p:Paper)-[:IN_PROJECT]->(proj)
            RETURN proj, count(p) AS paper_count
            ORDER BY proj.created_at DESC
            """
        )
        return [{**dict(r["proj"]), "paper_count": r["paper_count"]} for r in result]


def update_project(driver: Driver, project_id: str, data: dict) -> dict | None:
    data["updated_at"] = _now()
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Project {id: $id}) SET p += $props RETURN p",
            id=project_id,
            props=data,
        )
        record = result.single()
        return dict(record["p"]) if record else None


def delete_project(driver: Driver, project_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Project {id: $id}) DETACH DELETE p RETURN count(p) AS deleted",
            id=project_id,
        )
        return result.single()["deleted"] > 0


def add_paper_to_project(driver: Driver, paper_id: str, project_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid}), (proj:Project {id: $projid})
            MERGE (p)-[:IN_PROJECT]->(proj)
            """,
            pid=paper_id,
            projid=project_id,
        )


def remove_paper_from_project(driver: Driver, paper_id: str, project_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid})-[r:IN_PROJECT]->(proj:Project {id: $projid})
            DELETE r
            """,
            pid=paper_id,
            projid=project_id,
        )


def get_project_papers(driver: Driver, project_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project {id: $id}) RETURN p ORDER BY p.created_at DESC",
            id=project_id,
        )
        return [dict(r["p"]) for r in result]


def link_projects(driver: Driver, project_a_id: str, project_b_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (a:Project {id: $aid}), (b:Project {id: $bid})
            MERGE (a)-[:RELATED_TO]-(b)
            """,
            aid=project_a_id,
            bid=project_b_id,
        )
