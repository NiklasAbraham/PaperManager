from mcp.server.fastmcp import FastMCP
from db.connection import get_driver
from db.queries.notes import get_paper_note, upsert_note, set_mentions
from services.note_parser import parse_mentions


def register(mcp: FastMCP):
    @mcp.tool()
    def get_note(paper_id: str) -> str:
        """Read the markdown note for a paper. Returns the raw markdown content, or an empty string if no note exists."""
        note = get_paper_note(get_driver(), paper_id)
        return note["content"] if note else ""

    @mcp.tool()
    def add_note(paper_id: str, content: str) -> dict:
        """Write or update the markdown note for a paper.
        Use @PersonName to link a person (creates graph relationship MENTIONS→Person).
        Use #TopicName to link a topic (creates MENTIONS→Topic).
        Multi-word names: use @First_Last (underscore becomes space).
        Returns the saved note with id and timestamps."""
        driver = get_driver()
        note = upsert_note(driver, paper_id, content)
        mentions = parse_mentions(content)
        set_mentions(driver, note["id"], mentions["people"], mentions["topics"])
        return note
