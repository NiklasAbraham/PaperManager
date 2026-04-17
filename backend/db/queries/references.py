import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_or_link_reference(driver: Driver, citing_paper_id: str, ref: dict) -> dict:
    """
    MERGE a Paper node for the reference (by DOI if available, else title),
    then create a CITES relationship from the citing paper.
    Returns the reference paper node.
    """
    ref_id = str(uuid.uuid4())
    doi = ref.get("doi") or ref.get("arxiv_id")

    with driver.session() as session:
        if doi:
            # Merge by DOI so we don't duplicate known papers
            result = session.run(
                """
                MERGE (ref:Paper {doi: $doi})
                ON CREATE SET
                  ref.id = $id,
                  ref.title = $title,
                  ref.year = $year,
                  ref.created_at = $now,
                  ref.updated_at = $now
                ON MATCH SET
                  ref.title = CASE WHEN ref.title IS NULL OR ref.title = ''
                               THEN $title ELSE ref.title END,
                  ref.year = CASE WHEN ref.year IS NULL THEN $year ELSE ref.year END,
                  ref.updated_at = $now
                WITH ref
                MATCH (citing:Paper {id: $citing_id})
                MERGE (citing)-[:CITES]->(ref)
                RETURN ref
                """,
                doi=doi,
                id=ref_id,
                title=ref.get("title", ""),
                year=ref.get("year"),
                now=_now(),
                citing_id=citing_paper_id,
            )
        else:
            # Fall back to merge by title (case-insensitive)
            result = session.run(
                """
                MERGE (ref:Paper {title: $title})
                ON CREATE SET
                  ref.id = $id,
                  ref.year = $year,
                  ref.created_at = $now,
                  ref.updated_at = $now
                ON MATCH SET
                  ref.year = CASE WHEN ref.year IS NULL THEN $year ELSE ref.year END,
                  ref.updated_at = $now
                WITH ref
                MATCH (citing:Paper {id: $citing_id})
                MERGE (citing)-[:CITES]->(ref)
                RETURN ref
                """,
                title=ref.get("title", ""),
                id=ref_id,
                year=ref.get("year"),
                now=_now(),
                citing_id=citing_paper_id,
            )
        record = result.single()
        return dict(record["ref"]) if record else {}


def get_references(driver: Driver, paper_id: str) -> list[dict]:
    """Return papers that this paper cites (outgoing CITES)."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $id})-[:CITES]->(ref:Paper)
            RETURN ref ORDER BY ref.year DESC
            """,
            id=paper_id,
        )
        return [dict(r["ref"]) for r in result]


def get_cited_by(driver: Driver, paper_id: str) -> list[dict]:
    """Return papers that cite this paper (incoming CITES)."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (citing:Paper)-[:CITES]->(p:Paper {id: $id})
            RETURN citing ORDER BY citing.year DESC
            """,
            id=paper_id,
        )
        return [dict(r["citing"]) for r in result]
