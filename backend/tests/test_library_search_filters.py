"""Library search filters, sorts, the filter-only listing and the router's validation.

Pure functions and a scripted fake driver (no Neo4j); test_library_search_demo_filters.py runs
the same filters against the demo library on a real database.
"""
import re

import pytest
from httpx import ASGITransport, AsyncClient

from db.queries import search as search_queries
from db.queries.search import _ORDER, search_papers
from main import app
from services.library_search.engine import (
    _PAPER_FIELDS,
    Filters,
    display_fields,
    filter_clause,
    normalize_added,
)
from services.library_search.ranking import SORTS, Candidate, sort_candidates


@pytest.fixture(autouse=True)
def _admin(monkeypatch):
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "niklas")


# ── date bounds ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, before, expected", [
    ("2026-11-12", False, "2026-11-12T00:00:00"),
    ("2026-11-12", True, "2026-11-13T00:00:00"),          # a date upper bound includes that day
    ("2026-12-31", True, "2027-01-01T00:00:00"),
    ("2026-11-12T00:00:00.000Z", False, "2026-11-12T00:00:00"),
    ("2026-11-12T10:30:15+00:00", True, "2026-11-12T10:30:15"),   # a datetime stays exclusive as given
    ("2026-11-12T10:30:15.987654+00:00", False, "2026-11-12T10:30:15"),
    ("2026-11-12T10:30:15", False, "2026-11-12T10:30:15"),         # no zone: UTC, like the stored values
    ("2026-11-12T01:30:00+02:00", False, "2026-11-11T23:30:00"),
    ("  2026-11-12 ", False, "2026-11-12T00:00:00"),
])
def test_normalize_added(value, before, expected):
    assert normalize_added(value, before=before) == expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_normalize_added_empty_is_no_bound(value):
    assert normalize_added(value) is None


@pytest.mark.parametrize("value", ["yesterday", "2026-13-01", "2026-11-31", "12.11.2026", "2026-11-12T25:00:00", "2026"])
def test_normalize_added_rejects_garbage(value):
    with pytest.raises(ValueError, match="not a date"):
        normalize_added(value)


def test_normalized_bounds_compare_like_the_stored_strings():
    stored = "2026-11-11T19:41:47.120895+00:00"
    assert stored >= normalize_added("2026-11-11")
    assert stored < normalize_added("2026-11-11", before=True)       # same day: included
    assert not stored < normalize_added("2026-11-10", before=True)   # day before: excluded
    assert not stored >= normalize_added("2026-11-12")


# ── filter_clause ─────────────────────────────────────────────────────────────

NEW_PARAMS = {"added_after", "added_before", "has_pdf", "has_text", "has_note", "has_hl", "doctype", "rating_min"}


def test_unfiltered_clause_has_none_of_the_new_predicates():
    where, params = filter_clause(Filters())
    assert not NEW_PARAMS & set(params)
    for needle in ("created_at", "drive_file_id", "raw_text", "HAS_NOTE", "HAS_ANNOTATION", "document_type", "rating"):
        assert needle not in where


def test_added_filters():
    where, params = filter_clause(Filters(added_after="2026-11-01", added_before="2026-11-12"))
    assert "p.created_at >= $added_after" in where and "p.created_at < $added_before" in where
    assert params["added_after"] == "2026-11-01T00:00:00"
    assert params["added_before"] == "2026-11-13T00:00:00"


def test_invalid_date_raises_value_error():
    with pytest.raises(ValueError):
        filter_clause(Filters(added_after="soon"))


def test_has_filters_are_boolean_comparisons_and_support_false():
    where, params = filter_clause(Filters(has_pdf=True, has_text=False, has_note=True, has_highlights=False))
    assert params["has_pdf"] is True and params["has_text"] is False
    assert params["has_note"] is True and params["has_hl"] is False
    assert "$has_pdf = (p.drive_file_id IS NOT NULL AND p.drive_file_id <> '')" in where
    # IS NOT NULL comes first so the string is only read for papers that have text
    assert "$has_text = (p.raw_text IS NOT NULL AND p.raw_text <> '')" in where
    assert "(p)-[:HAS_NOTE]->(_n:Note)" in where and "trim(coalesce(_n.content, '')) <> ''" in where
    assert "(p)-[:HAS_ANNOTATION]->()" in where


def test_unread_matches_papers_without_a_status():
    where, params = filter_clause(Filters(reading_status="unread"))
    assert "toLower(coalesce(p.reading_status, 'unread')) = toLower($status)" in where
    assert params["status"] == "unread"


def test_bookmarked_false_matches_papers_without_the_property():
    where, _ = filter_clause(Filters(bookmarked=False))
    assert "coalesce(p.bookmarked, false) = $bookmarked" in where


