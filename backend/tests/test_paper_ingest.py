"""
Tests for the full paper ingestion pipeline (POST /papers/upload).

Unit tests mock Drive, AI, and db — run without external services.
Integration tests hit real services — mark with @pytest.mark.integration.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from io import BytesIO

from main import app
from db.connection import get_driver
from db.queries.papers import delete_paper

FIXTURE = Path(__file__).parent / "fixtures" / "attention.pdf"

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_mock_meta(**overrides):
    base = {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": 2017,
        "doi": "arXiv:1706.03762",
        "abstract": "We propose the Transformer.",
        "venue": "NeurIPS",
        "citation_count": 50000,
        "topics": ["Natural Language Processing", "Machine Learning"],
        "metadata_source": "semantic_scholar",
        "raw_text": "Attention Is All You Need\nVaswani et al.",
    }
    base.update(overrides)
    return base


# ── unit tests (mocked) ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_creates_paper_and_returns_ingest_out():
    meta = _make_mock_meta()
    with patch("routers.papers.extract_metadata", return_value=meta), \
         patch("routers.papers.upload_pdf", return_value="drive123"), \
         patch("routers.papers.summarize_paper", return_value="## Summary\nGreat paper."), \
         patch("routers.papers.get_or_create_person") as mock_person, \
         patch("routers.papers.link_author"), \
         patch("routers.papers.get_or_create_topic") as mock_topic, \
         patch("routers.papers.link_paper_topic"):

        mock_person.return_value = {"id": "pid1", "name": "Vaswani"}
        mock_topic.return_value = {"id": "tid1", "name": "NLP"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/papers/upload",
                files={"file": ("attention.pdf", FIXTURE.read_bytes(), "application/pdf")},
            )

    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Attention Is All You Need"
    assert data["metadata_source"] == "semantic_scholar"
    assert data["drive_url"].startswith("https://drive.google.com")
    assert "drive123" in data["drive_url"]

    # clean up real Neo4j node
    delete_paper(get_driver(), data["id"])


@pytest.mark.asyncio
async def test_upload_title_override():
    meta = _make_mock_meta(title="Wrong Title From PDF")
    with patch("routers.papers.extract_metadata", return_value=meta), \
         patch("routers.papers.upload_pdf", return_value="drive456"), \
         patch("routers.papers.summarize_paper", return_value="Summary"), \
         patch("routers.papers.get_or_create_person", return_value={"id": "p", "name": "A"}), \
         patch("routers.papers.link_author"), \
         patch("routers.papers.get_or_create_topic", return_value={"id": "t", "name": "X"}), \
         patch("routers.papers.link_paper_topic"):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/papers/upload",
                files={"file": ("test.pdf", FIXTURE.read_bytes(), "application/pdf")},
                data={"title_override": "Correct Title"},
            )

    assert r.status_code == 201
    assert r.json()["title"] == "Correct Title"
    delete_paper(get_driver(), r.json()["id"])


@pytest.mark.asyncio
async def test_upload_drive_failure_returns_503():
    meta = _make_mock_meta()
    with patch("routers.papers.extract_metadata", return_value=meta), \
         patch("routers.papers.upload_pdf", side_effect=Exception("Drive down")):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/papers/upload",
                files={"file": ("test.pdf", b"fake pdf", "application/pdf")},
            )

    assert r.status_code == 503
    assert "Drive" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_claude_failure_saves_paper_without_summary():
    """Claude failing should not abort the ingestion."""
    meta = _make_mock_meta()
    with patch("routers.papers.extract_metadata", return_value=meta), \
         patch("routers.papers.upload_pdf", return_value="driveXXX"), \
         patch("routers.papers.summarize_paper", side_effect=Exception("Claude down")), \
         patch("routers.papers.get_or_create_person", return_value={"id": "p", "name": "A"}), \
         patch("routers.papers.link_author"), \
         patch("routers.papers.get_or_create_topic", return_value={"id": "t", "name": "X"}), \
         patch("routers.papers.link_paper_topic"):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/papers/upload",
                files={"file": ("test.pdf", FIXTURE.read_bytes(), "application/pdf")},
            )

    assert r.status_code == 201
    assert r.json()["summary"] is None
    delete_paper(get_driver(), r.json()["id"])


@pytest.mark.asyncio
async def test_upload_authors_and_topics_in_response():
    meta = _make_mock_meta()
    with patch("routers.papers.extract_metadata", return_value=meta), \
         patch("routers.papers.upload_pdf", return_value="drive789"), \
         patch("routers.papers.summarize_paper", return_value="Summary"), \
         patch("routers.papers.get_or_create_person") as mock_person, \
         patch("routers.papers.link_author"), \
         patch("routers.papers.get_or_create_topic") as mock_topic, \
         patch("routers.papers.link_paper_topic"):

        mock_person.side_effect = lambda d, name: {"id": "p", "name": name}
        mock_topic.side_effect = lambda d, name: {"id": "t", "name": name}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/papers/upload",
                files={"file": ("test.pdf", FIXTURE.read_bytes(), "application/pdf")},
            )

    data = r.json()
    assert "Ashish Vaswani" in data["authors"]
    assert "Natural Language Processing" in data["topics_auto_added"]
    delete_paper(get_driver(), data["id"])


# ── integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_upload_real_pdf_end_to_end():
    """Requires Neo4j, Google Drive, and Anthropic API key."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/papers/upload",
            files={"file": ("attention.pdf", FIXTURE.read_bytes(), "application/pdf")},
        )
    assert r.status_code == 201
    data = r.json()
    assert data["title"]
    assert data["drive_file_id"]
    assert data["metadata_source"] in ("semantic_scholar", "crossref", "llm", "heuristic")
    # clean up
    delete_paper(get_driver(), data["id"])
