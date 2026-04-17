"""Full-text and filter-based search over Paper nodes."""
from __future__ import annotations

from neo4j import Driver


def search_papers(
    driver: Driver,
    q: str | None = None,
    tag: str | None = None,
    topic: str | None = None,
    project_id: str | None = None,
    person_id: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    """Return papers matching the given query and/or filters.

    When *q* is provided, full-text indexes are queried and results are
    ranked by relevance score.  When only filters are given, a plain
    MATCH query is used.

    Returns ``{"results": [...], "total": int}``.
    """
    results: list[dict] = []

    if q:
        results = _fulltext_search(driver, q, tag, topic, project_id, person_id, skip, limit)
    else:
        results = _filter_search(driver, tag, topic, project_id, person_id, skip, limit)

    return {"results": results, "total": len(results)}


# ── helpers ───────────────────────────────────────────────────────────────────

def _fulltext_search(
    driver: Driver,
    q: str,
    tag: str | None,
    topic: str | None,
    project_id: str | None,
    person_id: str | None,
    skip: int,
    limit: int,
) -> list[dict]:
    """Search paper_search and note_search fulltext indexes, merge, deduplicate."""
    seen: dict[str, dict] = {}

    # Paper-level index
    with driver.session() as session:
        result = session.run(
            """
            CALL db.index.fulltext.queryNodes("paper_search", $q)
            YIELD node AS p, score
            WHERE ($tag IS NULL       OR (p)-[:TAGGED]->(:Tag {name: $tag}))
              AND ($topic IS NULL     OR (p)-[:ABOUT]->(:Topic {name: $topic}))
              AND ($pid IS NULL       OR (p)-[:IN_PROJECT]->(:Project {id: $pid}))
              AND ($person IS NULL    OR (p)-[:AUTHORED_BY|INVOLVES]->(:Person {id: $person}))
            RETURN p, score, "paper" AS matched_in
            ORDER BY score DESC
            SKIP $skip LIMIT $limit
            """,
            q=q, tag=tag, topic=topic, pid=project_id, person=person_id,
            skip=skip, limit=limit,
        )
        for r in result:
            d = dict(r["p"])
            d["score"] = r["score"]
            d["matched_in"] = r["matched_in"]
            seen[d["id"]] = d

    # Note-level index — find papers via HAS_NOTE
    with driver.session() as session:
        result = session.run(
            """
            CALL db.index.fulltext.queryNodes("note_search", $q)
            YIELD node AS n, score
            MATCH (p:Paper)-[:HAS_NOTE]->(n)
            WHERE ($tag IS NULL       OR (p)-[:TAGGED]->(:Tag {name: $tag}))
              AND ($topic IS NULL     OR (p)-[:ABOUT]->(:Topic {name: $topic}))
              AND ($pid IS NULL       OR (p)-[:IN_PROJECT]->(:Project {id: $pid}))
              AND ($person IS NULL    OR (p)-[:AUTHORED_BY|INVOLVES]->(:Person {id: $person}))
            RETURN p, score, "note" AS matched_in
            ORDER BY score DESC
            SKIP $skip LIMIT $limit
            """,
            q=q, tag=tag, topic=topic, pid=project_id, person=person_id,
            skip=skip, limit=limit,
        )
        for r in result:
            paper_id = r["p"]["id"]
            if paper_id not in seen:
                d = dict(r["p"])
                d["score"] = r["score"]
                d["matched_in"] = r["matched_in"]
                seen[paper_id] = d

    return sorted(seen.values(), key=lambda x: x.get("score", 0), reverse=True)


def _filter_search(
    driver: Driver,
    tag: str | None,
    topic: str | None,
    project_id: str | None,
    person_id: str | None,
    skip: int,
    limit: int,
) -> list[dict]:
    """Filter-only search — no full-text query."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)
            WHERE ($tag IS NULL       OR (p)-[:TAGGED]->(:Tag {name: $tag}))
              AND ($topic IS NULL     OR (p)-[:ABOUT]->(:Topic {name: $topic}))
              AND ($pid IS NULL       OR (p)-[:IN_PROJECT]->(:Project {id: $pid}))
              AND ($person IS NULL    OR (p)-[:AUTHORED_BY|INVOLVES]->(:Person {id: $person}))
            RETURN p, 0.0 AS score, "filter" AS matched_in
            ORDER BY p.created_at DESC
            SKIP $skip LIMIT $limit
            """,
            tag=tag, topic=topic, pid=project_id, person=person_id,
            skip=skip, limit=limit,
        )
        rows = []
        for r in result:
            d = dict(r["p"])
            d["score"] = r["score"]
            d["matched_in"] = r["matched_in"]
            rows.append(d)
        return rows
