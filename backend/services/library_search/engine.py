"""Ranked library search over Neo4j: lexical sources, optional semantic blend, snippets.

``search()`` is what ``GET /search`` (via db.queries.search.search_papers) and the MCP tool
``library_search`` call. Per query it runs one Lucene query per source, each already
restricted by the filters and the caller's project visibility, merges the hits per paper,
scores them (services.library_search.ranking), pages, and only then loads display fields,
author names and snippets for the papers on the page. See .specs/012_search.md.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import astuple, dataclass
from datetime import datetime, timedelta, timezone

from neo4j import Driver

from db.queries.visibility import current_user, paper_visibility_clause, project_visibility_clause
from services.library_search import cache as result_cache
from services.library_search.query import (
    ParsedQuery,
    clean,
    lucene_all,
    lucene_any,
    matchers_for,
    mark,
    needles,
    on_fields,
    parse_query,
    snippet,
)
from services.library_search.ranking import (
    Candidate,
    SORTS,
    legacy_matched_in,
    rank,
    fuse,
    hybrid_weights,
    score_candidates,
    sort_candidates,
)

log = logging.getLogger(__name__)

REF_TAG = "from-references"
_K_PAPER = 1000      # hits read from paper_search (title/abstract/summary)
_K_OTHER = 300       # hits read from every other source
_SNIPPET_ORDER = ["note", "highlight", "abstract", "summary", "claim", "fulltext"]
_RAW_TEXT_MAX = 400_000  # characters of raw_text scanned for a full-text snippet
_WINDOW = 1400           # characters of raw_text sent back around the passage
# Paper properties returned per hit (what PaperOut / the frontend's Paper type carry).
_PAPER_FIELDS = ", ".join("." + f for f in (
    "id", "title", "year", "doi", "arxiv_id", "abstract", "summary", "drive_file_id",
    "citation_count", "metadata_source", "created_at", "updated_at", "venue", "reading_status",
    "rating", "bookmarked", "color", "document_type", "published_date"))
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="search-source")


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STORED = "%Y-%m-%dT%H:%M:%S"


def normalize_added(value: str | None, *, before: bool = False) -> str | None:
    """A ``created_at`` bound as a string comparable with the stored ISO timestamps
    (``2026-11-11T19:41:47.120895+00:00``): ``YYYY-MM-DDTHH:MM:SS`` in UTC. Accepts a date
    (``2026-11-12``) or an ISO datetime (``2026-11-12T00:00:00.000Z``, ``...+00:00``,
    ``...+02:00``, no zone = UTC). A date-only upper bound is inclusive of that day, so it
    becomes the next day's midnight (compare with ``<``). Raises ``ValueError``."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        if _DATE_ONLY.match(text):
            d = datetime.strptime(text, "%Y-%m-%d")
            if before:
                d += timedelta(days=1)
            return d.strftime(_STORED)
        d = datetime.fromisoformat(text[:-1] + "+00:00" if text[-1] in "zZ" else text)
    except ValueError:
        raise ValueError(f"not a date or ISO datetime: {value!r} (use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)") from None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d.strftime(_STORED)


@dataclass
class Filters:
    tag: str | None = None
    topic: str | None = None
    project_id: str | None = None
    project: str | None = None          # project name or id (MCP tools)
    person_id: str | None = None
    venue: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    reading_status: str | None = None
    bookmarked: bool | None = None
    include_references: bool = True
    added_after: str | None = None      # date or ISO datetime, on created_at (inclusive)
    added_before: str | None = None     # date (that day included) or ISO datetime (exclusive)
    has_pdf: bool | None = None
    has_text: bool | None = None        # full text extracted
    has_note: bool | None = None
    has_highlights: bool | None = None
    document_type: str | None = None    # paper | book | lecture_deck | news_article
    rating_min: int | None = None