def test_document_type_paper_matches_papers_without_a_type():
    where, params = filter_clause(Filters(document_type="Paper"))
    assert "toLower(coalesce(p.document_type, 'paper')) = toLower($doctype)" in where
    assert params["doctype"] == "Paper"


def test_rating_min():
    where, params = filter_clause(Filters(rating_min=4))
    assert "p.rating >= $rating_min" in where and params["rating_min"] == 4


def test_existing_filters_keep_their_null_guarded_shape():
    where, params = filter_clause(Filters())
    for p in ("tag", "topic", "pid", "project", "person", "venue", "year_min", "year_max", "status", "bookmarked"):
        assert f"${p} IS NULL OR" in where and p in params


# ── sorts ─────────────────────────────────────────────────────────────────────

def _c(pid, **kw):
    return Candidate(id=pid, title=pid, **kw)


def test_new_sorts_are_registered():
    assert {"rating_desc", "citations_desc", "updated_desc"} <= SORTS
    assert {"rating_desc", "citations_desc", "updated_desc"} <= set(_ORDER)
    assert (SORTS - {"relevance"}) == set(_ORDER)


def test_sort_rating_desc_puts_unrated_last_and_breaks_ties_newest_first():
    cs = [_c("none", created_at="2026-03-01"), _c("r3_old", rating=3, created_at="2026-01-01"),
          _c("r5", rating=5, created_at="2026-02-01"), _c("r3_new", rating=3, created_at="2026-02-01")]
    assert [c.id for c in sort_candidates(cs, "rating_desc")] == ["r5", "r3_new", "r3_old", "none"]


def test_sort_citations_desc_nulls_last_and_keeps_relevance_order_for_ties():
    cs = [_c("a", citation_count=None), _c("b", citation_count=10), _c("c", citation_count=None),
          _c("d", citation_count=500), _c("e", citation_count=10)]
    assert [c.id for c in sort_candidates(cs, "citations_desc")] == ["d", "b", "e", "a", "c"]
    assert [c.id for c in cs] == ["a", "b", "c", "d", "e"]   # input untouched


def test_sort_updated_desc_falls_back_to_created_at():
    cs = [_c("old", created_at="2026-01-01", updated_at="2026-05-01T00:00:00"),
          _c("never_updated", created_at="2026-09-01"),
          _c("recent", created_at="2026-01-01", updated_at="2026-10-01T00:00:00+00:00")]
    assert [c.id for c in sort_candidates(cs, "updated_desc")] == ["recent", "never_updated", "old"]


def test_unknown_sort_keeps_the_order():
    cs = [_c("a"), _c("b")]
    assert sort_candidates(cs, "nonsense") is cs


def test_listing_order_clauses():
    assert _ORDER["rating_desc"].startswith("p.rating IS NULL, p.rating DESC")
    assert _ORDER["citations_desc"].startswith("p.citation_count IS NULL, p.citation_count DESC")
    assert _ORDER["updated_desc"].startswith("coalesce(p.updated_at, p.created_at) DESC")
    assert _ORDER["year_desc"].startswith("p.year IS NULL, p.year DESC")   # no year last, like the ranked sort


# ── the filter-only listing ───────────────────────────────────────────────────

class _ListingSession:
    def __init__(self, driver):
        self.d = driver

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.d.queries.append((query, params))
        if "count(p) AS c" in query:
            return [{"c": self.d.total}]
        if "RETURN p.id AS id" in query and "AS authors" not in query:
            return [{"id": pid} for pid in self.d.page]
        if "AS authors" in query:
            # Neo4j gives rows in any order; ask for the ids in reverse to prove the order is restored
            return [{"id": pid, "p": {"id": pid, "title": f"T {pid}", "year": None, "created_at": "2026-01-01"},
                     "added_by": "niklas", "added_by_color": "#fff", "authors": ["A", "B"], "text_chars": 12,
                     "has_note": True, "highlight_count": 2, "ref": pid == "r1", "projects": ["P"]}
                    for pid in reversed(params["ids"])]
        raise AssertionError(query)


class _ListingDriver:
    def __init__(self, page, total):
        self.page, self.total, self.queries = page, total, []

    def session(self):
        return _ListingSession(self)


def test_listing_returns_display_rows_in_page_order():
    driver = _ListingDriver(["a", "r1", "c"], total=57)
    res = search_papers(driver, include_references=False, limit=3, skip=6, sort="rating_desc")
    assert res["total"] == 57 and res["cached"] is False
    assert [r["id"] for r in res["results"]] == ["a", "r1", "c"]
    first = res["results"][0]
    assert first["matched_in"] == "filter" and first["score"] == 0.0
    assert first["authors"] == ["A", "B"] and first["added_by"] == "niklas" and first["added_by_color"] == "#fff"
    assert first["text_chars"] == 12 and first["has_note"] is True and first["highlight_count"] == 2
    assert first["projects"] == ["P"] and first["is_reference"] is False
    assert res["results"][1]["is_reference"] is True
    assert "year" not in first   # null properties are dropped, like the ranked rows
    page_q = next(q for q, p in driver.queries if "RETURN p.id AS id" in q and "AS authors" not in q)
    assert "ORDER BY p.rating IS NULL, p.rating DESC" in page_q and "SKIP $skip LIMIT $limit" in page_q


