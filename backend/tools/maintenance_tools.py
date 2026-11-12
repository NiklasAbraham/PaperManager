"""Library maintenance for MCP clients: find and merge duplicates, correct metadata, re-run a
failed summary, delete a paper. The write tools default to a preview (``dry_run`` /
``confirm``) so a client sees what changes before it changes."""
from mcp.server.fastmcp import FastMCP

from db.connection import get_driver
from db.queries.papers import get_paper, update_paper
from db.queries.people import get_authors_for_paper, get_or_create_person, link_author, unlink_author
from services.duplicate_scan import CLASSES, SCAN_QUERY, scan, wrong_doi_suspects
from services.paper_delete import deletion_preview, delete_paper_completely
from services.paper_merge import merge_papers as _merge

_METADATA_FIELDS = ("title", "year", "venue", "doi", "abstract", "published_date", "document_type")


def _slim(p: dict) -> dict:
    keys = ("id", "title", "year", "doi", "text_chars", "notes", "annotations", "projects")
    out = {k: p.get(k) for k in keys}
    out["has_pdf"] = bool(p.get("drive_file_id"))
    return out


def find_duplicates(classes: str = "") -> dict:
    wanted = set(filter(None, (classes or ",".join(CLASSES)).split(",")))
    unknown = wanted - set(CLASSES)
    if unknown:
        return {"error": f"unknown classes {sorted(unknown)}; choose from {list(CLASSES)}"}
    with get_driver().session() as session:
        result = scan(session.run(SCAN_QUERY).data())
    return {
        "total_papers": result.total,
        "groups": [{"class": g.klass, "reasons": g.reasons, "keep": _slim(g.keep),
                    "remove": [_slim(p) for p in g.remove]}
                   for g in result.groups if g.klass in wanted],
        "wrong_doi_suspects": [{"paper": _slim(s), "doi_belongs_to": _slim(o)}
                               for s, o in wrong_doi_suspects(result)],
    }


def merge_papers(keep_id: str, remove_ids: list[str], dry_run: bool = True) -> dict:
    remove_ids = [r for r in remove_ids if r]
    if not remove_ids or keep_id in remove_ids:
        return {"error": "give at least one remove_id, all different from keep_id"}
    try:
        return _merge(get_driver(), keep_id, remove_ids, dry_run=dry_run).as_dict()
    except LookupError as exc:
        return {"error": str(exc)}


def update_paper_metadata(
    paper_id: str,
    title: str | None = None,
    year: int | None = None,
    venue: str | None = None,
    doi: str | None = None,
    abstract: str | None = None,
    published_date: str | None = None,
    document_type: str | None = None,
    authors: list[str] | None = None,
) -> dict:
    driver = get_driver()
    if not get_paper(driver, paper_id):
        return {"error": f"Paper {paper_id} not found"}
    given = dict(title=title, year=year, venue=venue, doi=doi, abstract=abstract,
                 published_date=published_date, document_type=document_type)
    props = {k: v for k, v in given.items() if v is not None}
    changed = sorted(props)
    if props:
        update_paper(driver, paper_id, {**props, "metadata_source": "manual"})

    removed: list[str] = []
    if authors is not None:
        from services.pdf_parser import clean_authors  # pypdf, only needed here
        names = clean_authors(authors)
        for person in get_authors_for_paper(driver, paper_id):
            if person["name"] not in names:
                unlink_author(driver, paper_id, person["id"])
                removed.append(person["name"])
                # A placeholder such as "Anonymous Authors" is left with nothing attached
                with driver.session() as session:
                    session.run("MATCH (a:Person {id: $id}) WHERE NOT (a)--() DELETE a", id=person["id"])
        for name in names:
            link_author(driver, paper_id, get_or_create_person(driver, name)["id"])

    paper = get_paper(driver, paper_id) or {}
    return {
        "id": paper_id,
        "updated": changed,
        **{k: paper.get(k) for k in _METADATA_FIELDS},
        "authors": [p["name"] for p in get_authors_for_paper(driver, paper_id)],
        "authors_removed": removed,
    }


def regenerate_summary(paper_id: str) -> dict:
    from services.ai import summarize_paper

    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        return {"error": f"Paper {paper_id} not found"}
    raw_text = paper.get("raw_text") or ""
    if not raw_text.strip():
        return {"error": "No extracted text for this paper; upload its PDF first"}
    summary = summarize_paper(raw_text, paper.get("title", ""))
    update_paper(driver, paper_id, {"summary": summary})
    return {"id": paper_id, "summary_chars": len(summary or ""), "summary": summary}


def delete_paper(paper_id: str, confirm: bool = False) -> dict:
    driver = get_driver()
    preview = deletion_preview(driver, paper_id)
    if preview is None:
        return {"error": f"Paper {paper_id} not found"}
    if not confirm:
        return {"status": "preview", "would_delete": preview,
                "hint": "Call again with confirm=true to delete. For a duplicate use merge_papers instead."}
    delete_paper_completely(driver, paper_id)
    return {"status": "deleted", "deleted": preview}


def register(mcp: FastMCP):
    @mcp.tool(name="find_duplicates")
    def _find_duplicates(classes: str = "") -> dict:
        """Find duplicate papers (same DOI, preprint/journal pairs, matching or truncated titles).

        classes: optional comma-separated subset of pdf_duplicates, library_duplicates,
        paper_with_stubs, stubs_only. Each group names the paper to keep and the ones to
        merge into it. Also lists papers that carry another paper's DOI."""
        return find_duplicates(classes)

    @mcp.tool(name="merge_papers")
    def _merge_papers(keep_id: str, remove_ids: list[str], dry_run: bool = True) -> dict:
        """Merge duplicate papers into keep_id without losing anything attached to them:
        missing properties (DOI, PDF, text, summary) are copied over, notes appended,
        highlights, tags, topics, projects, authors and citations moved, then the duplicates
        are deleted. dry_run=true (the default) only reports what would happen."""
        return merge_papers(keep_id, remove_ids, dry_run)

    @mcp.tool(name="update_paper_metadata")
    def _update_paper_metadata(
        paper_id: str,
        title: str | None = None,
        year: int | None = None,
        venue: str | None = None,
        doi: str | None = None,
        abstract: str | None = None,
        published_date: str | None = None,
        document_type: str | None = None,
        authors: list[str] | None = None,
    ) -> dict:
        """Correct a paper's metadata. Only the fields given are changed.

        authors, if given, replaces the author list: missing people are created, authors not
        in the list are unlinked (and deleted if nothing else refers to them). Placeholders
        such as "Anonymous Authors" are dropped."""
        return update_paper_metadata(paper_id, title, year, venue, doi, abstract,
                                     published_date, document_type, authors)

    @mcp.tool(name="regenerate_summary")
    def _regenerate_summary(paper_id: str) -> dict:
        """Re-run the AI summary on a paper's stored full text (e.g. when the summary step
        failed during upload). Uses the library's summary model (LiteLLM)."""
        return regenerate_summary(paper_id)

    @mcp.tool(name="delete_paper")
    def _delete_paper(paper_id: str, confirm: bool = False) -> dict:
        """Delete a paper with its note, highlights, claims, figures and PDF (Drive trash).
        Without confirm=true it only returns what would be deleted. Use merge_papers for
        duplicates, so nothing attached is lost."""
        return delete_paper(paper_id, confirm)