def filter_clause(f: Filters, var: str = "p") -> tuple[str, dict]:
    """Cypher predicate for the filters plus project visibility, and its parameters.

    The long-standing filters keep the ``$x IS NULL OR ...`` shape; the newer ones
    (added_*, has_*, document_type, rating_min) are appended only when set, so an
    unfiltered search runs exactly the query it always did."""
    vis, vis_params = paper_visibility_clause(var)
    # Names and values compare case-insensitively: a filter set from "diffusion models"
    # matches the topic "Diffusion Models".
    parts = [
        f"($tag IS NULL OR EXISTS {{ MATCH ({var})-[:TAGGED]->(_t:Tag) WHERE toLower(_t.name) = toLower($tag) }})",
        f"($topic IS NULL OR EXISTS {{ MATCH ({var})-[:ABOUT]->(_tp:Topic) "
        f"WHERE toLower(_tp.name) = toLower($topic) }})",
        f"($pid IS NULL OR EXISTS {{ ({var})-[:IN_PROJECT]->(:Project {{id: $pid}}) }})",
        f"($project IS NULL OR EXISTS {{ MATCH ({var})-[:IN_PROJECT]->(_pr:Project) "
        f"WHERE _pr.id = $project OR toLower(_pr.name) = toLower($project) }})",
        f"($person IS NULL OR EXISTS {{ ({var})-[:AUTHORED_BY|INVOLVES]->(:Person {{id: $person}}) }})",
        f"($venue IS NULL OR toLower({var}.venue) = toLower($venue))",
        f"($year_min IS NULL OR {var}.year >= $year_min)",
        f"($year_max IS NULL OR {var}.year <= $year_max)",
        # Most papers have no reading_status at all: no status means unread.
        f"($status IS NULL OR toLower(coalesce({var}.reading_status, 'unread')) = toLower($status))",
        f"($bookmarked IS NULL OR coalesce({var}.bookmarked, false) = $bookmarked)",
        f"($refs OR NOT EXISTS {{ ({var})-[:TAGGED]->(:Tag {{name: '{REF_TAG}'}}) }})",
        vis,
    ]
    params = {
        "tag": f.tag, "topic": f.topic, "pid": f.project_id, "project": f.project or None,
        "person": f.person_id, "venue": f.venue, "year_min": f.year_min, "year_max": f.year_max,
        "status": f.reading_status, "bookmarked": f.bookmarked, "refs": bool(f.include_references),
        **vis_params,
    }
    after = normalize_added(f.added_after)
    before = normalize_added(f.added_before, before=True)
    if after is not None:
        parts.append(f"{var}.created_at >= $added_after")
        params["added_after"] = after
    if before is not None:
        parts.append(f"{var}.created_at < $added_before")
        params["added_before"] = before
    if f.has_pdf is not None:
        # drive_file_id is the stored PDF; most reference stubs have none.
        parts.append(f"$has_pdf = ({var}.drive_file_id IS NOT NULL AND {var}.drive_file_id <> '')")
        params["has_pdf"] = bool(f.has_pdf)
    if f.has_text is not None:
        # IS NOT NULL first: it is answered from the property record without reading the
        # string; only the ~475 papers with text are then compared with ''.
        parts.append(f"$has_text = ({var}.raw_text IS NOT NULL AND {var}.raw_text <> '')")
        params["has_text"] = bool(f.has_text)
    if f.has_note is not None:
        parts.append(f"$has_note = EXISTS {{ ({var})-[:HAS_NOTE]->(_n:Note) "
                     f"WHERE trim(coalesce(_n.content, '')) <> '' }}")
        params["has_note"] = bool(f.has_note)
    if f.has_highlights is not None:
        parts.append(f"$has_hl = EXISTS {{ ({var})-[:HAS_ANNOTATION]->() }}")
        params["has_hl"] = bool(f.has_highlights)
    if f.document_type:
        parts.append(f"toLower(coalesce({var}.document_type, 'paper')) = toLower($doctype)")
        params["doctype"] = f.document_type
    if f.rating_min is not None:
        parts.append(f"{var}.rating >= $rating_min")
        params["rating_min"] = int(f.rating_min)
    return " AND ".join(parts), params


