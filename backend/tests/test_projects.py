import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from db.connection import get_driver, close_driver
from db.queries.papers import create_paper, delete_paper, get_paper
from db.queries.projects import delete_project


@pytest.fixture
def paper():
    d = get_driver()
    p = create_paper(d, {"title": "Project Test Paper"})
    yield p
    delete_paper(d, p["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_project():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/projects", json={"name": "PhD Thesis", "status": "active"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "PhD Thesis"
    delete_project(get_driver(), body["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_paper_to_project(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        proj = await c.post("/projects", json={"name": "Test Project"})
        project_id = proj.json()["id"]
        r = await c.post(f"/projects/{project_id}/papers", json={"paper_id": paper["id"]})
        assert r.status_code == 201
        r_get = await c.get(f"/projects/{project_id}")
    papers = r_get.json()["papers"]
    assert any(p["id"] == paper["id"] for p in papers)
    delete_project(get_driver(), project_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_paper_idempotent(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        proj = await c.post("/projects", json={"name": "Idempotent Project"})
        project_id = proj.json()["id"]
        await c.post(f"/projects/{project_id}/papers", json={"paper_id": paper["id"]})
        await c.post(f"/projects/{project_id}/papers", json={"paper_id": paper["id"]})
    driver = get_driver()
    with driver.session() as s:
        result = s.run(
            "MATCH (p:Paper {id:$pid})-[:IN_PROJECT]->(proj:Project {id:$projid}) RETURN count(*) AS n",
            pid=paper["id"], projid=project_id,
        )
        assert result.single()["n"] == 1
    delete_project(driver, project_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_project_keeps_papers(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        proj = await c.post("/projects", json={"name": "Delete Project"})
        project_id = proj.json()["id"]
        await c.post(f"/projects/{project_id}/papers", json={"paper_id": paper["id"]})
        r_del = await c.delete(f"/projects/{project_id}")
    assert r_del.status_code == 204
    assert get_paper(get_driver(), paper["id"]) is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_link_projects():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        pa = (await c.post("/projects", json={"name": "Project A"})).json()
        pb = (await c.post("/projects", json={"name": "Project B"})).json()
        r = await c.post(f"/projects/{pa['id']}/related/{pb['id']}")
    assert r.status_code == 201
    driver = get_driver()
    with driver.session() as s:
        result = s.run(
            "MATCH (a:Project {id:$aid})-[:RELATED_TO]-(b:Project {id:$bid}) RETURN count(*) AS n",
            aid=pa["id"], bid=pb["id"],
        )
        assert result.single()["n"] == 1
    delete_project(driver, pa["id"])
    delete_project(driver, pb["id"])