def test_listing_never_reads_raw_text_into_the_rows():
    assert "raw_text" not in _PAPER_FIELDS and "embedding" not in _PAPER_FIELDS
    driver = _ListingDriver(["a"], total=1)
    search_papers(driver, limit=1)
    for q, _ in driver.queries:
        assert not re.search(r"RETURN\s+p\s*[,\n]", q), "a bare RETURN p would ship every property"
    row = display_fields({"p": {"id": "x", "raw_text": "..."}, "authors": [], "added_by": None, "added_by_color": None,
                          "text_chars": 3, "has_note": False, "highlight_count": 0, "projects": []})
    assert row["text_chars"] == 3
    # the projection in the display query is an explicit property list
    display_q = next(q for q, _ in driver.queries if "AS authors" in q)
    projection = re.search(r"p \{[^}]*\}", display_q).group(0)
    assert projection.startswith("p {.id, .title") and "raw_text" not in projection


def test_listing_passes_the_filters_and_clamps_the_page():
    driver = _ListingDriver([], total=0)
    res = search_papers(driver, added_after="2026-11-01", has_pdf=True, reading_status="unread",
                        skip=-5, limit=99999, sort="no_such_sort")
    assert res == {"results": [], "total": 0, "cached": False}
    q, params = next((q, p) for q, p in driver.queries if "SKIP $skip" in q)
    assert params["skip"] == 0 and params["limit"] == 2000
    assert params["added_after"] == "2026-11-01T00:00:00" and params["has_pdf"] is True
    assert "ORDER BY p.created_at DESC" in q   # unknown sort -> newest first


def test_listing_total_is_never_below_the_rows_returned():
    driver = _ListingDriver(["a", "b"], total=0)
    assert search_papers(driver, limit=2)["total"] == 2


# ── the router ────────────────────────────────────────────────────────────────

def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("param", ["added_after", "added_before"])
async def test_router_rejects_invalid_dates_with_422(param):
    async with _client() as c:
        r = await c.get("/search", params={param: "last week"})
    assert r.status_code == 422
    assert param in r.json()["detail"] and "YYYY-MM-DD" in r.json()["detail"]


@pytest.mark.parametrize("params", [{"rating_min": 0}, {"rating_min": 6}, {"has_pdf": "maybe"}, {"limit": 5000}])
async def test_router_rejects_out_of_range_values(params):
    async with _client() as c:
        assert (await c.get("/search", params=params)).status_code == 422


async def test_router_passes_every_filter_through(monkeypatch):
    seen = {}

    def fake(driver, **kw):
        seen.update(kw)
        return {"results": [], "total": 0}

    monkeypatch.setattr("routers.search.search_papers", fake)
    monkeypatch.setattr("routers.search.get_driver", lambda: object())
    async with _client() as c:
        r = await c.get("/search", params={
            "added_after": "2026-11-01", "added_before": "2026-11-12T00:00:00.000Z", "has_pdf": "1", "has_text": "false",
            "has_note": "true", "has_highlights": "0", "document_type": " Book ", "rating_min": 3,
            "sort": "rating_desc", "limit": 24, "skip": 48, "snippets": 0, "include_references": "false",
            "year_min": 2020, "reading_status": "unread"})
    assert r.status_code == 200
    assert seen["added_after"] == "2026-11-01" and seen["added_before"] == "2026-11-12T00:00:00.000Z"
    assert seen["has_pdf"] is True and seen["has_text"] is False and seen["has_note"] is True
    assert seen["has_highlights"] is False and seen["document_type"] == "book" and seen["rating_min"] == 3
    assert seen["sort"] == "rating_desc" and seen["limit"] == 24 and seen["skip"] == 48
    assert seen["max_snippets"] == 0 and seen["include_references"] is False
    assert seen["year_min"] == 2020 and seen["reading_status"] == "unread"
    assert seen["cache"] is True


async def test_router_omitted_filters_stay_none(monkeypatch):
    seen = {}
    monkeypatch.setattr("routers.search.search_papers", lambda driver, **kw: seen.update(kw) or {"results": [], "total": 0})
    monkeypatch.setattr("routers.search.get_driver", lambda: object())
    async with _client() as c:
        assert (await c.get("/search")).status_code == 200
    for k in ("added_after", "added_before", "has_pdf", "has_text", "has_note", "has_highlights",
              "document_type", "rating_min"):
        assert seen[k] is None
    assert seen["sort"] == "date_desc"   # no query, default sort -> newest first


def test_module_exports():
    assert search_queries.search_papers is search_papers