# What every source returns per row: only what scoring needs. The fields only a sort needs
# (year, created_at, rating, citation_count, updated_at) are fetched once, for the ranked
# list, when a sort asks for them (``_load_sort_fields``): rows are decoded in pure Python,
# so every column of every duplicate row across the sources costs CPU.
_COMMON = (f"p.id AS id, p.title AS title, "
           f"EXISTS {{ (p)-[:TAGGED]->(:Tag {{name: '{REF_TAG}'}}) }} AS ref, "
           f"COUNT {{ (p)<-[:CITES]-() }} AS cited")


def _sources(pq: ParsedQuery, where: str) -> list[tuple[str, str, dict]]:
    """(source name, Cypher, extra params) for every lexical source of a parsed query."""
    any_q = lucene_any(pq)
    out = [
        ("paper", f"""/*search:paper*/
            CALL db.index.fulltext.queryNodes('paper_search', $lq) YIELD node AS p, score
            WHERE {where}
            RETURN {_COMMON}, score, p.abstract AS abstract, p.summary AS summary
            LIMIT {_K_PAPER}""",
         {"lq": on_fields(any_q, {"title": 4, "abstract": 1, "summary": 0.7})}),
        ("entity", f"""/*search:entity*/
            CALL db.index.fulltext.queryNodes('entity_name_search', $lq) YIELD node AS e, score
            WITH e, score WHERE NOT e:Project AND NOT (e:Tag AND e.name = '{REF_TAG}')
            WITH e, score ORDER BY score DESC LIMIT 200
            MATCH (p:Paper)-[r:AUTHORED_BY|ABOUT|TAGGED]->(e)
            WHERE {where}
            RETURN {_COMMON}, score, type(r) AS rel, e.name AS name
            LIMIT 5000""",
         {"lq": on_fields(any_q, {"name": 1})}),
        ("venue", f"""/*search:venue*/
            CALL db.index.fulltext.queryNodes('paper_text_search', $lq) YIELD node AS p, score
            WHERE {where}
            RETURN {_COMMON}, score, p.venue AS venue
            LIMIT {_K_OTHER}""",
         {"lq": on_fields(any_q, {"venue": 1})}),
        ("fulltext", f"""/*search:fulltext*/
            CALL db.index.fulltext.queryNodes('paper_text_search', $lq) YIELD node AS p, score
            WHERE {where}
            RETURN {_COMMON}, score
            LIMIT {_K_OTHER}""",
         {"lq": on_fields(lucene_all(pq), {"raw_text": 1})}),
        ("note", f"""/*search:note*/
            CALL db.index.fulltext.queryNodes('note_search', $lq) YIELD node AS n, score
            MATCH (p:Paper)-[:HAS_NOTE]->(n)
            WHERE {where}
            RETURN {_COMMON}, score, n.content AS text
            LIMIT {_K_OTHER}""",
         {"lq": any_q}),
        ("highlight", f"""/*search:highlight*/
            CALL db.index.fulltext.queryNodes('annotation_search', $lq) YIELD node AS a, score
            MATCH (p:Paper)-[:HAS_ANNOTATION]->(a)
            WHERE {where}
            RETURN {_COMMON}, score, a.highlighted_text AS text, a.note AS comment,
                   a.page_number AS page
            LIMIT {_K_OTHER}""",
         {"lq": any_q}),
        ("claim", f"""/*search:claim*/
            CALL db.index.fulltext.queryNodes('claim_search', $lq) YIELD node AS c, score
            MATCH (p:Paper)-[:HAS_CLAIM]->(c)
            WHERE {where}
            RETURN {_COMMON}, score, c.text AS text
            LIMIT {_K_OTHER}""",
         {"lq": any_q}),
    ]
    return out


_REL_FIELD = {"AUTHORED_BY": "author", "ABOUT": "topic", "TAGGED": "tag"}


def _new_candidate(r) -> Candidate:
    return Candidate(id=r["id"], title=r["title"] or "", ref=bool(r["ref"]),
                     cited=int(r.get("cited") or 0))


