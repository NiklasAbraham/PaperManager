from mcp.server.fastmcp import FastMCP
from db.connection import get_driver
from db.queries.papers import create_paper, get_paper, update_paper, random_paper
from db.queries.search import search_papers as _search
from db.queries.people import list_people as _list_people
from db.queries.tags import list_tags as _list_tags
from db.queries.topics import list_topics as _list_topics


def register(mcp: FastMCP):
    @mcp.tool()
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
    ) -> list[dict]:
        """Search papers by keyword, tag, topic, project, or person. All params optional.
        reading_status can be 'unread', 'reading', or 'read'.
        Returns a list of matching paper objects with id, title, year, summary, and metadata_source."""
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
        )
        return result["results"]

    @mcp.tool()
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
    def add_paper_metadata(
        title: str,
        year: int | None = None,
        doi: str | None = None,
        abstract: str | None = None,
        venue: str | None = None,
    ) -> dict:
        """Add a paper to the library without a PDF (e.g. from a citation or URL).
        Returns the new paper with its id that you can use with other tools."""
        return create_paper(get_driver(), {
            "title": title,
            "year": year,
            "doi": doi,
            "abstract": abstract,
            "venue": venue,
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
