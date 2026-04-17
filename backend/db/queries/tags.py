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


def list_tags(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (t:Tag)
            OPTIONAL MATCH (p:Paper)-[:TAGGED]->(t)
            RETURN t, count(p) AS paper_count
            ORDER BY t.name
            """
        )
        return [{**dict(r["t"]), "paper_count": r["paper_count"]} for r in result]


def papers_by_tag(driver: Driver, tag_name: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper)-[:TAGGED]->(t:Tag {name: $name}) RETURN p ORDER BY p.created_at DESC",
            name=tag_name,
        )
        return [dict(r["p"]) for r in result]
