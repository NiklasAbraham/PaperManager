from mcp.server.fastmcp import FastMCP
from db.connection import get_driver
from db.queries.people import (
    create_person, get_or_create_person, list_people as _list_people,
    link_author, link_involves, get_papers_by_person
)


def register(mcp: FastMCP):
    @mcp.tool()
    def list_people() -> list[dict]:
        """List all people in the network with their names, affiliations, and ids."""
        return _list_people(get_driver())

    @mcp.tool()
    def add_person(name: str, affiliation: str = "") -> dict:
        """Create a new person node. If a person with this name already exists, returns the existing one.
        Returns the person with their id."""
        return get_or_create_person(get_driver(), name)

    @mcp.tool()
    def link_person_to_paper(paper_id: str, person_name: str, role: str) -> dict:
        """Link a person to a paper with a workflow role.
        Common roles: 'feedback_needed', 'working_on', 'shared_by', 'collaborating', 'supervisor'.
        The person is looked up by name — created if not found.
        Returns the person node."""
        driver = get_driver()
        person = get_or_create_person(driver, person_name)
        link_involves(driver, paper_id, person["id"], role)
        return person

    @mcp.tool()
    def get_person_papers(person_id: str) -> list[dict]:
        """Get all papers associated with a person (authored, involved, etc.).
        Returns papers with rel_type ('AUTHORED_BY' or 'INVOLVES') and optional role."""
        return get_papers_by_person(get_driver(), person_id)
