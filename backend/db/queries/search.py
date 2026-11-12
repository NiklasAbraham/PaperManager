"""Search over Paper nodes: ranked text search, or filters only.

With a query the work is done by services.library_search.engine (ranking across titles,
authors, topics, tags, venue, abstracts, notes, highlights, claims and full text; see
.specs/012_search.md). Without one, a plain filtered MATCH ordered by ``sort`` that returns
the same display rows as a ranked hit (authors, projects, has_note, ...), paged on the server.
"""
from __future__ import annotations

from neo4j import Driver

from services.library_search.engine import (
    Filters,
    _POOL,
    display_papers,
    filter_clause,
    search,
)

# ORDER BY of the filter-only listing. Missing ratings / citation counts / years sort last
# (in Neo4j null is the largest value, so a plain DESC would put them first).
_ORDER = {
    "date_desc": "p.created_at DESC",
    "date_asc": "p.created_at ASC",
    "year_desc": "p.year IS NULL, p.year DESC, p.created_at DESC",
    "year_asc": "p.year ASC, p.created_at DESC",
    "title_asc": "toLower(p.title) ASC, p.id ASC",
    "rating_desc": "p.rating IS NULL, p.rating DESC, p.created_at DESC",
    "citations_desc": "p.citation_count IS NULL, p.citation_count DESC, p.created_at DESC",
    "updated_desc": "coalesce(p.updated_at, p.created_at) DESC, p.created_at DESC",
}


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
    *,
    venue: str | None = None,
    include_references: bool = True,
    sort: str = "relevance",
    mode: str = "lexical",
    max_snippets: int = 2,
    added_after: str | None = None,
    added_before: str | None = None,
    has_pdf: bool | None = None,
    has_text: bool | None = None,
    has_note: bool | None = None,
    has_highlights: bool | None = None,
    document_type: str | None = None,
    rating_min: int | None = None,
    cache: bool = False,
) -> dict:
    """Return ``{"results": [...], "total": int, ...}``.

    With *q*: ranked hits, each with ``score``, ``matched_in`` (coarse, e.g. "note+paper"),
    ``matched_fields``, ``matches``, ``snippets`` and ``title_marks``; the response adds
    ``mode``, ``relaxed``, ``semantic``, ``failed_sources``, ``took_ms`` and ``cached``.
    Without *q*: the filtered papers (``matched_in`` "filter", ``score`` 0), newest first
    unless *sort* says otherwise, with the display fields of a ranked hit. ``total`` is the
    number of papers passing the filters. *cache* keeps a ranked answer for a minute.
    """
    filters = Filters(
        tag=tag, topic=topic, project_id=project_id, person_id=person_id, venue=venue,
        year_min=year_min, year_max=year_max, reading_status=reading_status,
        bookmarked=bookmarked, include_references=include_references,
        added_after=added_after, added_before=added_before, has_pdf=has_pdf, has_text=has_text,
        has_note=has_note, has_highlights=has_highlights, document_type=document_type,
        rating_min=rating_min,
    )
    if q and q.strip():
        return search(driver, q, filters, skip=skip, limit=limit, sort=sort, mode=mode,
                      max_snippets=max_snippets, cache=cache)
    return _filter_search(driver, filters, skip, limit, sort)


def _run(driver: Driver, cypher: str, params: dict) -> list:
    with driver.session() as session:
        return [dict(r) for r in session.run(cypher, **params)]


def _filter_search(driver: Driver, f: Filters, skip: int, limit: int, sort: str = "date_desc") -> dict:
    """Filter-only search: the ids of the page (and the count of all matches) come from
    two small queries run side by side; the display fields are then loaded for those ids
    only, so no ``raw_text`` ever leaves Neo4j."""
    where, params = filter_clause(f)
    order = _ORDER.get(sort, _ORDER["date_desc"])
    skip, limit = max(0, int(skip)), max(1, min(int(limit), 2000))
    total_f = _POOL.submit(_run, driver, f"MATCH (p:Paper) WHERE {where} RETURN count(p) AS c", params)
    page = _run(
        driver,
        f"MATCH (p:Paper) WHERE {where} WITH p ORDER BY {order} SKIP $skip LIMIT $limit RETURN p.id AS id",
        {**params, "skip": skip, "limit": limit})
    ids = [r["id"] for r in page]
    by_id = display_papers(driver, ids)
    rows = []
    for pid in ids:
        d = by_id.get(pid)
        if d is None:
            continue
        d["score"] = 0.0
        d["matched_in"] = "filter"
        rows.append(d)
    count = total_f.result()[0]["c"]
    return {"results": rows, "total": max(count, len(rows)), "cached": False}
