from mcp.server.fastmcp import FastMCP
from db.connection import get_driver
from db.queries.projects import (
    create_project as _create_project,
    list_projects as _list_projects,
    add_paper_to_project as _add_paper,
    get_project_papers,
)


def register(mcp: FastMCP):
    @mcp.tool()
    def list_projects() -> list[dict]:
        """List all projects with their name, status, description, and id."""
        return _list_projects(get_driver())

    @mcp.tool()
    def create_project(name: str, description: str = "") -> dict:
        """Create a new project to group related papers.
        Returns the project with its id."""
        return _create_project(get_driver(), {"name": name, "description": description})

    @mcp.tool()
    def add_to_project(paper_id: str, project_id: str) -> dict:
        """Add a paper to a project. Use list_projects to find project ids.
        Returns status ok if successful."""
        _add_paper(get_driver(), project_id, paper_id)
        return {"status": "ok", "paper_id": paper_id, "project_id": project_id}

    @mcp.tool()
    def list_project_papers(project_id: str) -> list[dict]:
        """List all papers in a project. Returns paper metadata without raw_text."""
        papers = get_project_papers(get_driver(), project_id)
        for p in papers:
            p.pop("raw_text", None)
        return papers
