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
    year_min: int | None = None,
    year_max: int | None = None,
    reading_status: str | None = None,
    bookmarked: bool | None = None,
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
        results = _fulltext_search(driver, q, tag, topic, project_id, person_id,
                                   year_min, year_max, reading_status, bookmarked,
                                   skip, limit)
    else:
        results = _filter_search(driver, tag, topic, project_id, person_id,
                                 year_min, year_max, reading_status, bookmarked,
                                 skip, limit)

    return {"results": results, "total": len(results)}


# ── helpers ───────────────────────────────────────────────────────────────────

def _fulltext_search(
    driver: Driver,
    q: str,
    tag: str | None,
    topic: str | None,
    project_id: str | None,
    person_id: str | None,
    year_min: int | None,
    year_max: int | None,
    reading_status: str | None,
    bookmarked: bool | None,
    skip: int,
    limit: int,
) -> list[dict]:
    """Search paper_search and note_search fulltext indexes, merge, deduplicate."""
    seen: dict[str, dict] = {}
    fetch_limit = max(skip + limit, limit)

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
              AND ($year_min IS NULL  OR p.year >= $year_min)
              AND ($year_max IS NULL  OR p.year <= $year_max)
              AND ($status IS NULL    OR p.reading_status = $status)
              AND ($bookmarked IS NULL OR p.bookmarked = $bookmarked)
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, score, head(collect(u)) AS added_user
            RETURN p, score, "paper" AS matched_in,
                   added_user.name AS added_by, added_user.color AS added_by_color
            ORDER BY score DESC
            SKIP 0 LIMIT $limit
            """,
            q=q, tag=tag, topic=topic, pid=project_id, person=person_id,
            year_min=year_min, year_max=year_max,
            status=reading_status, bookmarked=bookmarked,
            limit=fetch_limit,
        )
        for r in result:
            _merge_hit(seen, r)

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
              AND ($year_min IS NULL  OR p.year >= $year_min)
              AND ($year_max IS NULL  OR p.year <= $year_max)
              AND ($status IS NULL    OR p.reading_status = $status)
              AND ($bookmarked IS NULL OR p.bookmarked = $bookmarked)
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, score, head(collect(u)) AS added_user
            RETURN p, score, "note" AS matched_in,
                   added_user.name AS added_by, added_user.color AS added_by_color
            ORDER BY score DESC
            SKIP 0 LIMIT $limit
            """,
            q=q, tag=tag, topic=topic, pid=project_id, person=person_id,
            year_min=year_min, year_max=year_max,
            status=reading_status, bookmarked=bookmarked,
            limit=fetch_limit,
        )
        for r in result:
            _merge_hit(seen, r)

    rows = []
    for row in seen.values():
        sources = sorted(row.pop("_matched_in", []))
        row["matched_in"] = "+".join(sources) if sources else "paper"
        rows.append(row)
    rows.sort(key=lambda x: x.get("score", 0), reverse=True)
    return rows[skip: skip + limit]


def _merge_hit(seen: dict[str, dict], row: dict) -> None:
    """Merge one full-text hit into the deduplicated result map."""
    paper = dict(row["p"])
    paper_id = paper["id"]
    score = row["score"]
    matched_in = row["matched_in"]

    existing = seen.get(paper_id)
    if not existing:
        paper["score"] = score
        paper["_matched_in"] = {matched_in}
        seen[paper_id] = paper
        return

    existing["_matched_in"].add(matched_in)
    if score > existing.get("score", 0):
        existing.update(paper)
        existing["score"] = score


def _filter_search(
    driver: Driver,
    tag: str | None,
    topic: str | None,
    project_id: str | None,
    person_id: str | None,
    year_min: int | None,
    year_max: int | None,
    reading_status: str | None,
    bookmarked: bool | None,
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
              AND ($year_min IS NULL  OR p.year >= $year_min)
              AND ($year_max IS NULL  OR p.year <= $year_max)
              AND ($status IS NULL    OR p.reading_status = $status)
              AND ($bookmarked IS NULL OR p.bookmarked = $bookmarked)
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, head(collect(u)) AS added_user
            RETURN p, 0.0 AS score, "filter" AS matched_in,
                   added_user.name AS added_by, added_user.color AS added_by_color
            ORDER BY p.created_at DESC
            SKIP $skip LIMIT $limit
            """,
            tag=tag, topic=topic, pid=project_id, person=person_id,
            year_min=year_min, year_max=year_max,
            status=reading_status, bookmarked=bookmarked,
            skip=skip, limit=limit,
        )
        rows = []
        for r in result:
            d = dict(r["p"])
            d["score"] = r["score"]
            d["matched_in"] = r["matched_in"]
            d["added_by"] = r["added_by"]
            d["added_by_color"] = r["added_by_color"]
            rows.append(d)
        return rows
