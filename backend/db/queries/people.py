import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_person(driver: Driver, data: dict) -> dict:
    props = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", ""),
        "affiliation": data.get("affiliation"),
        "email": data.get("email"),
        "created_at": _now(),
    }
    with driver.session() as session:
        result = session.run("CREATE (p:Person $props) RETURN p", props=props)
        return dict(result.single()["p"])


def get_or_create_person(driver: Driver, name: str) -> dict:
    """Lookup by name (case-insensitive), create if not found."""
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person) WHERE toLower(p.name) = toLower($name) RETURN p LIMIT 1",
            name=name,
        )
        record = result.single()
        if record:
            return dict(record["p"])
    return create_person(driver, {"name": name})


def get_person(driver: Driver, person_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run("MATCH (p:Person {id: $id}) RETURN p", id=person_id)
        record = result.single()
        return dict(record["p"]) if record else None


def list_people(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run("MATCH (p:Person) RETURN p ORDER BY p.name")
        return [dict(r["p"]) for r in result]


def delete_person(driver: Driver, person_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person {id: $id}) DETACH DELETE p RETURN count(p) AS deleted",
            id=person_id,
        )
        return result.single()["deleted"] > 0


def link_author(driver: Driver, paper_id: str, person_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (paper:Paper {id: $pid}), (person:Person {id: $peid})
            MERGE (paper)-[:AUTHORED_BY]->(person)
            """,
            pid=paper_id,
            peid=person_id,
        )


def link_involves(driver: Driver, paper_id: str, person_id: str, role: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (paper:Paper {id: $pid}), (person:Person {id: $peid})
            MERGE (paper)-[r:INVOLVES {role: $role}]->(person)
            """,
            pid=paper_id,
            peid=person_id,
            role=role,
        )


def link_specializes(driver: Driver, person_id: str, topic_id: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (person:Person {id: $pid}), (topic:Topic {id: $tid})
            MERGE (person)-[:SPECIALIZES_IN]->(topic)
            """,
            pid=person_id,
            tid=topic_id,
        )


def get_papers_by_person(driver: Driver, person_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (paper:Paper)-[r:AUTHORED_BY|INVOLVES]->(person:Person {id: $id})
            RETURN paper, type(r) AS rel_type,
                   CASE WHEN type(r) = 'INVOLVES' THEN r.role ELSE null END AS role
            ORDER BY paper.created_at DESC
            """,
            id=person_id,
        )
        papers = []
        for r in result:
            p = dict(r["paper"])
            p["_rel_type"] = r["rel_type"]
            p["_role"] = r["role"]
            papers.append(p)
        return papers


def get_specialties(driver: Driver, person_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person {id: $id})-[:SPECIALIZES_IN]->(t:Topic) RETURN t",
            id=person_id,
        )
        return [dict(r["t"]) for r in result]
