import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from db.connection import get_driver, close_driver
from db.queries.papers import delete_paper

BASE = "/papers"


@pytest.fixture(autouse=True)
def cleanup():
    created = []
    yield created
    # delete any papers created during the test
    driver = get_driver()
    for pid in created:
        delete_paper(driver, pid)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_paper(cleanup):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(BASE, json={"title": "Test Paper", "year": 2024})
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert body["title"] == "Test Paper"
    assert body["year"] == 2024
    cleanup.append(body["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_paper(cleanup):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post(BASE, json={"title": "Fetch Me"})
        paper_id = create.json()["id"]
        cleanup.append(paper_id)
        r = await c.get(f"{BASE}/{paper_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "Fetch Me"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_paper_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"{BASE}/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_papers(cleanup):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post(BASE, json={"title": "Paper A"})
        r2 = await c.post(BASE, json={"title": "Paper B"})
        cleanup += [r1.json()["id"], r2.json()["id"]]
        r = await c.get(BASE)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_paper(cleanup):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post(BASE, json={"title": "Old Title"})
        paper_id = create.json()["id"]
        cleanup.append(paper_id)
        r = await c.patch(
            f"{BASE}/{paper_id}",
            json={"title": "New Title", "metadata_source": "manual"},
        )
    assert r.status_code == 200
    assert r.json()["title"] == "New Title"
    assert r.json()["metadata_source"] == "manual"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_paper():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post(BASE, json={"title": "Delete Me"})
        paper_id = create.json()["id"]
        r_del = await c.delete(f"{BASE}/{paper_id}")
        r_get = await c.get(f"{BASE}/{paper_id}")
    assert r_del.status_code == 204
    assert r_get.status_code == 404
