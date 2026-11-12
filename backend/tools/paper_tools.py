from mcp.server.fastmcp import FastMCP
from tools._compact import json_tool
from db.connection import get_driver
from db.queries.papers import create_paper, get_paper, update_paper, random_paper
from db.queries.concepts import list_concepts
from db.queries.search import search_papers as _search
from db.queries.people import list_people as _list_people
from db.queries.tags import list_tags as _list_tags
from db.queries.topics import list_topics as _list_topics
from config import settings


def _row(p: dict) -> dict:
    """A search_papers hit without the long fields (summary, abstract, snippets' marks)."""
    row = {k: p[k] for k in ("id", "title", "year", "venue", "doi", "document_type", "reading_status")
           if p.get(k) not in (None, "")}
    if p.get("authors"):
        row["authors"] = p["authors"][:5] + (["…"] if len(p["authors"]) > 5 else [])
    if p.get("matched_fields"):
        row["matched_in"] = p["matched_fields"]
    if p.get("is_reference"):
        row["reference_stub"] = True
    row["url"] = f"{settings.frontend_url.rstrip('/')}/paper/{p['id']}"
    return row


def register(mcp: FastMCP):
    @json_tool(mcp)
    def search_papers(
        query: str = "",
        tag: str = "",
        topic: str = "",
        project_id: str = "",
        person_id: str = "",
        year_min: int | None = None,
        year_max: int | None = None,
        reading_status: str = "",
        bookmarked: bool | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List papers by keyword and/or filters (tag, topic, project id, person id, years,
        reading_status 'unread'|'reading'|'read', bookmarked); all optional, newest first
        without a query. One short row per paper: id, title, year, venue, doi, authors, url
        and, with a query, where it matched. For a topic search prefer library_search; for
        abstract and summary call get_paper_detail."""
        result = _search(
            get_driver(),
            q=query or None,
            tag=tag or None,
            topic=topic or None,
            project_id=project_id or None,
            person_id=person_id or None,
            year_min=year_min,
            year_max=year_max,
            reading_status=reading_status or None,
            bookmarked=bookmarked,
            limit=max(1, min(int(limit), 100)),
        )
        return [_row(p) for p in result["results"]]

    @json_tool(mcp)
    def get_paper_detail(paper_id: str) -> dict:
        """Get full details of a paper by its ID, including title, abstract, summary, doi, year, venue,
        reading_status, rating, bookmarked, color, and metadata_source."""
        paper = get_paper(get_driver(), paper_id)
        if not paper:
            return {"error": f"Paper {paper_id} not found"}
        # Omit raw_text — too large for tool output
        paper.pop("raw_text", None)
        return paper

    @mcp.tool()
    def get_paper_concepts(paper_id: str) -> list[dict]:
        """List the interactive concepts detected on a paper's PDF pages (Concepts tab in the app).
        Each entry has page (0-based), label, type (formula / graph / 2d-text / 2d-anim), context,
        and the generated visualisation spec if one exists (null otherwise)."""
        return [
            {k: c.get(k) for k in ("id", "page", "label", "type", "context", "spec")}
            for c in list_concepts(get_driver(), paper_id)
        ]

    @mcp.tool()
    def add_paper_metadata(
        title: str,
        year: int | None = None,
        doi: str | None = None,
        abstract: str | None = None,
        venue: str | None = None,
        document_type: str | None = None,
        published_date: str | None = None,
    ) -> dict:
        """Add a paper to the library without a PDF (e.g. from a citation or URL).

        document_type is one of "paper" (default), "book", "lecture_deck", or
        "news_article". For a news article, put the outlet in `venue` and the
        full publication date (YYYY-MM-DD) in `published_date`.
        Returns the new paper with its id that you can use with other tools."""
        return create_paper(get_driver(), {
            "title": title,
            "year": year,
            "doi": doi,
            "abstract": abstract,
            "venue": venue,
            "document_type": document_type,
            "published_date": published_date,
            "metadata_source": "manual",
        })

    @mcp.tool()
    def set_reading_status(paper_id: str, status: str) -> dict:
        """Set the reading status of a paper. status must be 'unread', 'reading', or 'read'."""
        if status not in ("unread", "reading", "read"):
            return {"error": "status must be 'unread', 'reading', or 'read'"}
        paper = update_paper(get_driver(), paper_id, {"reading_status": status})
        if not paper:
            return {"error": f"Paper {paper_id} not found"}
        return {"id": paper_id, "reading_status": status}

    @mcp.tool()
    def rate_paper(paper_id: str, rating: int) -> dict:
        """Rate a paper from 1 to 5 stars. Pass 0 to clear the rating (0 is a special clear value, not a valid star rating)."""
        if rating not in range(0, 6):
            return {"error": "rating must be between 0 (clear) and 5 (stars)"}
        paper = update_paper(get_driver(), paper_id, {"rating": rating if rating > 0 else None})
        if not paper:
            return {"error": f"Paper {paper_id} not found"}
        return {"id": paper_id, "rating": rating}

    @mcp.tool()
    def bookmark_paper(paper_id: str, bookmarked: bool = True) -> dict:
        """Bookmark or un-bookmark a paper."""
        paper = update_paper(get_driver(), paper_id, {"bookmarked": bookmarked})
        if not paper:
            return {"error": f"Paper {paper_id} not found"}
        return {"id": paper_id, "bookmarked": bookmarked}

    @mcp.tool()
    def get_random_paper(reading_status: str = "") -> dict:
        """Return a random paper from the library, optionally filtered by reading_status.
        Useful for discovering papers to read next."""
        paper = random_paper(get_driver(), reading_status=reading_status or None)
        if not paper:
            return {"error": "No papers found"}
        paper.pop("raw_text", None)
        return paper
