"""library_add (services/library_add.py, MCP tool in tools/library_tools.py).

The first block is pure; the second hits Neo4j like test_library_lookup.py and removes
what it creates.
"""
import json

import pytest

from db.connection import get_driver
from db.queries.papers import create_paper, delete_paper
from services.auth import reset_request_user, set_request_user
from services.library_add import _doi, add, batch_key, load_items

# ── pure ──────────────────────────────────────────────────────────────────────


def test_doi_from_arxiv_and_batch_key():
    assert _doi({"arxiv": "2601.13548"}) == "10.48550/arXiv.2601.13548"
    assert _doi({"arxiv": "arXiv:2601.13548", "doi": "10.1/x"}) == "10.1/x"
    assert _doi({"title": "t"}) == ""
    assert batch_key({"arxiv": "2601.13548"}) == batch_key({"doi": "arXiv:2601.13548v2"})
    assert batch_key({"title": "A <i>Title</i>!"}) == batch_key({"title": "a title"}) == "t:atitle"
    assert batch_key({"title": ""}) is None


def test_load_items_shapes_and_errors(tmp_path):
    f = tmp_path / "papers.json"
    f.write_text(json.dumps({"papers": [{"title": "x"}], "other": 1}))
    entries, wrapper, err = load_items(None, str(f))
    assert entries == [{"title": "x"}] and wrapper["other"] == 1 and err is None
    assert load_items(None, "papers.json")[2].startswith("path must be absolute")
    assert "cannot read" in load_items(None, str(tmp_path / "nope.json"))[2]
    assert load_items([{"title": "y"}], "")[0] == [{"title": "y"}]


def test_rejects_untitled_and_oversized():
    d = get_driver()
    assert "without a title" in add(d, [{"title": "ok"}, {"doi": "10.1/x"}])["error"]
    assert "at most" in add(d, [{"title": str(i)} for i in range(201)])["error"]
    assert "give `papers`" in add(d, [])["error"]


# ── against Neo4j ─────────────────────────────────────────────────────────────

PID = "library-add-test-project"


@pytest.fixture
def setup():
    token = set_request_user("niklas")
    d = get_driver()
    old = create_paper(d, {"title": "Library add test: an existing paper on singular models",
                           "doi": "10.5555/LIBADD-TEST.1", "year": 2020})
    with d.session() as s:
        s.run("MERGE (pr:Project {id: $id}) SET pr.name = 'LibraryAddTestProject'", id=PID)
    made: list[str] = []
    yield d, old, made
    for pid in [old["id"], *made]:
        delete_paper(d, pid)
    with d.session() as s:
        s.run("MATCH (pr:Project {id: $id}) DETACH DELETE pr", id=PID)
        s.run("MATCH (p:Person {name: 'Libadd Testperson'}) WHERE NOT (p)--() DELETE p")
    reset_request_user(token)


def _entries():
    return [
        {"title": "Library add test: an existing paper on singular models", "doi": "https://doi.org/10.5555/libadd-test.1"},
        {"title": "Library add test: a new arXiv paper", "arxiv": "2699.99991", "year": "2026",
         "authors": ["Libadd Testperson"], "venue": "arXiv"},
        {"title": "Library add test: a new arXiv paper (cited again)", "arxiv": "arXiv:2699.99991v2"},
        {"title": "Library add test: a book without identifiers", "authors": "Someone, Else",
         "document_type": "book"},
    ]


def test_dry_run_writes_nothing(setup, tmp_path):
    d, old, _ = setup
    f = tmp_path / "papers.json"
    f.write_text(json.dumps(_entries()))
    res = add(d, path=str(f), project="librarYaddTestProject", dry_run=True)
    assert (res["present"], res["would_add"], res["same_in_batch"], res["would_link"]) == (1, 2, 1, 1)
    assert res["written"] is False and json.loads(f.read_text()) == _entries()
    with d.session() as s:
        n = s.run("MATCH (p:Paper) WHERE p.title STARTS WITH 'Library add test: a ' RETURN count(p) AS n").single()["n"]
    assert n == 0


def test_add_links_and_writes_back(setup, tmp_path):
    d, old, made = setup
    f = tmp_path / "papers.json"
    f.write_text(json.dumps(_entries()))
    res = add(d, path=str(f), project=PID, url_base="https://pm.example")
    made += [r["id"] for r in res["items"] if r["status"] == "added" and "same_as" not in r]
    assert (res["present"], res["added"], res["same_in_batch"], res["linked"]) == (1, 2, 1, 3)
    i0, i1, i2, i3 = res["items"]
    assert i0["status"] == "present" and i0["kind"] == "doi" and i0["id"] == old["id"]
    assert i1["status"] == "added" and i2["same_as"] == 1 and i2["id"] == i1["id"]
    assert i3["status"] == "added" and "1 entries give `authors` as a string" in res["note"]

    back = json.loads(f.read_text())
    assert back[0]["paperId"] == old["id"] and back[0]["status"] == "present"
    assert back[1]["status"] == "added" and back[1]["url"] == f"https://pm.example/paper/{i1['id']}"
    assert back[2]["paperId"] == i1["id"] and back[2]["status"] == "added"

    with d.session() as s:
        p = s.run("""MATCH (p:Paper {id: $id}) RETURN p.doi AS doi, p.year AS year, p.venue AS venue,
                     [(p)-[:AUTHORED_BY]->(a) | a.name] AS authors,
                     [(p)-[:IN_PROJECT]->(pr) | pr.id] AS projects""", id=i1["id"]).single()
        assert p["year"] == 2026 and p["venue"] == "arXiv" and p["authors"] == ["Libadd Testperson"]
        assert p["projects"] == [PID] and "2699.99991" in p["doi"]
        n = s.run("MATCH (:Paper)-[r:IN_PROJECT]->(:Project {id: $id}) RETURN count(r) AS n", id=PID).single()["n"]
        assert n == 3

    # a second run finds everything by the written paperIds and links nothing new
    again = add(d, path=str(f), project=PID)
    assert (again["present"], again["added"], again["linked"]) == (3, 0, 0)
    assert {r["kind"] for r in again["items"] if "same_as" not in r} == {"id"}


def test_unknown_project_is_an_error_before_any_write(setup):
    d, _, _ = setup
    res = add(d, [{"title": "Library add test: should never be created"}], project="no-such-project-xyz")
    assert res["error"].startswith("no project named")
    with d.session() as s:
        assert s.run("MATCH (p:Paper {title: 'Library add test: should never be created'}) "
                     "RETURN count(p) AS n").single()["n"] == 0
