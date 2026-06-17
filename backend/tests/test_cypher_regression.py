"""Cypher regression tests — run the real DB queries against a live Neo4j.

These guard against Cypher *syntax* errors and Neo4j-version incompatibilities
that unit tests with a mocked driver can never catch. The bug that motivated
this file: `update_paper` placed an `OPTIONAL MATCH` directly after `SET`
without the `WITH` clause that Neo4j 5 requires, so every paper PATCH
(reading_status, document_type, bookmark, rating) returned HTTP 500.

They talk to the query layer directly (no FastAPI app, no docling) so they stay
fast and have light dependencies — only `neo4j` + config. They are marked
`integration` because they need a running Neo4j; CI provides one as a service
container. Locally they skip cleanly when Neo4j is unreachable.
"""
import uuid

import pytest

from db.connection import get_driver
from db.queries.papers import create_paper, update_paper, delete_paper
from db.queries.people import get_or_create_person, link_involves, get_involves_for_paper

pytestmark = pytest.mark.integration


@pytest.fixture
def driver():
    try:
        drv = get_driver()
        drv.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 — any connection problem means "skip"
        pytest.skip(f"Neo4j not reachable: {exc}")
    return drv


@pytest.fixture
def paper(driver):
    p = create_paper(driver, {"title": "Cypher Regression Paper"})
    yield p
    delete_paper(driver, p["id"])


# Every field the PATCH /papers/{id} endpoint can set must round-trip through
# update_paper without raising. A Cypher syntax error fails at the first one.
@pytest.mark.parametrize(
    "field, value",
    [
        ("reading_status", "read"),
        ("reading_status", "reading"),
        ("reading_status", "unread"),
        ("document_type", "paper"),
        ("document_type", "book"),
        ("document_type", "lecture_deck"),
        ("bookmarked", True),
        ("rating", 4),
        ("title", "Renamed"),
        ("metadata_source", "manual"),
    ],
)
def test_update_paper_field_round_trips(driver, paper, field, value):
    updated = update_paper(driver, paper["id"], {field: value})
    assert updated is not None, "update_paper returned None for an existing paper"
    assert updated[field] == value
    # The added-by attribution columns must always be present in the result shape.
    assert "added_by" in updated
    assert "added_by_color" in updated


def test_update_paper_missing_returns_none(driver):
    assert update_paper(driver, f"missing-{uuid.uuid4()}", {"reading_status": "read"}) is None


# Regression for the `01N42` "missing property name" warning: reading an
# INVOLVES relationship that was created without `years_known` must not warn or
# error — get_involves_for_paper reads it via properties() to stay quiet.
def test_get_involves_without_years_known(driver, paper):
    person = get_or_create_person(driver, f"Test Person {uuid.uuid4()}")
    try:
        link_involves(driver, paper["id"], person["id"], role="discussed")  # no years_known
        rows = get_involves_for_paper(driver, paper["id"])
        assert any(r["id"] == person["id"] for r in rows)
        row = next(r for r in rows if r["id"] == person["id"])
        assert row["role"] == "discussed"
        assert row["years_known"] is None
    finally:
        with driver.session() as session:
            session.run("MATCH (p:Person {id: $id}) DETACH DELETE p", id=person["id"])
