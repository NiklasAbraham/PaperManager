"""Neo4j queries for Claim nodes."""
from __future__ import annotations

import logging
from uuid import uuid4

log = logging.getLogger(__name__)

CLAIM_TYPES = {"claim", "hypothesis", "finding", "method", "limitation"}


def create_claims(driver, paper_id: str, claims: list[dict]) -> list[dict]:
    """
    claims: [{"text": str, "type": str}]
    Creates Claim nodes and (Paper)-[:HAS_CLAIM]->(Claim) relationships.
    Uses CREATE — call delete_paper_claims first if re-running.
    """
    created = []
    with driver.session() as session:
        for c in claims:
            claim_id = str(uuid4())
            c_type = c.get("type", "claim")
            if c_type not in CLAIM_TYPES:
                c_type = "claim"
            result = session.run(
                """
                MATCH (p:Paper {id: $paper_id})
                CREATE (c:Claim {id: $id, text: $text, type: $type})
                CREATE (p)-[:HAS_CLAIM]->(c)
                RETURN c
                """,
                paper_id=paper_id,
                id=claim_id,
                text=c["text"].strip(),
                type=c_type,
            )
            record = result.single()
            if record:
                created.append(dict(record["c"]))
    return created


def get_paper_claims(driver, paper_id: str) -> list[dict]:
    """
    MATCH (p:Paper {id: $id})-[:HAS_CLAIM]->(c:Claim)
    RETURN c ORDER BY c.type, c.text
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_CLAIM]->(c:Claim)
            RETURN c
            ORDER BY c.type, c.text
            """,
            paper_id=paper_id,
        )
        return [dict(r["c"]) for r in result]


def delete_paper_claims(driver, paper_id: str) -> int:
    """Delete all Claim nodes for a paper. Returns count deleted."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $paper_id})-[:HAS_CLAIM]->(c:Claim)
            DETACH DELETE c
            RETURN count(c) AS deleted
            """,
            paper_id=paper_id,
        )
        record = result.single()
        return record["deleted"] if record else 0


def search_claims(driver, query: str, limit: int = 20) -> list[dict]:
    """
    Fulltext search on claim_search index.
    Returns [{claim, paper: {id, title}}]
    """
    with driver.session() as session:
        result = session.run(
            """
            CALL db.index.fulltext.queryNodes('claim_search', $query)
            YIELD node AS c, score
            MATCH (p:Paper)-[:HAS_CLAIM]->(c)
            RETURN c AS claim, {id: p.id, title: p.title} AS paper
            ORDER BY score DESC
            LIMIT $limit
            """,
            query=query,
            limit=limit,
        )
        return [
            {"claim": dict(r["claim"]), "paper": dict(r["paper"])} for r in result
        ]