def _candidate(cands: dict[str, Candidate], r) -> Candidate:
    c = cands.get(r["id"])
    if c is None:
        c = cands[r["id"]] = _new_candidate(r)
    return c


def _iso(v) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)


def _run(driver: Driver, cypher: str, params: dict) -> list:
    with driver.session() as s:
        return list(s.run(cypher, **params))


def _collect(rows, source: str, cands: dict[str, Candidate]) -> None:
    for r in rows:
        c = _candidate(cands, r)
        score = r["score"]
        if source == "paper":
            c.add("paper", score)
            for f in ("abstract", "summary"):
                if r[f]:
                    c.add("paper", score, f, r[f], cap=1)
        elif source == "entity":
            fld = _REL_FIELD.get(r["rel"], "tag")
            c.add(fld, score, fld, r["name"], cap=6)
        elif source == "venue":
            c.add("venue", score, "venue", r["venue"], cap=1)
        elif source == "fulltext":
            c.add("fulltext", score)
        elif source == "highlight":
            text = r["text"] or ""
            if r["comment"]:
                text = f"{text} — {r['comment']}" if text else r["comment"]
            c.add("highlight", score, "highlight", text)
            if r["page"] is not None and r["page"] not in c.pages:
                c.pages.append(r["page"])
        else:  # note, claim
            c.add(source, score, source, r["text"])


def _identifier_hits(session, ident: dict, where: str, params: dict,
                     cands: dict[str, Candidate]) -> None:
    if "doi" in ident:
        doi = ident["doi"]
        arxiv = None
        if doi.startswith("10.48550/arxiv."):
            arxiv = doi.split("arxiv.", 1)[1]
    else:
        arxiv = ident["arxiv"]
        doi = f"10.48550/arxiv.{arxiv}"
    rows = session.run(
        f"""/*search:identifier*/
        MATCH (p:Paper)
        WHERE (toLower(p.doi) IN $dois OR ($arxiv IS NOT NULL AND toLower(p.arxiv_id) = $arxiv))
          AND {where}
        RETURN {_COMMON}, 1.0 AS score""",
        dois=[doi] + ([f"arxiv:{arxiv}", arxiv] if arxiv else []), arxiv=arxiv, **params)
    for r in rows:
        _candidate(cands, r).add("identifier", 1.0)


def lexical_candidates(driver: Driver, pq: ParsedQuery, f: Filters) -> tuple[list[Candidate], list[str]]:
    """Every paper any lexical source returns, merged per paper. Also returns the names of
    sources that failed (an index still populating, say) so callers can report them."""
    where, params = filter_clause(f)
    cands: dict[str, Candidate] = {}
    failed: list[str] = []
    if pq.identifier:
        try:
            with driver.session() as s:
                _identifier_hits(s, pq.identifier, where, params, cands)
        except Exception as exc:  # noqa: BLE001
            log.warning("search source identifier failed: %s", exc)
            failed.append("identifier")
        if cands:
            return list(cands.values()), failed
    if not pq.units:
        return [], failed
    # The sources are independent: run them on separate sessions in parallel, then merge
    # in a fixed order so ties break the same way every time.
    sources = _sources(pq, where)
    futures = [(_POOL.submit(_run, driver, cypher, {**params, **extra}), source)
               for source, cypher, extra in sources]
    for fut, source in futures:
        try:
            _collect(fut.result(), source, cands)
        except Exception as exc:  # noqa: BLE001 — one broken source must not fail the search
            log.warning("search source %s failed: %s", source, exc)
            failed.append(source)
    return list(cands.values()), failed


def _semantic_candidates(driver: Driver, q: str, where: str, params: dict,
                         k: int = 200) -> tuple[list[Candidate], float | None]:
    """Nearest papers by embedding that pass the filters, best first and cut at the
    similarity floors, plus the best raw similarity (``None`` without an index)."""
    from services.library_search import semantic

    hits = semantic.query(q, k=k)
    if not hits:
        return [], None
    sims = dict(hits)
    with driver.session() as s:
        rows = s.run(
            f"""/*search:semantic*/
            MATCH (p:Paper) WHERE p.id IN $ids AND {where}
            RETURN {_COMMON}""", ids=list(sims), **params)
        out = []
        for r in rows:
            c = _new_candidate(r)
            c.semantic = sims[r["id"]]
            out.append(c)
    out.sort(key=lambda c: -(c.semantic or 0))
    return semantic.cut(out), hits[0][1]


