import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from db.connection import get_driver, close_driver
from db.queries.papers import create_paper, delete_paper


@pytest.fixture
def paper():
    d = get_driver()
    p = create_paper(d, {"title": "Notes Test Paper"})
    yield p
    delete_paper(d, p["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_put_and_get_note(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r_put = await c.put(f"/papers/{paper['id']}/note", json={"content": "My first note."})
        assert r_put.status_code == 200
        r_get = await c.get(f"/papers/{paper['id']}/note")
    assert r_get.status_code == 200
    assert r_get.json()["content"] == "My first note."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_note_upsert(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put(f"/papers/{paper['id']}/note", json={"content": "Version 1"})
        await c.put(f"/papers/{paper['id']}/note", json={"content": "Version 2"})
        r = await c.get(f"/papers/{paper['id']}/note")
    assert r.json()["content"] == "Version 2"
    # Only one note node exists
    driver = get_driver()
    with driver.session() as s:
        result = s.run(
            "MATCH (p:Paper {id:$pid})-[:HAS_NOTE]->(n:Note) RETURN count(n) AS n",
            pid=paper["id"],
        )
        assert result.single()["n"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mentions_created(paper):
    from db.queries.people import delete_person
    driver = get_driver()
    # Clean up any stale nodes from previous runs
    with driver.session() as s:
        s.run("MATCH (p:Person) WHERE p.name = 'MentionTestPerson' DETACH DELETE p").consume()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        pr = await c.post("/people", json={"name": "MentionTestPerson"})
        person_id = pr.json()["id"]
        await c.put(f"/papers/{paper['id']}/note",
                    json={"content": "Ask @MentionTestPerson about #TransformerModels"})

    with driver.session() as s:
        # Person mention — check by name to avoid stale-id confusion
        r1 = s.run(
            "MATCH (n:Note)-[:MENTIONS]->(p:Person {name:'MentionTestPerson'}) RETURN count(*) AS n"
        )
        assert r1.single()["n"] >= 1
        # Topic mention (auto-created)
        r2 = s.run(
            "MATCH (n:Note)-[:MENTIONS]->(t:Topic {name:'TransformerModels'}) RETURN count(*) AS n"
        )
        assert r2.single()["n"] >= 1

    delete_person(driver, person_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mentions_updated(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        pr = await c.post("/people", json={"name": "OldMentionPerson"})
        person_id = pr.json()["id"]
        await c.put(f"/papers/{paper['id']}/note",
                    json={"content": "Note with @OldMentionPerson"})
        # Update note — remove the mention
        await c.put(f"/papers/{paper['id']}/note", json={"content": "Updated note, no mentions"})
    driver = get_driver()
    with driver.session() as s:
        result = s.run(
            "MATCH (n:Note)-[:MENTIONS]->(p:Person {id:$pid}) RETURN count(*) AS n",
            pid=person_id,
        )
        assert result.single()["n"] == 0
    from db.queries.people import delete_person
    delete_person(driver, person_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_note_not_found(paper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/papers/{paper['id']}/note")
    assert r.status_code == 404
