from mcp.server.fastmcp import FastMCP
from tools._compact import json_tool
from db.connection import get_driver
from db.queries.visibility import paper_visibility_clause, project_visibility_clause
from db.queries.projects import (
    create_project as _create_project,
    list_projects as _list_projects,
    add_paper_to_project as _add_paper,
    get_project_papers,
)


def link_paper_to_project(driver, paper_id: str, project: str) -> dict:
    """MERGE paper -> project, the project given by id or (case-insensitive) name. Says
    whether the link is new, and errors instead of a silent no-op when the paper or the
    project is not there (or not visible), or the name names several projects."""
    pvis, pparams = paper_visibility_clause("p")
    jvis, jparams = project_visibility_clause("pr")
    project = (project or "").strip()
    with driver.session() as s:
        projects = s.run(
            f"""MATCH (pr:Project) WHERE (pr.id = $v OR toLower(pr.name) = toLower($v)) AND {jvis}
                RETURN pr.id AS id, pr.name AS name, pr.id = $v AS exact""",
            v=project, **jparams).data()
        exact = [r for r in projects if r["exact"]]
        projects = exact or projects
        if not projects:
            return {"status": "error", "error": f"Project not found: {project}. Call list_projects.",
                    "paper_id": paper_id, "project_id": project}
        if len(projects) > 1:
            return {"status": "error", "error": f"'{project}' names {len(projects)} projects; pass the id.",
                    "paper_id": paper_id, "project_ids": [r["id"] for r in projects]}
        pr = projects[0]
        rec = s.run(
            f"""MATCH (p:Paper {{id: $pid}}) WHERE {pvis}
                MATCH (pr:Project {{id: $prid}})
                OPTIONAL MATCH (p)-[old:IN_PROJECT]->(pr)
                WITH p, pr, old IS NOT NULL AS already
                MERGE (p)-[:IN_PROJECT]->(pr)
                RETURN already""",
            pid=paper_id, prid=pr["id"], **pparams).single()
    if rec is None:
        return {"status": "error", "error": f"Paper not found: {paper_id}", "paper_id": paper_id,
                "project_id": pr["id"]}
    return {"status": "ok", "paper_id": paper_id, "project_id": pr["id"], "project": pr["name"],
            "linked": "already" if rec["already"] else "linked"}


def register(mcp: FastMCP):
    @json_tool(mcp)
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
        """Add a paper to a project (`project_id`: id or exact name). Returns status ok
        with linked (new link) or already (was in it), or an error if either is not found."""
        return link_paper_to_project(get_driver(), paper_id, project_id)

    @json_tool(mcp)
    def list_project_papers(project_id: str) -> list[dict]:
        """List all papers in a project. Returns paper metadata without raw_text."""
        papers = get_project_papers(get_driver(), project_id)
        for p in papers:
            p.pop("raw_text", None)
        return papers
