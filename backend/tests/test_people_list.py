"""GET /people is fetched by the People page, every paper page, the onboarding and the chat
mention pickers, one row per person. With 5,000 people it once weighed 2.9 MB (every person
property, plus every null field of PersonOut) and slowed all of them. These tests pin the row
shape and size, and the Cypher, without a database."""
import json

import pytest
from httpx import AsyncClient, ASGITransport

from db.queries import people as q
from main import app
from models.schemas import PersonListOut

# What one row may carry; a new person property must not reach the list by accident.
ALLOWED = {"id", "name", "affiliation", "citation_count", "h_index", "paper_count"}
MAX_ROW_BYTES = 250  # a typical row is ~120 B; 5,000 people stay under ~1.2 MB before gzip


class _Result(list):
    pass


class _Session:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.log.append(query)
        return _Result(self.rows)


class _Driver:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def session(self):
        return _Session(self.rows, self.log)


def _rows(n=300):
    # What the projection returns: only LIST_FIELDS (the Cypher is checked below).
    return [
        {"p": {"id": f"id-{i}", "name": f"Given{i} Family{i % 97}", "affiliation": "Some University, Somewhere",
               "citation_count": i * 10, "h_index": i % 40}, "paper_count": i % 5}
        for i in range(n)
    ]


def test_list_fields_are_the_schema_fields():
    assert set(q.LIST_FIELDS) | {"paper_count"} == ALLOWED
    assert set(PersonListOut.model_fields) == ALLOWED


@pytest.mark.parametrize("tag,fn", [(None, "list_people"), ("known", "list_people"), ("known", "list_people_without_tag")])
def test_cypher_projects_only_list_fields(tag, fn):
    d = _Driver(_rows(3))
    getattr(q, fn)(d, tag) if tag else q.list_people(d)
    cypher = d.log[0]
    assert "RETURN p {" in cypher, "the list query must project fields, not return whole nodes"
    for heavy in ("cv", "photo", "bio", "skills"):
        assert f".{heavy}" not in cypher
    for f in q.LIST_FIELDS:
        assert f".{f}" in cypher


def test_rows_sorted_by_surname_with_paper_count():
    d = _Driver([{"p": {"id": "1", "name": "Zed Alpha"}, "paper_count": 2}, {"p": {"id": "2", "name": "Amy Zulu"}, "paper_count": 0}])
    rows = q.list_people(d)
    assert [r["name"] for r in rows] == ["Zed Alpha", "Amy Zulu"]
    assert rows[0]["paper_count"] == 2


@pytest.mark.asyncio
async def test_endpoint_rows_stay_light(monkeypatch):
    rows = q._list_rows(_rows())
    # Even if the query layer leaked a heavy property, the response model must drop it.
    rows[0]["cv"] = "x" * 100_000
    rows[0]["bio"] = "y" * 5_000
    from routers import people as router
    monkeypatch.setattr(router, "list_people", lambda driver, tag=None: rows)
    monkeypatch.setattr(router, "get_driver", lambda: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/people")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == len(rows)
    assert all(set(row) <= ALLOWED for row in body)
    biggest = max(len(json.dumps(row)) for row in body)
    assert biggest <= MAX_ROW_BYTES, f"a /people row is {biggest} bytes"
    assert len(r.content) <= len(rows) * MAX_ROW_BYTES
