"""
Tests for the search endpoint and db.queries.search.

Integration tests create real Neo4j data — mark with @pytest.mark.integration.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from db.connection import get_driver
from db.queries.papers import create_paper, delete_paper
from db.queries.tags import get_or_create_tag, tag_paper
from db.queries.topics import get_or_create_topic, link_paper_topic


# ── helpers ────────────────────────────────────────────────────────────────────

@pytest.fixture
def three_papers():
    driver = get_driver()
    p1 = create_paper(driver, {
        "title": "Transformer Attention Mechanisms",
        "abstract": "We study attention in deep learning.",
        "summary": "A deep dive into transformer models.",
    })
    p2 = create_paper(driver, {
        "title": "Graph Neural Networks",
        "abstract": "We propose a new GNN architecture.",
        "summary": "GNNs applied to molecular data.",
    })
    p3 = create_paper(driver, {
        "title": "Reinforcement Learning Survey",
        "abstract": "Overview of RL methods.",
        "summary": "Comprehensive RL survey from 2023.",
    })
    yield p1, p2, p3
    for p in (p1, p2, p3):
        delete_paper(driver, p["id"])


# ── unit tests (no full-text index needed) ────────────────────────────────────

@pytest.mark.asyncio
async def test_search_empty_returns_all():
    """No q and no filters → returns all papers (up to limit)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search")
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert "total" in data
    assert isinstance(data["results"], list)


@pytest.mark.asyncio
async def test_search_no_results_returns_empty_list():
    """Query that matches nothing → empty results, not an error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search", params={"q": "xyzzy_nonexistent_term_12345"})
    assert r.status_code == 200
    assert r.json()["results"] == []
    assert r.json()["total"] == 0


# ── integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_fulltext_search_by_title(three_papers):
    p1, p2, p3 = three_papers
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search", params={"q": "Transformer"})
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["results"]]
    assert p1["id"] in ids
    assert p2["id"] not in ids


@pytest.mark.integration
async def test_fulltext_search_by_summary(three_papers):
    p1, p2, p3 = three_papers
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search", params={"q": "molecular"})
    ids = [x["id"] for x in r.json()["results"]]
    assert p2["id"] in ids


@pytest.mark.integration
async def test_filter_by_tag(three_papers):
    p1, p2, p3 = three_papers
    driver = get_driver()
    tag = get_or_create_tag(driver, "arxiv-search-test")
    tag_paper(driver, p1["id"], tag["id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search", params={"tag": "arxiv-search-test"})

    ids = [x["id"] for x in r.json()["results"]]
    assert p1["id"] in ids
    assert p2["id"] not in ids


@pytest.mark.integration
async def test_filter_by_topic(three_papers):
    p1, p2, p3 = three_papers
    driver = get_driver()
    topic = get_or_create_topic(driver, "TestTopicSearch")
    link_paper_topic(driver, p2["id"], topic["id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search", params={"topic": "TestTopicSearch"})

    ids = [x["id"] for x in r.json()["results"]]
    assert p2["id"] in ids
    assert p3["id"] not in ids


@pytest.mark.integration
async def test_combined_q_and_tag(three_papers):
    """Full-text match AND tag filter — intersection."""
    p1, p2, p3 = three_papers
    driver = get_driver()
    tag = get_or_create_tag(driver, "combo-test-tag")
    # Tag p1 (Transformer) but not p2 (GNN, also has "deep" in abstract if we add)
    tag_paper(driver, p1["id"], tag["id"])
    tag_paper(driver, p2["id"], tag["id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # "Transformer" only matches p1; tag="combo-test-tag" matches p1 and p2
        # intersection → only p1
        r = await c.get("/search", params={"q": "Transformer", "tag": "combo-test-tag"})

    ids = [x["id"] for x in r.json()["results"]]
    assert p1["id"] in ids
    assert p2["id"] not in ids


@pytest.mark.integration
async def test_search_note_content(three_papers):
    """Notes are searchable via note_search fulltext index."""
    from db.queries.notes import upsert_note
    p1, p2, p3 = three_papers
    driver = get_driver()
    upsert_note(driver, p3["id"], "This paper covers epsilon-greedy RL exploration")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search", params={"q": "epsilon-greedy"})

    ids = [x["id"] for x in r.json()["results"]]
    assert p3["id"] in ids
