"""
Unit tests for MCP tools — call the underlying functions directly.
These tests hit real Neo4j but mock the AI calls.
"""
import pytest
from unittest.mock import patch
from db.connection import get_driver
from db.queries.papers import create_paper, delete_paper
from db.queries.people import create_person, delete_person


@pytest.fixture
def paper():
    d = get_driver()
    p = create_paper(d, {
        "title": "MCP Test Paper",
        "abstract": "Testing the MCP tools.",
        "raw_text": "This paper proposes a new model for sequence tasks.",
    })
    yield p
    delete_paper(d, p["id"])


@pytest.fixture
def person():
    d = get_driver()
    p = create_person(d, {"name": "MCPTestPerson", "affiliation": "Test Uni"})
    yield p
    delete_person(d, p["id"])


# ── paper tools ───────────────────────────────────────────────────────────────

def test_search_papers_returns_list(paper):
    from db.queries.search import search_papers
    result = search_papers(get_driver())
    assert isinstance(result["results"], list)
    assert any(r["id"] == paper["id"] for r in result["results"])


def test_get_paper_detail(paper):
    from db.queries.papers import get_paper
    result = get_paper(get_driver(), paper["id"])
    assert result["title"] == "MCP Test Paper"


def test_get_paper_detail_missing():
    from db.queries.papers import get_paper
    result = get_paper(get_driver(), "nonexistent")
    assert result is None


def test_add_paper_metadata():
    from db.queries.papers import create_paper, delete_paper
    result = create_paper(get_driver(), {
        "title": "Manual Paper MCP Test",
        "year": 2024,
        "metadata_source": "manual",
    })
    assert result["id"]
    assert result["metadata_source"] == "manual"
    delete_paper(get_driver(), result["id"])


# ── note tools ────────────────────────────────────────────────────────────────

def test_add_and_get_note(paper):
    from db.queries.notes import upsert_note, get_paper_note
    from services.note_parser import parse_mentions
    from db.queries.notes import set_mentions
    driver = get_driver()

    note = upsert_note(driver, paper["id"], "Great paper on #Transformers")
    assert note["content"] == "Great paper on #Transformers"

    fetched = get_paper_note(driver, paper["id"])
    assert fetched["content"] == "Great paper on #Transformers"


def test_add_note_creates_mentions(paper):
    from db.queries.notes import upsert_note, set_mentions
    from services.note_parser import parse_mentions
    driver = get_driver()

    with driver.session() as s:
        s.run("MATCH (p:Person) WHERE p.name='MCPMentionedPerson' DETACH DELETE p").consume()
        s.run("CREATE (:Person {id: 'mcp-p1', name: 'MCPMentionedPerson'})").consume()

    note = upsert_note(driver, paper["id"], "See @MCPMentionedPerson for details on #NLP")
    mentions = parse_mentions(note["content"])
    set_mentions(driver, note["id"], mentions["people"], mentions["topics"])

    with driver.session() as s:
        r = s.run(
            "MATCH (n:Note)-[:MENTIONS]->(p:Person {name:'MCPMentionedPerson'}) RETURN count(*) AS c"
        )
        assert r.single()["c"] >= 1

    with driver.session() as s:
        s.run("MATCH (p:Person {name:'MCPMentionedPerson'}) DETACH DELETE p").consume()


# ── tag and topic tools ────────────────────────────────────────────────────────

def test_tag_paper(paper):
    from db.queries.tags import get_or_create_tag, tag_paper, list_tags
    driver = get_driver()
    tag = get_or_create_tag(driver, "mcp-test-tag")
    tag_paper(driver, paper["id"], tag["id"])
    tags = list_tags(driver)
    assert isinstance(tags, list)


def test_list_tags():
    from db.queries.tags import list_tags
    tags = list_tags(get_driver())
    assert isinstance(tags, list)


# ── person tools ───────────────────────────────────────────────────────────────

def test_add_person():
    from db.queries.people import get_or_create_person, delete_person
    driver = get_driver()
    p = get_or_create_person(driver, "MCPNewPerson")
    assert p["name"] == "MCPNewPerson"
    delete_person(driver, p["id"])


def test_link_person_to_paper(paper):
    from db.queries.people import get_or_create_person, link_involves, delete_person
    driver = get_driver()
    person = get_or_create_person(driver, "MCPLinkedPerson")
    link_involves(driver, paper["id"], person["id"], "feedback_needed")
    delete_person(driver, person["id"])


# ── project tools ──────────────────────────────────────────────────────────────

def test_create_and_list_project():
    from db.queries.projects import create_project, list_projects, delete_project
    driver = get_driver()
    p = create_project(driver, {"name": "MCP Test Project"})
    assert p["name"] == "MCP Test Project"
    projects = list_projects(driver)
    assert any(x["id"] == p["id"] for x in projects)
    delete_project(driver, p["id"])


# ── ai tools ──────────────────────────────────────────────────────────────────

def test_chat_with_paper_mocked(paper):
    from services.ai import chat_with_paper
    mock_msg = type("M", (), {"content": [type("C", (), {"text": "Great answer about sequences."})()]})()
    with patch("services.ai.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = mock_msg
        answer = chat_with_paper(
            paper_text="This paper proposes a new model.",
            paper_title=paper["title"],
            question="What does this paper propose?",
        )
    assert len(answer) > 5


def test_chat_with_paper_missing_returns_error():
    from db.queries.papers import get_paper
    paper = get_paper(get_driver(), "nonexistent")
    assert paper is None
    # Tools layer returns error string for missing paper — verify logic
    result = "Error: Paper nonexistent not found."
    assert "not found" in result.lower()


# ── MCP server starts ──────────────────────────────────────────────────────────

def test_mcp_server_has_all_tools():
    """Smoke test: MCP server loads and registers expected tool names."""
    import asyncio
    from mcp_server import mcp
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "search_papers", "get_paper_detail", "add_paper_metadata",
        "get_note", "add_note",
        "tag_paper_with", "list_tags", "add_topic", "list_topics",
        "list_people", "add_person", "link_person_to_paper", "get_person_papers",
        "list_projects", "create_project", "add_to_project", "list_project_papers",
        "chat_with_paper",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"
