"""Candidate papers and evidence for a report. Read-only; every Paper read is visibility-filtered
for the request user (the job thread sets the report owner)."""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

RAW_TEXT_CAP = 400_000
WINDOW = 1200
_STOP = set(
    "about above after again also among because been before being between both could does each "
    "from have into more most much must other over same should some such than that their them "
    "then there these they this those through under very were what when where which while with "
    "would your report library papers paper work study".split()
)


def query_terms(*texts: str, limit: int = 12) -> list[str]:
    """Distinct lower-case content words (4+ letters) of the texts, in order of appearance."""
    seen: list[str] = []
    for text in texts:
        for word in re.findall(r"[^\W\d_]{4,}|\w*\d\w*", (text or "").lower()):
            if word not in _STOP and word not in seen:
                seen.append(word)
    return seen[:limit]


def _brief(row: dict) -> dict:
    return {"id": row.get("id"), "title": row.get("title") or "", "year": row.get("year")}


# --------------------------------------------------------------------------- candidates

def project_info(driver, project_id: str, user: str | None) -> dict | None:
    """``{"id", "name"}`` of a project the user may see, else None."""
    from db.queries.visibility import project_visibility_clause
    from services.auth import reset_request_user, set_request_user

    token = set_request_user(user)
    try:
        clause, params = project_visibility_clause("pr")
        with driver.session() as session:
            rec = session.run(
                f"MATCH (pr:Project {{id: $id}}) WHERE {clause} RETURN pr.id AS id, pr.name AS name",
                id=project_id,
                **params,
            ).single()
    finally:
        reset_request_user(token)
    return {"id": rec["id"], "name": rec["name"] or ""} if rec else None


def project_papers(driver, project_id: str, limit: int = 60) -> list[dict]:
    """Papers of a project (not reference stubs), most recent first."""
    from db.queries.visibility import paper_visibility_clause

    clause, params = paper_visibility_clause("p")
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (p:Paper)-[:IN_PROJECT]->(:Project {{id: $pid}})
            WHERE {clause} AND NOT EXISTS {{ (p)-[:TAGGED]->(:Tag {{name: 'from-references'}}) }}
            RETURN p.id AS id, p.title AS title, p.year AS year
            ORDER BY coalesce(p.year, 0) DESC, p.title
            LIMIT $limit
            """,
            pid=project_id,
            limit=limit,
            **params,
        )
        return [_brief(dict(r)) for r in result]


def papers_by_ids(driver, ids: list[str]) -> list[dict]:
    """The visible papers among ``ids``, in the order given."""
    if not ids:
        return []
    from db.queries.visibility import paper_visibility_clause

    clause, params = paper_visibility_clause("p")
    with driver.session() as session:
        rows = {
            r["id"]: _brief(dict(r))
            for r in session.run(
                f"MATCH (p:Paper) WHERE p.id IN $ids AND {clause} "
                "RETURN p.id AS id, p.title AS title, p.year AS year",
                ids=ids,
                **params,
            )
        }
    return [rows[i] for i in ids if i in rows]


def _fulltext(driver, query: str, limit: int) -> list[dict]:
    """Plain fulltext fallback on the paper_search index."""
    from db.queries.visibility import paper_visibility_clause

    words = re.findall(r"\w{3,}", query)
    if not words:
        return []
    clause, params = paper_visibility_clause("p")
    with driver.session() as session:
        result = session.run(
            f"""
            CALL db.index.fulltext.queryNodes('paper_search', $q) YIELD node AS p, score
            WHERE {clause}
            RETURN p.id AS id, p.title AS title, p.year AS year
            ORDER BY score DESC LIMIT $limit
            """,
            q=" ".join(words[:12]),
            limit=limit,
            **params,
        )
        return [_brief(dict(r)) for r in result]


def search(driver, query: str, *, project_id: str | None = None, limit: int = 20) -> list[dict]:
    """Top library hits for a query: hybrid search, then lexical, then plain fulltext."""
    if not (query or "").strip():
        return []
    try:
        from services.library_search.engine import Filters, search as engine_search

        filters = Filters(project_id=project_id)
        if hasattr(filters, "include_references"):
            filters.include_references = False
        for mode in ("hybrid", "lexical"):
            try:
                found = engine_search(driver, query, filters, limit=limit, mode=mode)
                return [_brief(r) for r in found.get("results", []) if r.get("id")]
            except Exception as exc:  # noqa: BLE001
                log.warning("library search (%s) failed: %s", mode, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("library search unavailable: %s", exc)
    try:
        hits = _fulltext(driver, query, limit)
        if project_id:
            allowed = {p["id"] for p in project_papers(driver, project_id, 2000)}
            hits = [h for h in hits if h["id"] in allowed]
        return hits
    except Exception as exc:  # noqa: BLE001
        log.warning("fulltext fallback failed: %s", exc)
        return []


# --------------------------------------------------------------------------- evidence

def fetch_evidence(driver, ids: list[str]) -> dict[str, dict]:
    """Evidence per visible paper id, without the full text.

    Each value: id, title, year, venue, authors (up to 4 names), summary, abstract,
    claims (up to 8 texts), note, highlights (up to 6 ``{"text", "note"}``).
    """
    if not ids:
        return {}
    from db.queries.visibility import paper_visibility_clause

    clause, params = paper_visibility_clause("p")
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (p:Paper) WHERE p.id IN $ids AND {clause}
            RETURN p.id AS id, p.title AS title, p.year AS year, p.venue AS venue,
                   p.summary AS summary, p.abstract AS abstract,
                   [(p)-[:AUTHORED_BY]->(a:Person) | a.name][..4] AS authors,
                   [(p)-[:HAS_CLAIM]->(c:Claim) | c.text][..8] AS claims,
                   head([(p)-[:HAS_NOTE]->(n:Note) | n.content]) AS note,
                   [(p)-[:HAS_ANNOTATION]->(a:Annotation) | {{text: a.highlighted_text, note: a.note}}][..6] AS highlights
            """,
            ids=ids,
            **params,
        )
        out = {}
        for r in result:
            row = dict(r)
            row["authors"] = [a for a in row.get("authors") or [] if a]
            row["claims"] = [c for c in row.get("claims") or [] if c]
            row["highlights"] = [h for h in row.get("highlights") or [] if h and (h.get("text") or h.get("note"))]
            out[row["id"]] = row
        return out