_DISPLAY_QUERY = """MATCH (p:Paper) WHERE p.id IN $ids
                OPTIONAL MATCH (u:User)-[:ADDED]->(p)
                WITH p, head(collect(u)) AS added_user
                RETURN p.id AS id, p {%s} AS p,
                       added_user.name AS added_by, added_user.color AS added_by_color,
                       [(p)-[:AUTHORED_BY]->(a:Person) | a.name][..12] AS authors,
                       size(coalesce(p.raw_text, '')) AS text_chars,
                       EXISTS { (p)-[:HAS_NOTE]->() } AS has_note,
                       COUNT { (p)-[:HAS_ANNOTATION]->() } AS highlight_count,
                       EXISTS { (p)-[:TAGGED]->(:Tag {name: '%s'}) } AS ref,
                       [(p)-[:IN_PROJECT]->(pr:Project) WHERE %s | pr.name] AS projects"""


def _display_rows(session, ids: list[str]) -> dict:
    proj_vis, proj_params = project_visibility_clause("pr")
    return {r["id"]: r for r in session.run(
        _DISPLAY_QUERY % (_PAPER_FIELDS, REF_TAG, proj_vis), ids=ids, **proj_params)}


def display_fields(r) -> dict:
    """The paper properties and the card fields (authors, added_by, text_chars, has_note,
    highlight_count, projects) of one row of ``_DISPLAY_QUERY``; no ``raw_text``."""
    paper = {k: v for k, v in dict(r["p"]).items() if v is not None}
    for k in ("created_at", "updated_at"):
        if k in paper:
            paper[k] = _iso(paper[k])
    paper.update(
        authors=r["authors"],
        added_by=r["added_by"],
        added_by_color=r["added_by_color"],
        text_chars=r["text_chars"],
        has_note=bool(r["has_note"]),
        highlight_count=r["highlight_count"],
        projects=r["projects"],
    )
    return paper


def display_papers(driver: Driver, ids: list[str]) -> dict[str, dict]:
    """Display fields (see ``display_fields``) plus ``is_reference`` of the papers with
    these ids, keyed by id. Used for the rows of the filter-only listing."""
    if not ids:
        return {}
    with driver.session() as s:
        rows = _display_rows(s, ids)
    out = {}
    for pid, r in rows.items():
        d = display_fields(r)
        d["is_reference"] = bool(r.get("ref"))
        out[pid] = d
    return out


def _raw_passages(driver: Driver, ids: list[str], needle_list: list[str]) -> dict:
    """id -> (text, cut_before, cut_after): ~1.4 kB of ``raw_text`` around the first
    occurrence of the most specific needle (found with split(), as Cypher has no indexOf),
    so the full text never leaves Neo4j."""
    with driver.session() as s:
        return {r["id"]: (r["t"], r["cut_before"], r["cut_after"]) for r in s.run(
            f"""MATCH (p:Paper) WHERE p.id IN $ids
                WITH p, toLower(substring(coalesce(p.raw_text, ''), 0, {_RAW_TEXT_MAX})) AS low
                WITH p, low, [n IN $needles | size(split(low, n)[0])] AS pos
                WITH p, low, [x IN pos WHERE x < size(low)] AS found
                WITH p, low, CASE WHEN size(found) = 0 THEN 0 ELSE found[0] END AS at
                WITH p, low, CASE WHEN at > {_WINDOW // 2} THEN at - {_WINDOW // 2} ELSE 0 END AS a
                RETURN p.id AS id, substring(p.raw_text, a, {_WINDOW}) AS t,
                       a > 0 AS cut_before, a + {_WINDOW} < size(low) AS cut_after""",
            ids=ids, needles=needle_list)}


