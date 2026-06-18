"""
End-to-end mock tests — realistic user scenarios without Neo4j or LLM access.

These tests simulate full user workflows through the FastAPI HTTP layer,
using an in-memory graph store (FakeDriver) and mocked AI services.
They validate the complete request→router→query→response pipeline.

Run with: pytest tests/test_e2e_mock.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from tests.fake_neo4j import FakeDriver


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def fake_driver():
    """Fresh in-memory graph driver for each test."""
    return FakeDriver()


@pytest.fixture
def patched_app(fake_driver):
    """Patch the app so all endpoints use the fake driver and skip lifespan."""
    from db.connection import get_driver as original_get_driver
    from main import app

    with patch("db.connection._driver", fake_driver), \
         patch("db.connection.get_driver", return_value=fake_driver), \
         patch("services.auth.get_request_user", return_value="niklas"):
        # Override FastAPI dependency for endpoints using Depends(get_driver)
        app.dependency_overrides[original_get_driver] = lambda: fake_driver
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def client(patched_app):
    """Async HTTP client hitting the patched app."""
    async with AsyncClient(
        transport=ASGITransport(app=patched_app),
        base_url="http://localhost",
    ) as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 1: Paper CRUD lifecycle
# A researcher creates a paper, retrieves it, updates metadata, then deletes it.
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaperCRUDLifecycle:
    """Full paper create → read → update → delete flow."""

    @pytest.mark.asyncio
    async def test_create_paper(self, client, fake_driver):
        """User creates a paper with title and year."""
        r = await client.post("/papers", json={
            "title": "Attention Is All You Need",
            "year": 2017,
            "doi": "arXiv:1706.03762",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "Attention Is All You Need"
        assert data["year"] == 2017
        assert data["id"]  # UUID assigned

    @pytest.mark.asyncio
    async def test_full_crud_lifecycle(self, client, fake_driver):
        """Create → Get → Update → Delete a paper."""
        # Create
        r = await client.post("/papers", json={
            "title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "year": 2019,
            "doi": "arXiv:1810.04805",
            "abstract": "We introduce BERT.",
        })
        assert r.status_code == 201
        paper_id = r.json()["id"]

        # Get
        r = await client.get(f"/papers/{paper_id}")
        assert r.status_code == 200
        assert r.json()["title"] == "BERT: Pre-training of Deep Bidirectional Transformers"
        assert r.json()["abstract"] == "We introduce BERT."

        # Update
        r = await client.patch(f"/papers/{paper_id}", json={
            "reading_status": "reading",
            "rating": 5,
            "bookmarked": True,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["reading_status"] == "reading"
        assert data["rating"] == 5
        assert data["bookmarked"] is True

        # Delete
        r = await client.delete(f"/papers/{paper_id}")
        assert r.status_code == 204

        # Verify deleted
        r = await client.get(f"/papers/{paper_id}")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 2: Full paper upload pipeline (mocked AI + Drive)
# Simulates a user uploading a PDF — metadata extracted, Drive uploaded,
# summary generated, authors linked, topics assigned.
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaperUploadPipeline:
    """Full upload ingestion with mocked external services."""

    @pytest.mark.asyncio
    async def test_upload_full_pipeline(self, client, fake_driver):
        """Upload creates paper with authors, topics, and Drive link."""
        mock_meta = {
            "title": "GPT-4 Technical Report",
            "authors": ["OpenAI"],
            "year": 2023,
            "doi": "arXiv:2303.08774",
            "abstract": "We report the development of GPT-4.",
            "venue": "arXiv",
            "citation_count": 5000,
            "topics": ["Large Language Models", "Deep Learning"],
            "metadata_source": "semantic_scholar",
            "raw_text": "GPT-4 Technical Report\nOpenAI\n...",
        }

        with patch("routers.papers.extract_metadata", return_value=mock_meta), \
             patch("routers.papers.upload_pdf", return_value="drive_gpt4_id"), \
             patch("routers.papers.summarize_paper", return_value="## Summary\nGPT-4 is a large multimodal model."), \
             patch("routers.papers.get_or_create_person") as mock_person, \
             patch("routers.papers.link_author"), \
             patch("routers.papers.get_or_create_topic") as mock_topic, \
             patch("routers.papers.link_paper_topic"), \
             patch("routers.papers.find_duplicate", return_value=None), \
             patch("routers.papers.extract_references", return_value=[]), \
             patch("routers.papers.extract_figures", return_value=[]), \
             patch("routers.papers.extract_claims", return_value=[]), \
             patch("routers.papers.extract_affiliations_with_litellm", return_value=[]), \
             patch("config.settings") as mock_settings:

            mock_settings.litellm_embed_model = ""
            mock_settings.google_drive_folder_id = "test_folder"
            mock_person.return_value = {"id": "person-1", "name": "OpenAI"}
            mock_topic.side_effect = lambda d, name: {"id": f"topic-{name}", "name": name}

            pdf_bytes = b"%PDF-1.4 fake content for testing"
            r = await client.post(
                "/papers/upload",
                files={"file": ("gpt4.pdf", pdf_bytes, "application/pdf")},
            )

        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "GPT-4 Technical Report"
        assert data["metadata_source"] == "semantic_scholar"
        assert "drive_gpt4_id" in data.get("drive_url", "")
        assert "OpenAI" in data.get("authors", [])
        assert "Large Language Models" in data.get("topics_auto_added", [])

    @pytest.mark.asyncio
    async def test_upload_drive_failure_returns_503(self, client, fake_driver):
        """When Drive is down, upload returns 503 with helpful message."""
        mock_meta = {
            "title": "Test Paper",
            "authors": [],
            "year": 2024,
            "doi": None,
            "abstract": "Abstract",
            "venue": None,
            "citation_count": None,
            "topics": [],
            "metadata_source": "heuristic",
            "raw_text": "text",
        }

        with patch("routers.papers.extract_metadata", return_value=mock_meta), \
             patch("routers.papers.upload_pdf", side_effect=Exception("Drive service unavailable")):

            r = await client.post(
                "/papers/upload",
                files={"file": ("test.pdf", b"fake pdf", "application/pdf")},
            )

        assert r.status_code == 503
        assert "Drive" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_summary_failure_non_fatal(self, client, fake_driver):
        """LLM failure for summary shouldn't abort the upload."""
        mock_meta = {
            "title": "Robust Paper Without Summary",
            "authors": ["Author A"],
            "year": 2024,
            "doi": "10.1234/test",
            "abstract": "We present a robust paper.",
            "venue": "ICML",
            "citation_count": 100,
            "topics": ["Robustness"],
            "metadata_source": "crossref",
            "raw_text": "Full text here...",
        }

        with patch("routers.papers.extract_metadata", return_value=mock_meta), \
             patch("routers.papers.upload_pdf", return_value="drive_robust"), \
             patch("routers.papers.summarize_paper", side_effect=Exception("LLM timeout")), \
             patch("routers.papers.get_or_create_person", return_value={"id": "p1", "name": "Author A"}), \
             patch("routers.papers.link_author"), \
             patch("routers.papers.get_or_create_topic", return_value={"id": "t1", "name": "Robustness"}), \
             patch("routers.papers.link_paper_topic"), \
             patch("routers.papers.find_duplicate", return_value=None), \
             patch("routers.papers.extract_references", return_value=[]), \
             patch("routers.papers.extract_figures", return_value=[]), \
             patch("routers.papers.extract_claims", return_value=[]), \
             patch("routers.papers.extract_affiliations_with_litellm", return_value=[]), \
             patch("config.settings") as mock_settings:

            mock_settings.litellm_embed_model = ""
            mock_settings.google_drive_folder_id = "test_folder"

            r = await client.post(
                "/papers/upload",
                files={"file": ("robust.pdf", b"fake pdf", "application/pdf")},
            )

        assert r.status_code == 201
        assert r.json()["summary"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 3: People management and author linking
# A researcher creates people, links them as authors, and verifies connections.
# ═══════════════════════════════════════════════════════════════════════════════

class TestPeopleAndAuthors:
    """People CRUD and paper-author relationship management."""

    @pytest.mark.asyncio
    async def test_create_and_list_people(self, client, fake_driver):
        """Create multiple people and list them."""
        # Create people
        r1 = await client.post("/people", json={
            "name": "Yoshua Bengio",
            "affiliation": "Mila, Université de Montréal",
        })
        assert r1.status_code == 201
        assert r1.json()["name"] == "Yoshua Bengio"

        r2 = await client.post("/people", json={
            "name": "Geoffrey Hinton",
            "affiliation": "University of Toronto",
        })
        assert r2.status_code == 201

        # List
        r = await client.get("/people")
        assert r.status_code == 200
        people = r.json()
        assert len(people) >= 2
        names = [p["name"] for p in people]
        assert "Yoshua Bengio" in names
        assert "Geoffrey Hinton" in names

    @pytest.mark.asyncio
    async def test_link_author_to_paper(self, client, fake_driver):
        """Create paper and person, then link them as author."""
        # Create paper
        r = await client.post("/papers", json={
            "title": "Deep Learning",
            "year": 2015,
        })
        paper_id = r.json()["id"]

        # Create person
        r = await client.post("/people", json={
            "name": "Yann LeCun",
            "affiliation": "Meta AI / NYU",
        })
        person_id = r.json()["id"]

        # Link author
        r = await client.post(f"/papers/{paper_id}/authors", json={
            "person_id": person_id,
        })
        assert r.status_code == 201

        # Verify relationship exists in graph
        assert any(
            rel.rel_type == "AUTHORED_BY"
            for rel in fake_driver.store.relationships
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 4: Tags workflow
# User tags papers, lists tags, filters by tag, and removes tags.
# ═══════════════════════════════════════════════════════════════════════════════

class TestTagsWorkflow:
    """Tagging papers and filtering by tags."""

    @pytest.mark.asyncio
    async def test_tag_and_untag_paper(self, client, fake_driver):
        """Tag a paper, verify tag list, then remove the tag."""
        # Create paper
        r = await client.post("/papers", json={
            "title": "Variational Autoencoders",
            "year": 2014,
        })
        paper_id = r.json()["id"]

        # Tag it
        r = await client.post(f"/papers/{paper_id}/tags", json={"name": "generative-models"})
        assert r.status_code == 201

        # Check tags on paper
        r = await client.get(f"/papers/{paper_id}/tags")
        assert r.status_code == 200
        tags = r.json()
        assert any(t["name"] == "generative-models" for t in tags)

        # Remove tag
        r = await client.delete(f"/papers/{paper_id}/tags/generative-models")
        assert r.status_code == 204

        # Verify tag removed
        r = await client.get(f"/papers/{paper_id}/tags")
        assert r.status_code == 200
        assert not any(t["name"] == "generative-models" for t in r.json())

    @pytest.mark.asyncio
    async def test_list_all_tags(self, client, fake_driver):
        """List all available tags in the system."""
        # Create a paper and tag it
        r = await client.post("/papers", json={"title": "Test Paper"})
        paper_id = r.json()["id"]
        await client.post(f"/papers/{paper_id}/tags", json={"name": "important"})
        await client.post(f"/papers/{paper_id}/tags", json={"name": "to-read"})

        # List tags
        r = await client.get("/tags")
        assert r.status_code == 200
        tag_names = [t["name"] for t in r.json()]
        assert "important" in tag_names
        assert "to-read" in tag_names


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 5: Topics workflow
# Assign topics to papers and verify topic listing.
# ═══════════════════════════════════════════════════════════════════════════════

class TestTopicsWorkflow:
    """Topic assignment and listing."""

    @pytest.mark.asyncio
    async def test_assign_topics_to_paper(self, client, fake_driver):
        """Add topics to a paper and verify they appear."""
        # Create paper
        r = await client.post("/papers", json={
            "title": "ImageNet Classification with Deep Convolutional Neural Networks",
            "year": 2012,
        })
        paper_id = r.json()["id"]

        # Add topics
        r = await client.post(f"/papers/{paper_id}/topics", json={"name": "Computer Vision"})
        assert r.status_code == 201

        r = await client.post(f"/papers/{paper_id}/topics", json={"name": "Deep Learning"})
        assert r.status_code == 201

        # List all topics
        r = await client.get("/topics")
        assert r.status_code == 200
        topic_names = [t["name"] for t in r.json()]
        assert "Computer Vision" in topic_names
        assert "Deep Learning" in topic_names


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 6: Projects workflow
# Create projects, add papers to them, and manage the collection.
# ═══════════════════════════════════════════════════════════════════════════════

class TestProjectsWorkflow:
    """Project creation, paper assignment, and lifecycle."""

    @pytest.mark.asyncio
    async def test_project_lifecycle(self, client, fake_driver):
        """Create project → add papers → list → update → delete."""
        # Create project
        r = await client.post("/projects", json={
            "name": "Transformer Survey",
            "description": "Comprehensive survey of transformer architectures",
        })
        assert r.status_code == 201
        project = r.json()
        project_id = project["id"]
        assert project["name"] == "Transformer Survey"

        # Create two papers
        r1 = await client.post("/papers", json={"title": "Attention Is All You Need", "year": 2017})
        r2 = await client.post("/papers", json={"title": "BERT", "year": 2019})
        paper1_id = r1.json()["id"]
        paper2_id = r2.json()["id"]

        # Add papers to project
        r = await client.post(f"/projects/{project_id}/papers", json={"paper_id": paper1_id})
        assert r.status_code == 201
        r = await client.post(f"/projects/{project_id}/papers", json={"paper_id": paper2_id})
        assert r.status_code == 201

        # Update project
        r = await client.patch(f"/projects/{project_id}", json={
            "description": "Updated: survey of attention mechanisms",
        })
        assert r.status_code == 200
        assert "Updated" in r.json()["description"]

        # List projects
        r = await client.get("/projects")
        assert r.status_code == 200
        projects = r.json()
        assert any(p["name"] == "Transformer Survey" for p in projects)

        # Delete project
        r = await client.delete(f"/projects/{project_id}")
        assert r.status_code == 204


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 7: Notes workflow
# User adds notes to papers, updates them, and verifies content.
# ═══════════════════════════════════════════════════════════════════════════════

class TestNotesWorkflow:
    """Paper notes create and update."""

    @pytest.mark.asyncio
    async def test_create_and_update_note(self, client, fake_driver):
        """Create a note on a paper, then update it."""
        # Create paper
        r = await client.post("/papers", json={
            "title": "Neural Machine Translation by Jointly Learning to Align and Translate",
            "year": 2015,
        })
        paper_id = r.json()["id"]

        # Add note
        r = await client.put(f"/papers/{paper_id}/note", json={
            "content": "Key insight: attention mechanism allows model to focus on relevant parts of input.",
        })
        assert r.status_code == 200
        assert "attention mechanism" in r.json()["content"]

        # Get note
        r = await client.get(f"/papers/{paper_id}/note")
        assert r.status_code == 200
        assert "attention mechanism" in r.json()["content"]

        # Update note
        r = await client.put(f"/papers/{paper_id}/note", json={
            "content": "Updated: This paper introduced the attention mechanism for NMT. Foundational work.",
        })
        assert r.status_code == 200
        assert "Foundational work" in r.json()["content"]


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 8: Search functionality
# User searches papers by text query, by tag, and by topic filters.
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchWorkflow:
    """Search papers using various filters."""

    @pytest.mark.asyncio
    async def test_search_by_title(self, client, fake_driver):
        """Full-text search finds papers by title keywords."""
        # Create papers
        await client.post("/papers", json={"title": "Attention Is All You Need", "year": 2017})
        await client.post("/papers", json={"title": "BERT: Pre-training", "year": 2019})
        await client.post("/papers", json={"title": "GPT-3: Language Models", "year": 2020})

        # Search
        r = await client.get("/search", params={"q": "Attention"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) >= 1
        assert any("Attention" in p.get("title", "") for p in results)

    @pytest.mark.asyncio
    async def test_list_papers_default(self, client, fake_driver):
        """List papers returns all papers in library."""
        await client.post("/papers", json={"title": "Paper A", "year": 2020})
        await client.post("/papers", json={"title": "Paper B", "year": 2021})

        r = await client.get("/papers")
        assert r.status_code == 200
        papers = r.json()
        assert len(papers) >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 9: Stats dashboard
# Verifies the stats endpoint aggregates data correctly.
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatsDashboard:
    """Stats endpoint returns correct aggregations."""

    @pytest.mark.asyncio
    async def test_stats_counts(self, client, fake_driver):
        """Stats reflects the current library state."""
        # Create some entities
        await client.post("/papers", json={"title": "Paper 1", "year": 2020})
        await client.post("/papers", json={"title": "Paper 2", "year": 2021})
        await client.post("/people", json={"name": "Researcher A"})

        r = await client.get("/stats")
        assert r.status_code == 200
        data = r.json()
        assert "counts" in data
        assert data["counts"]["papers"] >= 2
        assert data["counts"]["authors"] >= 1

    @pytest.mark.asyncio
    async def test_stats_papers_by_year(self, client, fake_driver):
        """Papers by year distribution is correct."""
        await client.post("/papers", json={"title": "Paper 2020", "year": 2020})
        await client.post("/papers", json={"title": "Paper 2021a", "year": 2021})
        await client.post("/papers", json={"title": "Paper 2021b", "year": 2021})

        r = await client.get("/stats")
        assert r.status_code == 200
        by_year = r.json()["papers_by_year"]
        year_map = {entry["year"]: entry["count"] for entry in by_year}
        assert year_map.get(2020) == 1
        assert year_map.get(2021) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 10: Graph visualization
# Verify the graph endpoint returns nodes and links correctly.
# ═══════════════════════════════════════════════════════════════════════════════

class TestGraphVisualization:
    """Graph endpoint returns structured data for visualization."""

    @pytest.mark.asyncio
    async def test_graph_returns_structure(self, client, fake_driver):
        """Graph endpoint returns nodes and links arrays."""
        # Add some data
        await client.post("/papers", json={"title": "Graph Test Paper", "year": 2023})

        r = await client.get("/graph")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert "links" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["links"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 11: Health endpoint
# Verify the health check works with mocked driver.
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """Health check responds correctly."""

    @pytest.mark.asyncio
    async def test_health_ok(self, client, fake_driver):
        """Health endpoint confirms service is running."""
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["neo4j"] == "connected"


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 12: Complete researcher workflow (end-to-end)
# Simulates a researcher's full session: upload paper, tag it, assign topics,
# add to project, write notes, search for it, check stats.
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompleteResearcherWorkflow:
    """Full realistic researcher session from start to finish."""

    @pytest.mark.asyncio
    async def test_full_researcher_session(self, client, fake_driver):
        """
        Simulates: Login → Upload paper → Tag → Topic → Project → Notes → Search → Stats

        This represents the typical first interaction a researcher would have
        with PaperManager when adding a new paper to their library.
        """
        # Step 1: Check health
        r = await client.get("/health")
        assert r.status_code == 200

        # Step 2: Create a project for organizing papers
        r = await client.post("/projects", json={
            "name": "Reinforcement Learning Survey",
            "description": "Collecting key RL papers for literature review",
        })
        assert r.status_code == 201
        project_id = r.json()["id"]

        # Step 3: Manually add a paper (not from PDF)
        r = await client.post("/papers", json={
            "title": "Playing Atari with Deep Reinforcement Learning",
            "year": 2013,
            "doi": "arXiv:1312.5602",
            "abstract": "We present the first deep learning model to successfully learn control policies directly from high-dimensional sensory input using reinforcement learning.",
        })
        assert r.status_code == 201
        paper1_id = r.json()["id"]

        # Step 4: Tag the paper
        r = await client.post(f"/papers/{paper1_id}/tags", json={"name": "reinforcement-learning"})
        assert r.status_code == 201
        r = await client.post(f"/papers/{paper1_id}/tags", json={"name": "foundational"})
        assert r.status_code == 201

        # Step 5: Assign topics
        r = await client.post(f"/papers/{paper1_id}/topics", json={"name": "Reinforcement Learning"})
        assert r.status_code == 201
        r = await client.post(f"/papers/{paper1_id}/topics", json={"name": "Deep Learning"})
        assert r.status_code == 201

        # Step 6: Add to project
        r = await client.post(f"/projects/{project_id}/papers", json={"paper_id": paper1_id})
        assert r.status_code == 201

        # Step 7: Add a second paper
        r = await client.post("/papers", json={
            "title": "Human-level control through deep reinforcement learning",
            "year": 2015,
            "doi": "10.1038/nature14236",
            "abstract": "We demonstrate that a deep Q-network agent is capable of learning successful policies directly from visual input.",
        })
        assert r.status_code == 201
        paper2_id = r.json()["id"]

        # Tag and categorize second paper
        await client.post(f"/papers/{paper2_id}/tags", json={"name": "reinforcement-learning"})
        await client.post(f"/papers/{paper2_id}/topics", json={"name": "Reinforcement Learning"})
        await client.post(f"/projects/{project_id}/papers", json={"paper_id": paper2_id})

        # Step 8: Create author and link
        r = await client.post("/people", json={
            "name": "Volodymyr Mnih",
            "affiliation": "DeepMind",
        })
        assert r.status_code == 201
        person_id = r.json()["id"]

        r = await client.post(f"/papers/{paper1_id}/authors", json={"person_id": person_id})
        assert r.status_code == 201

        # Step 9: Write notes
        r = await client.put(f"/papers/{paper1_id}/note", json={
            "content": "Seminal DQN paper. Key contributions:\n- First to combine deep learning with RL for Atari\n- Experience replay\n- Target network",
        })
        assert r.status_code == 200

        # Step 10: Search for the paper
        r = await client.get("/search", params={"q": "Atari"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert any("Atari" in p.get("title", "") for p in results)

        # Step 11: Update reading status
        r = await client.patch(f"/papers/{paper1_id}", json={"reading_status": "read"})
        assert r.status_code == 200
        assert r.json()["reading_status"] == "read"

        # Step 12: Verify stats reflect all our data
        r = await client.get("/stats")
        assert r.status_code == 200
        stats = r.json()
        assert stats["counts"]["papers"] >= 2
        assert stats["counts"]["authors"] >= 1
        assert stats["counts"]["projects"] >= 1

        # Step 13: Verify tags list
        r = await client.get("/tags")
        assert r.status_code == 200
        tag_names = [t["name"] for t in r.json()]
        assert "reinforcement-learning" in tag_names
        assert "foundational" in tag_names

        # Step 14: Verify topics list
        r = await client.get("/topics")
        assert r.status_code == 200
        topic_names = [t["name"] for t in r.json()]
        assert "Reinforcement Learning" in topic_names
        assert "Deep Learning" in topic_names

        # Step 15: Verify project contents
        r = await client.get(f"/projects/{project_id}")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_multi_paper_comparative_research(self, client, fake_driver):
        """
        Simulates a researcher comparing multiple papers in the same area:
        Upload several papers, organize them, write comparative notes.
        """
        # Create multiple papers in a research area
        papers = [
            {"title": "ResNet: Deep Residual Learning", "year": 2016, "abstract": "We present residual networks."},
            {"title": "DenseNet: Densely Connected Networks", "year": 2017, "abstract": "We propose dense connections."},
            {"title": "EfficientNet: Rethinking Model Scaling", "year": 2019, "abstract": "We propose compound scaling."},
        ]

        paper_ids = []
        for paper_data in papers:
            r = await client.post("/papers", json=paper_data)
            assert r.status_code == 201
            paper_ids.append(r.json()["id"])

        # Create a project for comparison
        r = await client.post("/projects", json={
            "name": "CNN Architecture Comparison",
            "description": "Comparing modern CNN architectures",
        })
        project_id = r.json()["id"]

        # Add all papers to project and tag them
        for pid in paper_ids:
            await client.post(f"/projects/{project_id}/papers", json={"paper_id": pid})
            await client.post(f"/papers/{pid}/tags", json={"name": "deep-learning"})
            await client.post(f"/papers/{pid}/topics", json={"name": "Computer Vision"})

        # Mark reading progress
        await client.patch(f"/papers/{paper_ids[0]}", json={"reading_status": "read", "rating": 5})
        await client.patch(f"/papers/{paper_ids[1]}", json={"reading_status": "read", "rating": 4})
        await client.patch(f"/papers/{paper_ids[2]}", json={"reading_status": "reading"})

        # Write comparative note on first paper
        await client.put(f"/papers/{paper_ids[0]}/note", json={
            "content": "ResNet's skip connections are foundational. Compare with DenseNet's dense connections and EfficientNet's scaling approach.",
        })

        # Verify the library state
        r = await client.get("/papers")
        assert r.status_code == 200
        assert len(r.json()) >= 3

        # Search within project's topic area
        r = await client.get("/search", params={"q": "scaling"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_duplicate_detection_workflow(self, client, fake_driver):
        """
        Simulates the deduplication check: user tries to add a paper that
        already exists (by title).
        """
        # Add first paper
        r = await client.post("/papers", json={
            "title": "Attention Is All You Need",
            "year": 2017,
            "doi": "arXiv:1706.03762",
        })
        assert r.status_code == 201

        # Check for duplicate before uploading
        r = await client.get("/papers/check-duplicate", params={
            "title": "Attention Is All You Need",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["duplicate"] is not None
        assert data["duplicate"]["title"] == "Attention Is All You Need"

    @pytest.mark.asyncio
    async def test_bookmark_and_rating_workflow(self, client, fake_driver):
        """User bookmarks important papers and rates them."""
        # Create papers
        r = await client.post("/papers", json={"title": "Important Paper", "year": 2023})
        paper_id = r.json()["id"]

        # Bookmark it
        r = await client.patch(f"/papers/{paper_id}", json={"bookmarked": True, "rating": 5})
        assert r.status_code == 200
        assert r.json()["bookmarked"] is True
        assert r.json()["rating"] == 5

        # Un-bookmark
        r = await client.patch(f"/papers/{paper_id}", json={"bookmarked": False})
        assert r.status_code == 200
        assert r.json()["bookmarked"] is False
