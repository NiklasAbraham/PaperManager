"""The 2026-11 search filters and sorts against the demo library (real Neo4j).

The expected sets are worked out from tests/fixtures/demo_library.json; the one test that
needs ratings, PDFs and full text writes them with Cypher into its own copy of the library.
"""
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient

from db.connection import get_driver
from db.queries.visibility import ADMIN_USERNAME
from main import app

# The visibility admin sees every paper; demo_alice is not in the "Sequence models reading
# group" project, so "transformer" would be hidden from her and every count below be one short.
ADMIN = ADMIN_USERNAME


async def _get(auth_headers, **params):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers=auth_headers(ADMIN)) as c:
        r = await c.get("/search", params={"include_references": "false", "limit": 50, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _keys(ids, res):
    by_id = {v: k for k, v in ids["papers"].items()}
    return [by_id[r["id"]] for r in res["results"]]


async def test_unread_includes_papers_without_a_status(demo_library, auth_headers):
    driver = get_driver()
    with driver.session() as s:   # one demo paper loses its status, as most real papers have none
        s.run("MATCH (p:Paper {id: $id}) REMOVE p.reading_status", id=demo_library["papers"]["transformer"]).consume()
    try:
        res = await _get(auth_headers, reading_status="unread")
        assert set(_keys(demo_library, res)) == {"edm", "flow_matching", "esm2", "gnn_survey", "transformer"}
        ranked = await _get(auth_headers, q="attention", reading_status="unread")
        assert _keys(demo_library, ranked) == ["transformer"]
        assert set(_keys(demo_library, await _get(auth_headers, reading_status="READING"))) == {"score_sde", "alphafold3"}
    finally:
        with driver.session() as s:
            s.run("MATCH (p:Paper {id: $id}) SET p.reading_status = 'read'", id=demo_library["papers"]["transformer"]).consume()


async def test_document_type_paper_matches_papers_without_a_type(demo_library, auth_headers):
    papers = await _get(auth_headers, document_type="paper")
    assert "gnn_survey" not in _keys(demo_library, papers) and papers["total"] == 9
    assert _keys(demo_library, await _get(auth_headers, document_type="review")) == ["gnn_survey"]
    assert (await _get(auth_headers, document_type="book"))["total"] == 0


async def test_bookmarked_false_matches_papers_without_the_property(demo_library, auth_headers):
    res = await _get(auth_headers, bookmarked="false")
    assert set(_keys(demo_library, res)) == {"score_sde", "edm", "alphafold2", "alphafold3", "esm2", "gnn_survey"}


async def test_added_window(demo_library, auth_headers):
    now = datetime.now(timezone.utc)
    today, tomorrow, yesterday = (d.strftime("%Y-%m-%d") for d in (now, now + timedelta(days=1), now - timedelta(days=1)))
    assert (await _get(auth_headers, added_after=yesterday))["total"] == 10
    assert (await _get(auth_headers, added_after=tomorrow))["total"] == 0
    assert (await _get(auth_headers, added_before=today))["total"] == 10        # the whole of today is included
    assert (await _get(auth_headers, added_before=yesterday))["total"] == 0
    assert (await _get(auth_headers, added_after=today, added_before=today))["total"] == 10
    assert (await _get(auth_headers, added_after=(now - timedelta(minutes=30)).isoformat()))["total"] == 10
    assert (await _get(auth_headers, added_after=(now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")))["total"] == 0
    ranked = await _get(auth_headers, q="diffusion", added_after=tomorrow)
    assert ranked["total"] == 0


async def test_has_note_and_highlights(demo_library, auth_headers):
    with_notes = await _get(auth_headers, has_note="true")
    assert set(_keys(demo_library, with_notes)) == {"ddpm", "rfdiffusion", "alphafold3"}
    assert all(r["has_note"] for r in with_notes["results"])
    without = await _get(auth_headers, has_note="false")
    assert without["total"] == 7 and not any(r["has_note"] for r in without["results"])
    assert (await _get(auth_headers, has_highlights="true"))["total"] == 0
    ranked = await _get(auth_headers, q="diffusion", has_note="true")
    assert set(_keys(demo_library, ranked)) <= {"ddpm", "rfdiffusion", "alphafold3"} and ranked["total"] >= 1


async def test_listing_rows_carry_what_the_cards_show(demo_library, auth_headers):
    res = await _get(auth_headers, sort="date_desc", limit=4, snippets=0)
    assert res["total"] == 10 and len(res["results"]) == 4 and res["cached"] is False
    row = next(r for r in (await _get(auth_headers, topic="Transformers"))["results"])
    assert row["matched_in"] == "filter" and row["score"] == 0
    # No author order is stored on AUTHORED_BY, so only membership is checked.
    assert "Ashish Vaswani" in row["authors"] and len(row["authors"]) <= 12
    assert row["added_by"] == "demo_bob" and row["added_by_color"] == "#d9822b"
    assert row["is_reference"] is False and row["highlight_count"] == 0 and row["has_note"] is False
    assert row["text_chars"] == 0 and isinstance(row["projects"], list)
    assert "raw_text" not in row and "embedding" not in row
    refs = await _get(auth_headers, include_references="true", q=None, limit=50)
    stub = next(r for r in refs["results"] if r.get("title") == "Denoising Diffusion Probabilistic Models" and r["is_reference"])
    assert stub["is_reference"] is True


async def test_pdf_text_rating_citation_and_update_sorts(demo_library_fresh, auth_headers):
    ids = demo_library_fresh["papers"]
    driver = get_driver()
    with driver.session() as s:
        s.run("""MATCH (a:Paper {id: $ddpm}) SET a.drive_file_id = 'drive-1', a.raw_text = 'denoising diffusion full text', a.rating = 5,
                       a.citation_count = 900, a.updated_at = '2030-01-01T00:00:00'
                 WITH a MATCH (b:Paper {id: $edm}) SET b.drive_file_id = 'drive-2', b.raw_text = '', b.rating = 3, b.citation_count = 12
                 WITH a MATCH (c:Paper {id: $fm}) SET c.rating = 4, c.citation_count = 40, c.drive_file_id = ''""",
              ddpm=ids["ddpm"], edm=ids["edm"], fm=ids["flow_matching"]).consume()
    pdf = await _get(auth_headers, has_pdf="true")
    assert set(_keys(demo_library_fresh, pdf)) == {"ddpm", "edm"}
    assert (await _get(auth_headers, has_pdf="false"))["total"] == 8          # '' and missing both mean no PDF
    assert _keys(demo_library_fresh, await _get(auth_headers, has_text="true")) == ["ddpm"]   # '' is no text
    assert (await _get(auth_headers, has_text="false"))["total"] == 9
    assert set(_keys(demo_library_fresh, await _get(auth_headers, rating_min=4))) == {"ddpm", "flow_matching"}
    assert set(_keys(demo_library_fresh, await _get(auth_headers, rating_min=3))) == {"ddpm", "flow_matching", "edm"}
    both = await _get(auth_headers, has_pdf="true", rating_min=4)
    assert _keys(demo_library_fresh, both) == ["ddpm"]

    for q in (None, "diffusion"):
        extra = {"q": q} if q else {}
        rating = _keys(demo_library_fresh, await _get(auth_headers, sort="rating_desc", **extra))
        assert [k for k in rating if k in ("ddpm", "flow_matching", "edm")] == ["ddpm", "flow_matching", "edm"]
        assert rating[:len([k for k in rating if k in ("ddpm", "flow_matching", "edm")])] == [
            k for k in rating if k in ("ddpm", "flow_matching", "edm")]   # rated papers first, unrated last
        cites = _keys(demo_library_fresh, await _get(auth_headers, sort="citations_desc", **extra))
        assert [k for k in cites if k in ("ddpm", "flow_matching", "edm")] == ["ddpm", "flow_matching", "edm"]
        upd = _keys(demo_library_fresh, await _get(auth_headers, sort="updated_desc", **extra))
        assert upd[0] == "ddpm"
    listing = await _get(auth_headers, sort="rating_desc", limit=3)
    assert _keys(demo_library_fresh, listing) == ["ddpm", "flow_matching", "edm"]
    # the same filters through the ranked path
    ranked = await _get(auth_headers, q="denoising", has_text="true")
    assert _keys(demo_library_fresh, ranked) == ["ddpm"]
    page = await _get(auth_headers, q="diffusion", sort="citations_desc", limit=1)
    assert _keys(demo_library_fresh, page) == ["ddpm"]


async def test_invalid_date_is_a_422_with_a_message(demo_library, auth_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=auth_headers(ADMIN)) as c:
        r = await c.get("/search", params={"added_before": "13/11/2026"})
    assert r.status_code == 422 and "added_before" in r.json()["detail"]