def _hydrate(driver: Driver, page: list[Candidate], pq: ParsedQuery, max_snippets: int) -> list[dict]:
    """Display fields, authors and snippets for the papers on the page, in page order."""
    if not page:
        return []
    ids = [c.id for c in page]
    need_text = [c.id for c in page if "fulltext" in c.fields
                 and sum(1 for f in _SNIPPET_ORDER[:-1] if c.texts.get(f)) < max_snippets]
    # The passage lookup reads up to 400 kB of text per paper; run it beside the display query.
    raw_future = _POOL.submit(_raw_passages, driver, need_text, needles(pq)) if need_text and pq.units else None
    with driver.session() as s:
        rows = _display_rows(s, ids)
    raw = raw_future.result() if raw_future is not None else {}

    matchers = matchers_for(pq)
    out = []
    for c in page:
        r = rows.get(c.id)
        if r is None:
            continue
        paper = display_fields(r)
        snippets = []
        if matchers:
            for fld in _SNIPPET_ORDER:
                if len(snippets) >= max_snippets:
                    break
                if fld == "fulltext":
                    t, before, after = raw.get(c.id, ("", False, False))
                    texts = [(t, before, after)]
                else:
                    texts = [(t, False, False) for t in c.texts.get(fld, [])]
                for t, before, after in texts:
                    sn = snippet(t, matchers, cut_before=before, cut_after=after)
                    if sn:
                        sn["field"] = fld
                        if fld == "highlight" and c.pages:
                            sn["page"] = c.pages[0]
                        snippets.append(sn)
                        break
        if not snippets and "semantic" in c.fields:
            # A meaning-only hit: show where the abstract mentions a query word, else its start.
            fld = "abstract" if paper.get("abstract") else "summary"
            body = paper.get(fld) or ""
            sn = snippet(body, matchers) if matchers else None
            if sn is None and body:
                text = clean(body)
                sn = {"text": text[:240] + ("…" if len(text) > 240 else ""), "marks": []}
            if sn:
                snippets.append({**sn, "field": fld})
        matches = {f: c.texts[f] for f in ("author", "topic", "tag", "venue") if c.texts.get(f)}
        paper.update(
            score=round(c.score, 4),
            matched_in=legacy_matched_in(c.fields),
            matched_fields=c.fields,
            matches=matches,
            snippets=snippets,
            title_marks=mark(paper.get("title") or "", matchers) if matchers else [],
            is_reference=c.ref,
        )
        if c.semantic is not None:
            paper["similarity"] = round(float(c.semantic), 4)
        out.append(paper)
    return out


_NEEDS_SORT_FIELDS = SORTS - {"relevance", "title_asc"}


def _load_sort_fields(driver: Driver, ranked: list[Candidate]) -> None:
    """Fill year, created_at, rating, citation_count and updated_at of candidates that do
    not have them yet (one query for all of them; cached candidates keep what was loaded)."""
    todo = [c for c in ranked if not c.fields_loaded]
    if not todo:
        return
    with driver.session() as s:
        rows = {r["id"]: r for r in s.run(
            """MATCH (p:Paper) WHERE p.id IN $ids
               RETURN p.id AS id, p.year AS year, p.created_at AS created_at, p.rating AS rating,
                      p.citation_count AS citation_count, p.updated_at AS updated_at""",
            ids=[c.id for c in todo])}
    for c in todo:
        r = rows.get(c.id)
        if r is not None:
            c.year, c.created_at, c.rating = r["year"], _iso(r["created_at"]), r["rating"]
            c.citation_count, c.updated_at = r["citation_count"], _iso(r["updated_at"])
        c.fields_loaded = True


MODES = {"lexical", "semantic", "hybrid"}


@dataclass
class _Ranked:
    """What a search computes before sorting and paging; what the cache stores."""
    ranked: list[Candidate]
    used: str
    relaxed: bool
    sem_status: dict | None
    failed: list[str]


def _cache_key(q: str, f: Filters, mode: str) -> tuple:
    return (current_user() or "", q.strip(), mode, astuple(f))


