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
        result = session.run(
            """
            MATCH (p:Person)
            OPTIONAL MATCH (paper:Paper)-[:AUTHORED_BY|INVOLVES]->(p)
            RETURN p, count(DISTINCT paper) AS paper_count
            ORDER BY p.name
            """
        )
        rows = []
        for r in result:
            d = dict(r["p"])
            d["paper_count"] = r["paper_count"]
            rows.append(d)
        return rows


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


def unlink_author(driver: Driver, paper_id: str, person_id: str):
    with driver.session() as session:
        session.run(
            "MATCH (paper:Paper {id: $pid})-[r:AUTHORED_BY]->(person:Person {id: $peid}) DELETE r",
            pid=paper_id, peid=person_id,
        )


def get_authors_for_paper(driver: Driver, paper_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (paper:Paper {id: $id})-[:AUTHORED_BY]->(person:Person) RETURN person",
            id=paper_id,
        )
        return [dict(r["person"]) for r in result]


def get_involves_for_paper(driver: Driver, paper_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (paper:Paper {id: $id})-[r:INVOLVES]->(person:Person) "
            "RETURN person, r.role AS role",
            id=paper_id,
        )
        rows = []
        for record in result:
            d = dict(record["person"])
            d["role"] = record["role"]
            rows.append(d)
        return rows


def unlink_involves(driver: Driver, paper_id: str, person_id: str, role: str | None = None):
    with driver.session() as session:
        if role:
            session.run(
                "MATCH (paper:Paper {id: $pid})-[r:INVOLVES {role: $role}]->(person:Person {id: $peid}) DELETE r",
                pid=paper_id, peid=person_id, role=role,
            )
        else:
            session.run(
                "MATCH (paper:Paper {id: $pid})-[r:INVOLVES]->(person:Person {id: $peid}) DELETE r",
                pid=paper_id, peid=person_id,
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


def get_or_create_person_with_affiliation(driver: Driver, name: str, affiliation: str | None, s2_author_id: str | None = None) -> dict:
    """Lookup by name; create if not found. If found and affiliation is missing, fill it in.
    Also updates s2_author_id if provided and not already set.
    
    Note: affiliation is always included in the props dict (even if None) for consistency with
    the original behavior, while s2_author_id is only included if it has a non-None value.
    """
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person) WHERE toLower(p.name) = toLower($name) RETURN p LIMIT 1",
            name=name,
        )
        record = result.single()
        if record:
            person = dict(record["p"])
            updates = {}
            if affiliation and not person.get("affiliation"):
                updates["affiliation"] = affiliation
            if s2_author_id and not person.get("s2_author_id"):
                updates["s2_author_id"] = s2_author_id
            if updates:
                session.run(
                    "MATCH (p:Person {id: $id}) SET p += $props",
                    id=person["id"], props=updates,
                )
                person.update(updates)
            return person
    props = {"name": name, "affiliation": affiliation}
    if s2_author_id:
        props["s2_author_id"] = s2_author_id
    return create_person(driver, props)


def set_person_tracked(driver: Driver, person_id: str, tracked: bool) -> dict:
    """Set tracked status for a person."""
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person {id: $id}) SET p.tracked = $tracked RETURN p",
            id=person_id, tracked=tracked,
        )
        record = result.single()
        if not record:
            raise ValueError(f"Person {person_id} not found")
        return dict(record["p"])


def list_tracked_people(driver: Driver) -> list[dict]:
    """Return all people with tracked=true."""
    with driver.session() as session:
        result = session.run("MATCH (p:Person {tracked: true}) RETURN p ORDER BY p.name")
        return [dict(r["p"]) for r in result]


def update_person_props(driver: Driver, person_id: str, props: dict) -> dict | None:
    """Set arbitrary properties on a Person node, skipping None values."""
    clean = {k: v for k, v in props.items() if v is not None}
    if not clean:
        return get_person(driver, person_id)
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person {id: $id}) SET p += $props RETURN p",
            id=person_id,
            props=clean,
        )
        record = result.single()
        return dict(record["p"]) if record else None


def get_person_library_dois(driver: Driver, person_id: str) -> set[str]:
    """Return set of DOIs for papers authored by this person that are in the library."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (paper:Paper)-[:AUTHORED_BY]->(p:Person {id: $id})
            WHERE paper.doi IS NOT NULL
            RETURN collect(paper.doi) AS dois
            """,
            id=person_id,
        )
        record = result.single()
        return set(record["dois"]) if record else set()
