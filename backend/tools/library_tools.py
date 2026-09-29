"""Read-only library tools for an external reader.

These let an MCP client (Claude Code over a research repository) use the library
as a database: find papers, see everything the user has done with them (note,
highlights, tags, projects, extracted claims) and read the extracted full text
itself, page by page. Nothing here calls a language model — the client does the
reading — so using them costs no API tokens on the PaperManager side.

Every result carries `paper_id`, `title` and `url` so a client UI can show which
papers entered the conversation and link back to them.
"""
from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP

from config import settings
from db.connection import get_driver
from db.queries.visibility import paper_visibility_clause

_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
# Claude Code moves MCP results above ~50 KB out of context into a file, which the
# model then has to open with another tool; every result here stays well below that.
_READ_MAX = 30000
_NOTE_MAX = 6000
_SAVED_ANSWER = re.compile(r"\n-{3,}\n\*\*Claude \(([^)]*)\):\*\*")


def _url(paper_id: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/paper/{paper_id}"


def _lucene(q: str) -> str:
    """Escape a free-text query for the Neo4j full-text indexes."""
    return _LUCENE_SPECIAL.sub(r"\\\1", q.strip())


def _snippet(text: str, needle: str, width: int = 220) -> str:
    i = text.lower().find(needle.lower())
    if i < 0:
        return text[:width].strip()
    a, b = max(0, i - width // 2), min(len(text), i + len(needle) + width // 2)
    return ("…" if a else "") + text[a:b].replace("\n", " ").strip() + ("…" if b < len(text) else "")


def _project_filter(var: str = "p") -> str:
    """Cypher predicate: `$project` empty, or the paper sits in a project with that name or id."""
    return (
        f"($project = '' OR EXISTS {{ MATCH ({var})-[:IN_PROJECT]->(pr:Project) "
        f"WHERE pr.id = $project OR toLower(pr.name) = toLower($project) }})"
    )


def _highlight(a: dict) -> dict:
    return {
        "annotation_id": a.get("id"),
        "page": a.get("page_number"),
        "text": a.get("highlighted_text") or "",
        "comment": a.get("note") or "",
        "color": a.get("color"),
        "created_at": a.get("created_at"),
    }


def _split_note(content: str, full: bool) -> dict:
    """A paper note is the user's own text, then chat answers the paper manager saved
    below it (`---` / `**Claude (date):**`). Keep them apart: the first is what the user
    thinks, the second is an earlier model's output."""
    content = content or ""
    m = _SAVED_ANSWER.search(content)
    own = (content[: m.start()] if m else content).strip()
    answers = [a.group(1) for a in _SAVED_ANSWER.finditer(content)]
    out = {"own_text": own, "saved_answers": len(answers), "saved_answer_dates": answers, "chars": len(content)}
    if full:
        body = content[m.start():] if m else ""
        out["saved_answers_text"] = body[:_NOTE_MAX] + ("\n…[truncated]" if len(body) > _NOTE_MAX else "")
    return out


def register(mcp: FastMCP):
    @mcp.tool()
    def library_search(query: str, project: str = "", limit: int = 12) -> dict:
        """Search the whole library for a topic and report WHERE each paper matched.

        Looks in paper titles/abstracts/summaries, the user's own notes, the user's PDF
        highlights and their comments, extracted claims, and the extracted full text.
        `project` restricts to one project (name, e.g. "MasterThesis", or id).
        Each hit lists `matched_in` and short `evidence` snippets, plus whether the paper
        has full text (`text_chars`), a note, and how many highlights — use
        get_paper_context and read_paper_text / find_in_paper to go deeper."""
        q = query.strip()
        if not q:
            return {"query": query, "hits": [], "error": "empty query"}
        limit = max(1, min(int(limit), 40))
        vis, vis_params = paper_visibility_clause("p")
        params = {"q": _lucene(q), "raw": q.lower(), "project": project.strip(), "k": limit * 3, **vis_params}
        hits: dict[str, dict] = {}

        def add(pid: str, title: str, year, source: str, score: float, evidence: str | None = None):
            h = hits.setdefault(pid, {"paper_id": pid, "title": title, "year": year, "score": 0.0,
                                      "matched_in": [], "evidence": []})
            if source not in h["matched_in"]:
                h["matched_in"].append(source)
            h["score"] += score
            if evidence and len(h["evidence"]) < 4:
                h["evidence"].append({"from": source, "text": evidence})

        where = f"{vis} AND {_project_filter('p')}"
        with get_driver().session() as s:
            for r in s.run(
                f"""CALL db.index.fulltext.queryNodes('paper_search', $q) YIELD node AS p, score
                    WHERE {where}
                    RETURN p.id AS id, p.title AS title, p.year AS year, score,
                           coalesce(p.abstract, p.summary, '') AS body LIMIT $k""", params):
                add(r["id"], r["title"], r["year"], "metadata", r["score"], _snippet(r["body"], q) if r["body"] else None)
            for r in s.run(
                f"""CALL db.index.fulltext.queryNodes('note_search', $q) YIELD node AS n, score
                    MATCH (p:Paper)-[:HAS_NOTE]->(n) WHERE {where}
                    RETURN p.id AS id, p.title AS title, p.year AS year, score, n.content AS body LIMIT $k""", params):
                add(r["id"], r["title"], r["year"], "note", r["score"] + 2.0, _snippet(r["body"] or "", q))
            for r in s.run(
                f"""CALL db.index.fulltext.queryNodes('claim_search', $q) YIELD node AS c, score
                    MATCH (p:Paper)-[:HAS_CLAIM]->(c) WHERE {where}
                    RETURN p.id AS id, p.title AS title, p.year AS year, score, c.text AS body LIMIT $k""", params):
                add(r["id"], r["title"], r["year"], "claim", r["score"], r["body"])
            for r in s.run(
                f"""MATCH (p:Paper)-[:HAS_ANNOTATION]->(a:Annotation)
                    WHERE (toLower(coalesce(a.highlighted_text, '')) CONTAINS $raw
                           OR toLower(coalesce(a.note, '')) CONTAINS $raw) AND {where}
                    RETURN p.id AS id, p.title AS title, p.year AS year,
                           a.highlighted_text AS hl, a.note AS note, a.page_number AS page LIMIT $k""", params):
                ev = f"p.{r['page']}: “{r['hl']}”" + (f" — {r['note']}" if r["note"] else "")
                add(r["id"], r["title"], r["year"], "highlight", 3.0, ev)
            for r in s.run(
                f"""MATCH (p:Paper) WHERE p.raw_text IS NOT NULL AND {where}
                      AND toLower(p.raw_text) CONTAINS $raw
                    RETURN p.id AS id, p.title AS title, p.year AS year, p.raw_text AS body LIMIT $k""", params):
                add(r["id"], r["title"], r["year"], "full_text", 1.0, _snippet(r["body"], q))

            ranked = sorted(hits.values(), key=lambda h: h["score"], reverse=True)[:limit]
            ids = [h["paper_id"] for h in ranked]
            info = {r["id"]: r for r in s.run(
                """MATCH (p:Paper) WHERE p.id IN $ids
                   RETURN p.id AS id, size(coalesce(p.raw_text, '')) AS chars,
                          EXISTS { (p)-[:HAS_NOTE]->() } AS has_note,
                          COUNT { (p)-[:HAS_ANNOTATION]->() } AS highlights,
                          [(p)-[:IN_PROJECT]->(pr:Project) | pr.name] AS projects""", ids=ids)}
        for h in ranked:
            i = info.get(h["paper_id"])
            h["score"] = round(h["score"], 2)
            h.update(text_chars=i["chars"] if i else 0, has_note=bool(i and i["has_note"]),
                     highlights=i["highlights"] if i else 0, projects=i["projects"] if i else [],
                     url=_url(h["paper_id"]))
        return {"query": query, "project": project or None, "hits": ranked}

    @mcp.tool()
    def get_paper_context(paper_id: str) -> dict:
        """Everything the library holds about one paper except its full text:
        metadata, authors, tags, topics, projects, the user's markdown note, every PDF
        highlight with page, colour and the user's comment, and extracted claims.
        `text_chars` says how much extracted text read_paper_text can return."""
        with get_driver().session() as s:
            r = s.run(
                """MATCH (p:Paper {id: $id})
                   RETURN p {.*, raw_text: null} AS p, size(coalesce(p.raw_text, '')) AS chars,
                          [(p)-[:AUTHORED_BY]->(a:Person) | a.name] AS authors,
                          [(p)-[:TAGGED]->(t:Tag) | t.name] AS tags,
                          [(p)-[:ABOUT]->(t:Topic) | t.name] AS topics,
                          [(p)-[:IN_PROJECT]->(pr:Project) | pr.name] AS projects,
                          head([(p)-[:HAS_NOTE]->(n:Note) | n]) AS note,
                          [(p)-[:HAS_ANNOTATION]->(a:Annotation) | a] AS anns,
                          [(p)-[:HAS_CLAIM]->(c:Claim) | {type: c.type, text: c.text}] AS claims""",
                id=paper_id).single()
        if not r:
            return {"paper_id": paper_id, "error": f"Paper {paper_id} not found"}
        p = {k: v for k, v in dict(r["p"]).items() if v is not None and k not in ("raw_text", "embedding")}
        anns = sorted((_highlight(dict(a)) for a in r["anns"]), key=lambda a: (a["page"] or 0, a["created_at"] or ""))
        note = dict(r["note"]) if r["note"] else None
        return {
            "paper_id": paper_id,
            "title": p.get("title"),
            "year": p.get("year"),
            "venue": p.get("venue"),
            "doi": p.get("doi"),
            "authors": r["authors"],
            "abstract": p.get("abstract"),
            "summary": p.get("summary"),
            "reading_status": p.get("reading_status"),
            "rating": p.get("rating"),
            "bookmarked": p.get("bookmarked"),
            "tags": r["tags"],
            "topics": r["topics"],
            "projects": r["projects"],
            "note": {**_split_note(note.get("content", ""), full=True), "updated_at": note.get("updated_at")} if note else None,
            "highlights": anns,
            "claims": r["claims"][:40],
            "text_chars": r["chars"],
            "url": _url(paper_id),
        }

    @mcp.tool()
    def read_paper_text(paper_id: str, offset: int = 0, length: int = 15000) -> dict:
        """Read the paper's extracted full text, `length` characters from `offset`
        (max 30000 per call). Page through with `next_offset` until it is null.
        Use find_in_paper first to jump to the relevant passage of a long paper."""
        offset, length = max(0, int(offset)), max(1, min(int(length), _READ_MAX))
        with get_driver().session() as s:
            r = s.run("MATCH (p:Paper {id: $id}) RETURN p.title AS title, coalesce(p.raw_text, '') AS t",
                      id=paper_id).single()
        if not r:
            return {"paper_id": paper_id, "error": f"Paper {paper_id} not found"}
        text, total = r["t"], len(r["t"])
        end = min(total, offset + length)
        return {
            "paper_id": paper_id, "title": r["title"], "url": _url(paper_id),
            "offset": offset, "end": end, "total_chars": total,
            "next_offset": end if end < total else None,
            "text": text[offset:end] if total else "",
            **({"note": "No extracted text for this paper."} if not total else {}),
        }

    @mcp.tool()
    def find_in_paper(paper_id: str, query: str, context: int = 500, max_hits: int = 8) -> dict:
        """Find passages in one paper's full text. Tries the exact phrase first, then
        each word of 4+ letters. Returns snippets with character offsets that can be
        passed to read_paper_text to read the surrounding section."""
        context, max_hits = max(100, min(int(context), 3000)), max(1, min(int(max_hits), 25))
        with get_driver().session() as s:
            r = s.run("MATCH (p:Paper {id: $id}) RETURN p.title AS title, coalesce(p.raw_text, '') AS t",
                      id=paper_id).single()
        if not r:
            return {"paper_id": paper_id, "error": f"Paper {paper_id} not found"}
        text, low = r["t"], r["t"].lower()
        phrase = query.strip().lower()
        if phrase and phrase in low:
            mode, terms = "phrase", [phrase]
        else:
            mode, terms = "words", sorted({w for w in re.findall(r"[\w\-]{4,}", phrase) if w in low})
        # Every occurrence is a candidate centre; a window scores by how many distinct
        # terms it contains, so passages where the words co-occur come first.
        occ = sorted((m.start(), t) for t in terms for m in re.finditer(re.escape(t), low))
        scored = []
        for pos, _ in occ:
            a, b = max(0, pos - context // 2), min(len(text), pos + context // 2)
            present = sorted({t for p, t in occ if a <= p < b})
            scored.append((len(present), -pos, a, b, present))
        scored.sort(reverse=True)
        hits, taken = [], []
        for n, _, a, b, present in scored:
            if any(abs(a - t) < context for t in taken):
                continue
            taken.append(a)
            hits.append({"offset": a, "terms": present, "text": text[a:b]})
            if len(hits) >= max_hits:
                break
        return {"paper_id": paper_id, "title": r["title"], "url": _url(paper_id), "query": query,
                "mode": mode, "total_chars": len(text), "hits": hits}

    @mcp.tool()
    def list_highlights(project: str = "", paper_id: str = "", query: str = "", limit: int = 100) -> dict:
        """The user's PDF highlights (quoted text, page, colour, their comment), newest
        first, optionally restricted to a project (name or id), one paper, or those whose
        text or comment contains `query`."""
        vis, vis_params = paper_visibility_clause("p")
        with get_driver().session() as s:
            rows = s.run(
                f"""MATCH (p:Paper)-[:HAS_ANNOTATION]->(a:Annotation)
                    WHERE {vis} AND {_project_filter('p')}
                      AND ($pid = '' OR p.id = $pid)
                      AND ($raw = '' OR toLower(coalesce(a.highlighted_text, '')) CONTAINS $raw
                                     OR toLower(coalesce(a.note, '')) CONTAINS $raw)
                    RETURN p.id AS id, p.title AS title, a
                    ORDER BY a.created_at DESC LIMIT $k""",
                project=project.strip(), pid=paper_id.strip(), raw=query.strip().lower(),
                k=max(1, min(int(limit), 500)), **vis_params)
            out = [{"paper_id": r["id"], "title": r["title"], "url": _url(r["id"]), **_highlight(dict(r["a"]))} for r in rows]
        return {"count": len(out), "highlights": out}

    @mcp.tool()
    def list_notes(project: str = "", query: str = "", limit: int = 50) -> dict:
        """The user's notes on papers, most recently edited first, optionally restricted
        to a project (name or id) or to notes containing `query`. Each note gives the
        user's own text in full and only counts the chat answers saved below it; read
        those with get_paper_context."""
        vis, vis_params = paper_visibility_clause("p")
        with get_driver().session() as s:
            rows = s.run(
                f"""MATCH (p:Paper)-[:HAS_NOTE]->(n:Note)
                    WHERE {vis} AND {_project_filter('p')}
                      AND ($raw = '' OR toLower(coalesce(n.content, '')) CONTAINS $raw)
                    RETURN p.id AS id, p.title AS title, n.content AS content, n.updated_at AS updated_at
                    ORDER BY n.updated_at DESC LIMIT $k""",
                project=project.strip(), raw=query.strip().lower(), k=max(1, min(int(limit), 200)), **vis_params)
            out = [{"paper_id": r["id"], "title": r["title"], "url": _url(r["id"]),
                    **_split_note(r["content"], full=False), "updated_at": r["updated_at"]} for r in rows]
        return {"count": len(out), "notes": out}
