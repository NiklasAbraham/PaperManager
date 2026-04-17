import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from db.connection import get_driver, close_driver
from db.queries.papers import create_paper, delete_paper


@pytest.fixture
def paper():
    d = get_driver()
    p = create_paper(d, {"title": "Tag/Topic Test Paper"})
    yield p
    delete_paper(d, p["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tag_paper(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/papers/{paper['id']}/tags", json={"name": "arxiv"})
    assert r.status_code == 201


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tag_idempotent(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(f"/papers/{paper['id']}/tags", json={"name": "duplicate-tag"})
        await c.post(f"/papers/{paper['id']}/tags", json={"name": "duplicate-tag"})
    driver = get_driver()
    with driver.session() as s:
        result = s.run(
            "MATCH (p:Paper {id:$pid})-[:TAGGED]->(t:Tag {name:'duplicate-tag'}) RETURN count(*) AS n",
            pid=paper["id"],
        )
        assert result.single()["n"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tags_with_count(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(f"/papers/{paper['id']}/tags", json={"name": "test-list-tag"})
        r = await c.get("/tags")
    assert r.status_code == 200
    tags = r.json()
    names = [t["name"] for t in tags]
    assert "test-list-tag" in names
    match = next(t for t in tags if t["name"] == "test-list-tag")
    assert match["paper_count"] >= 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_untag_paper(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(f"/papers/{paper['id']}/tags", json={"name": "remove-me"})
        r_del = await c.delete(f"/papers/{paper['id']}/tags/remove-me")
    assert r_del.status_code == 204
    driver = get_driver()
    with driver.session() as s:
        result = s.run(
            "MATCH (p:Paper {id:$pid})-[:TAGGED]->(t:Tag {name:'remove-me'}) RETURN count(*) AS n",
            pid=paper["id"],
        )
        assert result.single()["n"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_topic_and_list(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/papers/{paper['id']}/topics", json={"name": "NLP"})
        assert r.status_code == 201
        r_list = await c.get("/topics")
    names = [t["name"] for t in r_list.json()]
    assert "NLP" in names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_papers_by_tag(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(f"/papers/{paper['id']}/tags", json={"name": "unique-findme-tag"})
        r = await c.get("/tags/unique-findme-tag/papers")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert paper["id"] in ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_related_topics():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/topics/machine-learning/related/deep-learning")
    assert r.status_code == 201
    driver = get_driver()
    with driver.session() as s:
        result = s.run(
            "MATCH (a:Topic {name:'machine-learning'})-[:RELATED_TO]-(b:Topic {name:'deep-learning'}) RETURN count(*) AS n"
        )
        assert result.single()["n"] == 1
