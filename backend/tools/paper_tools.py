from mcp.server.fastmcp import FastMCP
from db.connection import get_driver
from db.queries.papers import create_paper, get_paper
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
    ) -> list[dict]:
        """Search papers by keyword, tag, topic, project, or person. All params optional.
        Returns a list of matching paper objects with id, title, year, summary, and metadata_source."""
        result = _search(
            get_driver(),
            q=query or None,
            tag=tag or None,
            topic=topic or None,
            project_id=project_id or None,
            person_id=person_id or None,
        )
        return result["results"]

    @mcp.tool()
    def get_paper_detail(paper_id: str) -> dict:
        """Get full details of a paper by its ID, including title, abstract, summary, doi, year, and metadata_source."""
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
    ) -> dict:
        """Add a paper to the library without a PDF (e.g. from a citation or URL).
        Returns the new paper with its id that you can use with other tools."""
        return create_paper(get_driver(), {
            "title": title,
            "year": year,
            "doi": doi,
            "abstract": abstract,
            "metadata_source": "manual",
        })
