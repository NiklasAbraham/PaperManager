import uuid
from neo4j import Driver


def get_or_create_topic(driver: Driver, name: str) -> dict:
    with driver.session() as session:
        result = session.run(
            """
            MERGE (t:Topic {name: $name})
            ON CREATE SET t.id = $id
            RETURN t
            """,
            name=name,
            id=str(uuid.uuid4()),
        )
        return dict(result.single()["t"])


def list_topics(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (t:Topic)
            OPTIONAL MATCH (p:Paper)-[:ABOUT]->(t)
            RETURN t, count(p) AS paper_count
            ORDER BY t.name
            """
        )
        return [{**dict(r["t"]), "paper_count": r["paper_count"]} for r in result]


def link_paper_topic(driver: Driver, paper_id: str, topic_name: str) -> dict:
    topic = get_or_create_topic(driver, topic_name)
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid}), (t:Topic {id: $tid})
            MERGE (p)-[:ABOUT]->(t)
            """,
            pid=paper_id,
            tid=topic["id"],
        )
    return topic


def unlink_paper_topic(driver: Driver, paper_id: str, topic_name: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid})-[r:ABOUT]->(t:Topic {name: $name})
            DELETE r
            """,
            pid=paper_id,
            name=topic_name,
        )


def papers_by_topic(driver: Driver, topic_name: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper)-[:ABOUT]->(t:Topic {name: $name}) RETURN p ORDER BY p.created_at DESC",
            name=topic_name,
        )
        return [dict(r["p"]) for r in result]


def link_related_topics(driver: Driver, name_a: str, name_b: str):
    topic_a = get_or_create_topic(driver, name_a)
    topic_b = get_or_create_topic(driver, name_b)
    with driver.session() as session:
        session.run(
            """
            MATCH (a:Topic {id: $aid}), (b:Topic {id: $bid})
            MERGE (a)-[:RELATED_TO]-(b)
            """,
            aid=topic_a["id"],
            bid=topic_b["id"],
        )
