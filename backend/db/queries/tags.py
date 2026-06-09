import uuid
from neo4j import Driver


def get_or_create_tag(driver: Driver, name: str) -> dict:
    with driver.session() as session:
        result = session.run(
            """
            MERGE (t:Tag {name: $name})
            ON CREATE SET t.id = $id
            RETURN t
            """,
            name=name,
            id=str(uuid.uuid4()),
        )
        return dict(result.single()["t"])


def tag_paper(driver: Driver, paper_id: str, tag_name: str) -> dict:
    tag = get_or_create_tag(driver, tag_name)
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid}), (t:Tag {id: $tid})
            MERGE (p)-[:TAGGED]->(t)
            """,
            pid=paper_id,
            tid=tag["id"],
        )
    return tag


def untag_paper(driver: Driver, paper_id: str, tag_name: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid})-[r:TAGGED]->(t:Tag {name: $name})
            DELETE r
            """,
            pid=paper_id,
            name=tag_name,
        )


def delete_tag(driver: Driver, name: str) -> int:
    """Delete a tag node and all its relationships. Returns number of nodes deleted."""
    with driver.session() as session:
        result = session.run(
            "MATCH (t:Tag {name: $name}) DETACH DELETE t RETURN count(t) AS n",
            name=name,
        )
        return result.single()["n"]


def list_tags(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (t:Tag)
            OPTIONAL MATCH (paper:Paper)-[:TAGGED]->(t)
            OPTIONAL MATCH (per:Person)-[:TAGGED]->(t)
            RETURN t, count(DISTINCT paper) AS paper_count, count(DISTINCT per) AS person_count
            ORDER BY t.name
            """
        )
        return [
            {**dict(r["t"]), "paper_count": r["paper_count"], "person_count": r["person_count"]}
            for r in result
        ]


def get_tags_for_paper(driver: Driver, paper_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper {id: $id})-[:TAGGED]->(t:Tag) RETURN t ORDER BY t.name",
            id=paper_id,
        )
        return [dict(r["t"]) for r in result]


def tag_person(driver: Driver, person_id: str, tag_name: str) -> dict:
    tag = get_or_create_tag(driver, tag_name)
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Person {id: $pid}), (t:Tag {id: $tid})
            MERGE (p)-[:TAGGED]->(t)
            """,
            pid=person_id,
            tid=tag["id"],
        )
    return tag


def untag_person(driver: Driver, person_id: str, tag_name: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Person {id: $pid})-[r:TAGGED]->(t:Tag {name: $name})
            DELETE r
            """,
            pid=person_id,
            name=tag_name,
        )


def get_tags_for_person(driver: Driver, person_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Person {id: $id})-[:TAGGED]->(t:Tag) RETURN t ORDER BY t.name",
            id=person_id,
        )
        return [dict(r["t"]) for r in result]


def papers_by_tag(driver: Driver, tag_name: str) -> list[dict]:
    from db.queries.visibility import paper_visibility_clause

    vis_clause, vis_params = paper_visibility_clause("p")
    with driver.session() as session:
        result = session.run(
            f"MATCH (p:Paper)-[:TAGGED]->(t:Tag {{name: $name}}) "
            f"WHERE {vis_clause} RETURN p ORDER BY p.created_at DESC",
            name=tag_name,
            **vis_params,
        )
        return [dict(r["p"]) for r in result]
