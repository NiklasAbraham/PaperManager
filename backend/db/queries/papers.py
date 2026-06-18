import re
import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy title matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.lower())).strip()


def _prefer_full_paper(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    for row in rows:
        paper = row.get("p") or {}
        if paper.get("drive_file_id"):
            return dict(paper)
    return dict(rows[0]["p"])


def find_duplicate(
    driver: Driver,
    doi: str | None = None,
    title: str | None = None,
) -> dict | None:
    """
    Return an existing Paper that matches by DOI (exact) or normalized title.
    Returns None if no match found.
    """
    if doi:
        with driver.session() as session:
            rec = session.run(
                "MATCH (p:Paper {doi: $doi}) RETURN p LIMIT 1", doi=doi
            ).single()
            if rec:
                return dict(rec["p"])

    if title:
        norm = _normalize_title(title)
        if not norm:
            return None
        # Case-insensitive exact match first
        with driver.session() as session:
            rows = session.run(
                "MATCH (p:Paper) WHERE toLower(p.title) = toLower($title) RETURN p LIMIT 5",
                title=title,
            ).data()
        preferred = _prefer_full_paper(rows)
        if preferred:
            return preferred

        # Normalized match (strips punctuation) — compare in Python against a
        # small window of recently added papers to avoid full-scan in huge libraries
        with driver.session() as session:
            rows = session.run(
                "MATCH (p:Paper) RETURN p ORDER BY p.created_at DESC LIMIT 2000"
            ).data()
        matched: list[dict] = []
        for row in rows:
            if _normalize_title(row["p"].get("title", "")) == norm:
                matched.append(row)
        preferred = _prefer_full_paper(matched)
        if preferred:
            return preferred

    return None


def _merge_paper_into_keep(driver: Driver, keep_id: str, remove_id: str) -> int:
    if keep_id == remove_id:
        return 0

    with driver.session() as session:
        k = session.run("MATCH (p:Paper {id: $id}) RETURN p.id", id=keep_id).single()
        r = session.run("MATCH (p:Paper {id: $id}) RETURN p.id", id=remove_id).single()
        if not k or not r:
            return 0

        moved = 0

        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:AUTHORED_BY]->(person:Person)
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:AUTHORED_BY]->(person)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:TAGGED]->(tag:Tag)
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:TAGGED]->(tag)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:ABOUT]->(topic:Topic)
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:ABOUT]->(topic)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        res = session.run("""
            MATCH (project:Project)-[rel:CONTAINS]->(remove:Paper {id: $rid})
            MATCH (keep:Paper {id: $kid})
            MERGE (project)-[:CONTAINS]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        res = session.run("""
            MATCH (remove:Paper {id: $rid})-[rel:CITES]->(cited:Paper)
            WHERE cited.id <> $kid
            MATCH (keep:Paper {id: $kid})
            MERGE (keep)-[:CITES]->(cited)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        res = session.run("""
            MATCH (citer:Paper)-[rel:CITES]->(remove:Paper {id: $rid})
            WHERE citer.id <> $kid
            MATCH (keep:Paper {id: $kid})
            MERGE (citer)-[:CITES]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        res = session.run("""
            MATCH (note:Note)-[rel:ABOUT]->(remove:Paper {id: $rid})
            MATCH (keep:Paper {id: $kid})
            MERGE (note)-[:ABOUT]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        res = session.run("""
            MATCH (person:Person)-[rel:INVOLVES]->(remove:Paper {id: $rid})
            MATCH (keep:Paper {id: $kid})
            MERGE (person)-[:INVOLVES]->(keep)
            DELETE rel
            RETURN count(rel) AS n
        """, rid=remove_id, kid=keep_id)
        moved += res.single()["n"]

        session.run("""
            MATCH (p:Paper {id: $rid})
            DETACH DELETE p
        """, rid=remove_id)

    return moved


def merge_reference_stubs_into_paper(
    driver: Driver,
    keep_id: str,
    doi: str | None = None,
    title: str | None = None,
) -> int:
    """
    Merge duplicate reference-only stubs (no PDF) into keep_id and delete stubs.
    Returns the number of moved relationships across all merged stubs.
    """
    stub_ids: list[str] = []

    if doi:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (p:Paper {doi: $doi})
                WHERE p.id <> $keep_id
                  AND (p.drive_file_id IS NULL OR p.drive_file_id = '')
                RETURN p.id AS id
                """,
                doi=doi,
                keep_id=keep_id,
            )
            for r in rows:
                pid = r["id"]
                if pid:
                    stub_ids.append(pid)

    if title:
        norm = _normalize_title(title)
        if norm:
            with driver.session() as session:
                rows = session.run(
                    """
                    MATCH (p:Paper)
                    WHERE p.id <> $keep_id
                      AND (p.drive_file_id IS NULL OR p.drive_file_id = '')
                    RETURN p.id AS id, p.title AS title
                    ORDER BY p.created_at DESC
                    LIMIT 2000
                    """,
                    keep_id=keep_id,
                )
                for row in rows:
                    title_value = row["title"] or ""
                    if _normalize_title(title_value) == norm:
                        pid = row["id"]
                        if pid:
                            stub_ids.append(pid)

    moved_total = 0
    for stub_id in sorted(set(stub_ids)):
        moved_total += _merge_paper_into_keep(driver, keep_id, stub_id)
    return moved_total


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def merge_paper_by_doi(driver: Driver, data: dict) -> dict:
    """
    MERGE by DOI if present (enriches an existing reference stub),
    otherwise fall back to a plain CREATE.
    Returns the paper node dict.
    """
    doi = data.get("doi")
    if not doi:
        return create_paper(driver, data)

    paper_id = str(uuid.uuid4())
    with driver.session() as session:
        result = session.run(
            """
            MERGE (p:Paper {doi: $doi})
            ON CREATE SET
              p.id           = $id,
              p.title        = $title,
              p.year         = $year,
              p.abstract     = $abstract,
              p.summary      = $summary,
              p.drive_file_id = $drive_file_id,
              p.raw_text     = $raw_text,
              p.citation_count = $citation_count,
              p.metadata_source = $metadata_source,
              p.venue        = $venue,
              p.document_type = $document_type,
              p.created_at   = $now,
              p.updated_at   = $now
            ON MATCH SET
              p.title        = CASE WHEN $title <> '' THEN $title ELSE p.title END,
              p.year         = COALESCE($year, p.year),
              p.abstract     = COALESCE($abstract, p.abstract),
              p.summary      = COALESCE($summary, p.summary),
              p.citation_count = COALESCE($citation_count, p.citation_count),
              p.metadata_source = $metadata_source,
              p.venue        = COALESCE($venue, p.venue),
              p.document_type = COALESCE($document_type, p.document_type),
              p.updated_at   = $now
            RETURN p
            """,
            doi=doi,
            id=paper_id,
            title=data.get("title", ""),
            year=data.get("year"),
            abstract=data.get("abstract"),
            summary=data.get("summary"),
            drive_file_id=data.get("drive_file_id"),
            raw_text=data.get("raw_text", ""),
            citation_count=data.get("citation_count"),
            metadata_source=data.get("metadata_source"),
            venue=data.get("venue"),
            document_type=data.get("document_type"),
            now=_now(),
        )
        return dict(result.single()["p"])


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
        "venue": data.get("venue"),
        "document_type": data.get("document_type"),
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
            """
            MATCH (p:Paper {id: $id})
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, head(collect(u)) AS added_user
            RETURN p, added_user.name AS added_by, added_user.color AS added_by_color
            """,
            id=paper_id,
        )
        record = result.single()
        if not record:
            return None
        d = dict(record["p"])
        d["added_by"] = record["added_by"]
        d["added_by_color"] = record["added_by_color"]
        return d


def list_papers(driver: Driver, skip: int = 0, limit: int = 10000) -> list[dict]:
    from db.queries.visibility import paper_visibility_clause

    vis_clause, vis_params = paper_visibility_clause("p")
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (p:Paper)
            WHERE NOT (p)-[:TAGGED]->(:Tag {{name: 'from-references'}})
              AND {vis_clause}
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, head(collect(u)) AS added_user
            RETURN p, added_user.name AS added_by, added_user.color AS added_by_color
            ORDER BY p.created_at DESC SKIP $skip LIMIT $limit
            """,
            skip=skip,
            limit=limit,
            **vis_params,
        )
        rows: list[dict] = []
        for r in result:
            d = dict(r["p"])
            d["added_by"] = r["added_by"]
            d["added_by_color"] = r["added_by_color"]
            rows.append(d)
        return rows


def update_paper(driver: Driver, paper_id: str, data: dict) -> dict | None:
    data["updated_at"] = _now()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $id})
            SET p += $props
            WITH p
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, head(collect(u)) AS added_user
            RETURN p, added_user.name AS added_by, added_user.color AS added_by_color
            """,
            id=paper_id,
            props=data,
        )
        record = result.single()
        if not record:
            return None
        d = dict(record["p"])
        d["added_by"] = record["added_by"]
        d["added_by_color"] = record["added_by_color"]
        return d


def delete_paper(driver: Driver, paper_id: str) -> bool:
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Paper {id: $id}) DETACH DELETE p RETURN count(p) AS deleted",
            id=paper_id,
        )
        return result.single()["deleted"] > 0


def random_paper(driver: Driver, reading_status: str | None = None) -> dict | None:
    """Return a single random Paper node, optionally filtered by reading_status."""
    from db.queries.visibility import paper_visibility_clause

    vis_clause, vis_params = paper_visibility_clause("p")
    with driver.session() as session:
        if reading_status:
            result = session.run(
                f"""
                MATCH (p:Paper)
                WHERE p.reading_status = $status
                  AND NOT ((p)-[:TAGGED]->(:Tag {{name: 'from-references'}}) AND p.drive_file_id IS NULL)
                  AND {vis_clause}
                WITH p, rand() AS r ORDER BY r LIMIT 1
                RETURN p
                """,
                status=reading_status,
                **vis_params,
            )
        else:
            result = session.run(
                f"""
                MATCH (p:Paper)
                WHERE NOT ((p)-[:TAGGED]->(:Tag {{name: 'from-references'}}) AND p.drive_file_id IS NULL)
                  AND {vis_clause}
                WITH p, rand() AS r ORDER BY r LIMIT 1
                RETURN p
                """,
                **vis_params,
            )
        record = result.single()
        return dict(record["p"]) if record else None