def fetch_raw(driver, ids: list[str]) -> dict[str, str]:
    """The first ~400k characters of each visible paper's full text (used only to cut passages)."""
    if not ids:
        return {}
    from db.queries.visibility import paper_visibility_clause

    clause, params = paper_visibility_clause("p")
    with driver.session() as session:
        result = session.run(
            f"MATCH (p:Paper) WHERE p.id IN $ids AND {clause} "
            f"RETURN p.id AS id, substring(coalesce(p.raw_text, ''), 0, {RAW_TEXT_CAP}) AS raw",
            ids=ids,
            **params,
        )
        return {r["id"]: r["raw"] or "" for r in result}


def find_passages(raw: str, terms: list[str], n: int = 2, width: int = WINDOW) -> list[str]:
    """Up to ``n`` windows of ~``width`` characters of ``raw`` that match the most query terms."""
    if not raw or not terms:
        return []
    low = raw.lower()
    step = width // 2
    scored: list[tuple[float, int]] = []
    for start in range(0, len(low), step):
        chunk = low[start : start + width]
        counts = [chunk.count(t) for t in terms]
        distinct = sum(1 for c in counts if c)
        if distinct:
            scored.append((distinct * 3 + sum(min(c, 3) for c in counts), start))
    scored.sort(key=lambda s: (-s[0], s[1]))
    picked: list[int] = []
    for _, start in scored:
        if all(abs(start - other) >= width for other in picked):
            picked.append(start)
        if len(picked) == n:
            break
    out = []
    for start in sorted(picked):
        a, b = start, min(len(raw), start + width)
        while a > 0 and not raw[a - 1].isspace() and a > start - 40:
            a -= 1
        while b < len(raw) and not raw[b].isspace() and b < start + width + 40:
            b += 1
        text = re.sub(r"\s+", " ", raw[a:b]).strip()
        out.append(("… " if a > 0 else "") + text + (" …" if b < len(raw) else ""))
    return out


def _clip(text: str | None, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def format_source(label: str, ev: dict, passages: list[str], limit: int) -> str:
    """One compact source block ``[S3] Title (2023), Authors — summary… Claims: …``.

    Parts are added in priority order (summary, claims, note, highlights, abstract, passages)
    and the block is cut to ``limit`` characters.
    """
    authors = ", ".join(ev.get("authors", [])[:3]) + (" et al." if len(ev.get("authors", [])) > 3 else "")
    head = f"[{label}] {ev.get('title') or 'Untitled'}"
    if ev.get("year"):
        head += f" ({ev['year']})"
    if authors:
        head += f", {authors}"
    if ev.get("venue"):
        head += f". {ev['venue']}"
    parts = [head]
    summary = _clip(ev.get("summary"), 1200)
    if summary:
        parts.append("Summary: " + summary)
    if ev.get("claims"):
        parts.append("Claims: " + " | ".join(_clip(c, 220) for c in ev["claims"][:8]))
    note = _clip(ev.get("note"), 800)
    if note:
        parts.append("Your note: " + note)
    if ev.get("highlights"):
        lines = []
        for h in ev["highlights"][:6]:
            line = f"“{_clip(h.get('text'), 250)}”"
            if h.get("note"):
                line += f" (comment: {_clip(h['note'], 150)})"
            lines.append(line)
        parts.append("Highlights: " + " ".join(lines))
    if not summary and ev.get("abstract"):
        parts.append("Abstract: " + _clip(ev["abstract"], 1000))
    if passages:
        parts.append("Passages: " + " ".join(f"“{p}”" for p in passages))
    block, used = [], 0
    for part in parts:
        room = limit - used
        if room < 80 and block:
            break
        block.append(part if len(part) <= room else part[: max(room - 1, 1)].rstrip() + "…")
        used += len(part) + 1
        if used >= limit:
            break
    return "\n".join(block)
