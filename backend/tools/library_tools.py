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

import json
import re

from mcp.server.fastmcp import FastMCP

from config import settings
from db.connection import get_driver
from db.queries.visibility import paper_visibility_clause
from services.library_lookup import lookup as _lookup
from services.library_search.engine import Filters, search as _search

# Claude Code moves MCP results above ~50 KB out of context into a file, which the
# model then has to open with another tool; every result here stays well below that.
_READ_MAX = 30000
_NOTE_MAX = 6000
_SAVED_ANSWER = re.compile(r"\n-{3,}\n\*\*Claude \(([^)]*)\):\*\*")


def _url(paper_id: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/paper/{paper_id}"


def _marked(sn: dict) -> str:
    """A search snippet as plain text with the matched words in «»."""
    text, out, at = sn["text"], [], 0
    for s, e in sn.get("marks", []):
        out += [text[at:s], "«", text[s:e], "»"]
        at = e
    return "".join(out + [text[at:]])


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


def library_lookup(dois: list[str] | None = None, titles: list[str] | None = None, project: str = "") -> dict:
    """Batch existence check behind the MCP tool of the same name (services/library_lookup.py)."""
    return _lookup(get_driver(), dois, titles, project, url_base=settings.frontend_url)


def register(mcp: FastMCP):
    @mcp.tool(name="library_lookup", structured_output=False)
    def _library_lookup(dois: list[str] = [], titles: list[str] = [], project: str = "") -> str:  # noqa: B006
        """Cheap batch check of which papers are ALREADY in the library. Call it before
        add_paper_metadata / upload_pdf for a list of cited papers, so nothing is added twice;
        far cheaper than search_papers or library_search (no summaries, abstracts or snippets).

        Up to 200 items per call. Pass `dois`, `titles`, or both paired by index (item i is
        dois[i] with titles[i]; use "" for a missing one): the DOI is tried first, then the
        title. DOIs are normalised (case, https://doi.org/, doi: prefixes, trailing dot) and
        arXiv forms are one id (10.48550/arXiv.2210.02747 = arXiv:2210.02747 = 2210.02747v2).
        Titles are compared lowercased with markup and everything but a-z0-9 removed: exact
        first, else the first 45 such characters. A paper stored under its bioRxiv DOI is
        missed by the journal DOI, so give titles too when you have them.

        Returns compact JSON: `found`, `missing`, and per item `{query, kind, match}` where
        kind is doi | title_exact | title_prefix | null and match is null or
        `{id, title, doi, year, projects, reference_stub, has_text, url}` (a list plus
        `duplicates: n` when several papers match). `reference_stub` = citation stub from a
        reference list (no PDF or notes); it counts as present but may deserve upload_pdf.
        `project` (name or id) adds `in_project` per match; add_to_project links a found
        paper that is not in it yet."""
        return json.dumps(library_lookup(dois, titles, project), ensure_ascii=False, separators=(",", ":"))

    @mcp.tool(name="library_add", structured_output=False)
    def _library_add(papers: list[dict] = [], path: str = "", project: str = "",  # noqa: B006
                     dry_run: bool = False) -> str:
        """Add a whole reference list to the library and to one project in ONE call, instead
        of library_lookup + add_paper_metadata + add_to_project per paper.

        Give `path`, the absolute path of a report's papers.json (a list of entries, or
        {"papers": [...]}), or `papers`, the entries inline (up to 200). An entry needs
        `title`; it may carry `doi`, `arxiv` (an id; becomes DOI 10.48550/arXiv.<id>),
        `paperId`, `year`, `venue`, `abstract`, `document_type`, `published_date`, and
        `authors` as a list of full names (a plain string is ignored).

        Per entry: a `paperId` that exists counts as present; otherwise the DOI, then the
        title, is looked up as in library_lookup; a paper still missing is created as
        metadata only (no PDF; upload_pdf adds one later). Entries naming the same paper
        twice are created once (`same_as`). With `project` (name or id; it must exist,
        create_project first) every paper is linked to it; existing links are kept.
        With `path` the file is rewritten with each entry's paperId, url and status
        ("present" or "added"). `dry_run` reports the same counts and writes nothing.

        Returns compact JSON: counts (present, added, same_in_batch, linked) and per entry
        {i, title, status, id, kind, url}; kind is how a present paper was found (id, doi,
        title_exact, title_prefix), `duplicates` lists ids when several library papers match."""
        from services.library_add import add as _add
        res = _add(get_driver(), papers, project, path, dry_run, url_base=settings.frontend_url)
        return json.dumps(res, ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    def library_search(query: str, project: str = "", limit: int = 12) -> dict:
        """Search the whole library for a topic and report WHERE each paper matched.

        Looks in titles, authors, topics, tags, venue, abstracts/summaries, the user's own
        notes, the user's PDF highlights and their comments, extracted claims and the
        extracted full text (the same ranked search as the app's library page), blended
        with embedding similarity of title + abstract. Quote a phrase to require it.
        `project` restricts to one project (name, e.g. "MasterThesis", or id).
        Each hit lists `matched_in` and short `evidence` snippets (matched words in
        «»), plus whether the paper has full text (`text_chars`), a note, and how many
        highlights — use get_paper_context and read_paper_text / find_in_paper to go deeper."""
        q = query.strip()
        if not q:
            return {"query": query, "hits": [], "error": "empty query"}
        limit = max(1, min(int(limit), 40))
        try:
            from services.library_search import semantic
            semantic.ensure_loaded()
        except Exception:  # noqa: BLE001 — lexical search works without it
            pass
        res = _search(get_driver(), q, Filters(project=project.strip() or None), limit=limit,
                      mode="hybrid", max_snippets=4)
        hits = []
        for p in res["results"]:
            evidence = [{"from": sn["field"], "text": _marked(sn)} for sn in p["snippets"]]
            for f, names in p.get("matches", {}).items():
                evidence.append({"from": f, "text": ", ".join(names)})
            hits.append({
                "paper_id": p["id"], "title": p.get("title"), "year": p.get("year"),
                "score": round(p["score"], 4), "matched_in": p["matched_fields"],
                "evidence": evidence[:5], "text_chars": p.get("text_chars", 0),
                "has_note": p.get("has_note", False), "highlights": p.get("highlight_count", 0),
                "projects": p.get("projects", []), "reference_stub": p.get("is_reference", False),
                "url": _url(p["id"]),
            })
        return {"query": query, "project": project or None, "total": res["total"],
                "mode": res["mode"], "hits": hits}

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
