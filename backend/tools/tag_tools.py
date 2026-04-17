from mcp.server.fastmcp import FastMCP
from db.connection import get_driver
from db.queries.tags import get_or_create_tag, tag_paper, untag_paper, list_tags as _list_tags
from db.queries.topics import get_or_create_topic, link_paper_topic, list_topics as _list_topics


def register(mcp: FastMCP):
    @mcp.tool()
    def tag_paper_with(paper_id: str, tag_name: str) -> dict:
        """Add a free-form tag to a paper. The tag is created if it doesn't exist.
        Tags are your personal labels — use them freely (e.g. 'to-read', 'from-Nele', 'arxiv')."""
        driver = get_driver()
        tag = get_or_create_tag(driver, tag_name)
        tag_paper(driver, paper_id, tag["id"])
        return {"status": "ok", "tag": tag}

    @mcp.tool()
    def list_tags() -> list[dict]:
        """List all tags with their paper counts. Useful for discovering what tags exist."""
        return _list_tags(get_driver())

    @mcp.tool()
    def add_topic(paper_id: str, topic_name: str) -> dict:
        """Link a research topic to a paper. Topics are formal research areas (e.g. 'Transformers', 'NLP').
        The topic is created if it doesn't exist."""
        driver = get_driver()
        topic = get_or_create_topic(driver, topic_name)
        link_paper_topic(driver, paper_id, topic["id"])
        return {"status": "ok", "topic": topic}

    @mcp.tool()
    def list_topics() -> list[dict]:
        """List all research topics with their paper counts."""
        return _list_topics(get_driver())