def _rank_all(driver: Driver, pq: ParsedQuery, f: Filters, mode: str) -> _Ranked:
    sem_hits: list[Candidate] = []
    top_sim = None
    sem_status = None
    sem_future = None
    if mode in ("semantic", "hybrid") and pq.raw and not pq.identifier:
        from services.library_search import semantic

        sem_status = semantic.status()
        where, params = filter_clause(f)  # here: the request user lives in this thread
        sem_future = _POOL.submit(_semantic_candidates, driver, pq.raw, where, params)

    lexical: list[Candidate] = []
    failed: list[str] = []
    relaxed = False
    if mode != "semantic":
        lexical, failed = lexical_candidates(driver, pq, f)
    if sem_future is not None:
        try:
            sem_hits, top_sim = sem_future.result()
        except Exception as exc:  # noqa: BLE001 — semantic search is optional
            log.warning("semantic search failed: %s", exc)
            sem_status = {**(sem_status or {}), "state": "error", "error": str(exc)[:200]}
    if mode == "semantic" and not sem_hits:
        # No index yet, or nothing similar enough: answer lexically rather than with nothing.
        lexical, failed = lexical_candidates(driver, pq, f)
    score_candidates(lexical, pq)
    lexical, relaxed = rank(lexical)

    if mode == "semantic" and sem_hits:
        used, ranked = "semantic", sem_hits
        for c in ranked:
            c.score, c.fields = c.semantic or 0.0, ["semantic"]
    elif mode == "hybrid" and sem_hits:
        used = "hybrid"
        ranked = fuse(lexical, sem_hits, hybrid_weights(len(pq.units), relaxed, top_sim))
    else:
        used, ranked = "lexical", lexical
    if sem_status is not None and top_sim is not None:
        sem_status["top_similarity"] = round(top_sim, 4)
    return _Ranked(ranked, used, relaxed, sem_status, failed)


def _cacheable(res: _Ranked) -> bool:
    """Not while a source failed or the embedding index is still building: the answer
    should improve on the next request, not be remembered for a minute."""
    if res.failed:
        return False
    st = res.sem_status
    return st is None or st.get("state") == "ready"


def search(driver: Driver, q: str, filters: Filters | None = None, *, skip: int = 0,
           limit: int = 20, sort: str = "relevance", mode: str = "lexical",
           max_snippets: int = 2, cache: bool = False) -> dict:
    """Ranked search. Returns ``{"results", "total", "mode", "relaxed", "semantic",
    "failed_sources", "took_ms", "cached"}``; ``mode`` is the mode actually used (hybrid
    falls back to lexical while the embedding index is not ready).

    ``cache=True`` (the HTTP endpoint) keeps the ranked list for a minute, keyed by user,
    query, filters and mode, so paging and re-sorting skip retrieval; see ``cache.py``."""
    t0 = time.perf_counter()
    f = filters or Filters()
    pq = parse_query(q)
    mode = mode if mode in MODES else "lexical"
    sort = sort if sort in SORTS else "relevance"
    skip, limit = max(0, int(skip)), max(1, min(int(limit), 2000))

    res, hit = None, False
    cache = cache and result_cache.enabled()
    if cache:
        key = _cache_key(q, f, mode)
        gen = result_cache.generation()
        res = result_cache.get(key)
        hit = res is not None
    if res is None:
        res = _rank_all(driver, pq, f, mode)
        if cache and _cacheable(res):
            result_cache.put(key, res, gen)

    if sort in _NEEDS_SORT_FIELDS:
        _load_sort_fields(driver, res.ranked)
    ranked = sort_candidates(res.ranked, sort)
    page = ranked[skip: skip + limit]
    results = _hydrate(driver, page, pq, max_snippets)
    return {
        "results": results,
        "total": len(ranked),
        "mode": res.used,
        "relaxed": res.relaxed,
        "semantic": dict(res.sem_status) if res.sem_status is not None else None,
        "failed_sources": list(res.failed),
        "took_ms": round((time.perf_counter() - t0) * 1000, 1),
        "cached": hit,
    }
