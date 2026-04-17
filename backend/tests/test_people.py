import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from db.connection import get_driver, close_driver
from db.queries.people import delete_person
from db.queries.papers import create_paper, delete_paper
from db.queries.topics import get_or_create_topic


@pytest.fixture
def driver():
    d = get_driver()
    yield d


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_person():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/people", json={"name": "Jan Müller", "affiliation": "TU Berlin"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Jan Müller"
    delete_person(get_driver(), body["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_people():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/people")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_link_author(driver):
    paper = create_paper(driver, {"title": "Test Authorship"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        pr = await c.post("/people", json={"name": "Test Author"})
        person_id = pr.json()["id"]
        r = await c.post(f"/papers/{paper['id']}/authors", json={"person_id": person_id})
    assert r.status_code == 201
    # Verify relationship exists
    with driver.session() as s:
        result = s.run(
            "MATCH (p:Paper {id:$pid})-[:AUTHORED_BY]->(per:Person {id:$peid}) RETURN count(*) AS n",
            pid=paper["id"], peid=person_id,
        )
        assert result.single()["n"] == 1
    delete_paper(driver, paper["id"])
    delete_person(driver, person_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_link_involves(driver):
    paper = create_paper(driver, {"title": "Involves Test"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        pr = await c.post("/people", json={"name": "Nele Test"})
        person_id = pr.json()["id"]
        r = await c.post(f"/papers/{paper['id']}/involves",
                         json={"person_id": person_id, "role": "feedback_needed"})
    assert r.status_code == 201
    with driver.session() as s:
        result = s.run(
            "MATCH (p:Paper {id:$pid})-[r:INVOLVES {role:'feedback_needed'}]->(per:Person {id:$peid}) RETURN count(*) AS n",
            pid=paper["id"], peid=person_id,
        )
        assert result.single()["n"] == 1
    delete_paper(driver, paper["id"])
    delete_person(driver, person_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_specialties(driver):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        pr = await c.post("/people", json={"name": "Specialty Person"})
        person_id = pr.json()["id"]
        r = await c.post(f"/people/{person_id}/specialties", json={"topic_name": "Graph Neural Networks"})
    assert r.status_code == 201
    with driver.session() as s:
        result = s.run(
            "MATCH (p:Person {id:$pid})-[:SPECIALIZES_IN]->(t:Topic {name:'Graph Neural Networks'}) RETURN count(*) AS n",
            pid=person_id,
        )
        assert result.single()["n"] == 1
    delete_person(driver, person_id)
