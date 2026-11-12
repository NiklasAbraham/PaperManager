"""The ranked-result cache of GET /search (services/library_search/cache.py) and its
invalidation by writes. Scripted driver, no Neo4j."""
import re

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from services.library_search import cache
from services.library_search.engine import Filters, search
from tests.test_library_search import _Driver, _row


@pytest.fixture(autouse=True)
def _cache_on(monkeypatch):
    """conftest turns the cache off for the whole suite; these tests turn it on."""
    monkeypatch.setenv("LIBRARY_SEARCH_CACHE", "1")
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "niklas")
    cache.clear()
    yield
    cache.clear()


class _SortFieldsDriver(_Driver):
    """The scripted driver, plus the query that loads the fields a sort needs."""

    def session(self):
        session = super().session()
        run = session.run

        def run_with_sort_fields(query, **params):
            if "p.year AS year" in query and "p.id IN $ids" in query:
                self.queries.append((query, params))
                self.sort_field_loads = getattr(self, "sort_field_loads", 0) + 1
                return [{"id": r["id"], "year": 2000 + int(r["id"][1:]), "created_at": r["created_at"],
                         "rating": r["rating"], "citation_count": r["citation_count"],
                         "updated_at": None} for r in self.rows["paper"] if r["id"] in params["ids"]]
            return run(query, **params)

        session.run = run_with_sort_fields
        return session


def _driver(n=5, **kw):
    return _SortFieldsDriver({"paper": [_row(f"p{i}", f"Diffusion {i}", 10 - i, abstract=None, summary=None,
                                             rating=i % 3 or None, citation_count=i * 7)
                                        for i in range(n)]}, **kw)


def _source_runs(driver):
    return sum(1 for q, _ in driver.queries if re.search(r"/\*search:\w+\*/", q))


def test_second_identical_request_is_served_from_the_cache():
    driver = _driver()
    first = search(driver, "diffusion", Filters(), cache=True)
    runs = _source_runs(driver)
    assert runs == 7 and first["cached"] is False
    second = search(driver, "diffusion", Filters(), cache=True)
    assert _source_runs(driver) == runs                      # no retrieval query ran again
    assert second["cached"] is True
    assert [r["id"] for r in second["results"]] == [r["id"] for r in first["results"]]
    assert second["total"] == first["total"]


def test_paging_and_sorting_reuse_the_ranked_list():
    driver = _driver(n=6)
    search(driver, "diffusion", Filters(), limit=2, cache=True)
    runs = _source_runs(driver)
    page2 = search(driver, "diffusion", Filters(), skip=2, limit=2, cache=True)
    by_rating = search(driver, "diffusion", Filters(), sort="rating_desc", cache=True)
    by_cites = search(driver, "diffusion", Filters(), sort="citations_desc", cache=True)
    assert _source_runs(driver) == runs
    assert page2["cached"] and by_rating["cached"] and by_cites["cached"]
    assert [r["id"] for r in page2["results"]] == ["p2", "p3"]
    assert by_cites["results"][0]["id"] == "p5"              # 35 citations: most
    # ratings 2, 1 and none; ties keep the relevance order
    assert [r["id"] for r in by_rating["results"]] == ["p2", "p5", "p1", "p4", "p0", "p3"]
    assert driver.sort_field_loads == 1      # loaded once for the ranked list, then kept on the candidates


def test_sort_fields_are_only_loaded_for_sorts_that_need_them():
    driver = _driver()
    search(driver, "diffusion", Filters())
    search(driver, "diffusion", Filters(), sort="title_asc")
    assert getattr(driver, "sort_field_loads", 0) == 0
    by_year = search(driver, "diffusion", Filters(), sort="year_desc")
    assert driver.sort_field_loads == 1
    assert [r["id"] for r in by_year["results"]] == ["p4", "p3", "p2", "p1", "p0"]


def test_key_covers_query_filters_mode_and_user(monkeypatch):
    driver = _driver()
    search(driver, "diffusion", Filters(), cache=True)
    runs = _source_runs(driver)
    for q, f, mode in [("diffusion models", Filters(), "lexical"),
                       ("diffusion", Filters(year_min=2020), "lexical"),
                       ("diffusion", Filters(include_references=False), "lexical"),
                       ("diffusion", Filters(has_pdf=True), "lexical"),
                       ("diffusion", Filters(added_after="2026-01-01"), "lexical"),
                       ("diffusion", Filters(), "semantic")]:
        res = search(driver, q, f, mode=mode, cache=True)
        assert res["cached"] is False, (q, f, mode)
        assert _source_runs(driver) > runs
        runs = _source_runs(driver)
    # another user must never see an answer computed under another user's visibility
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "carol")
    assert search(driver, "diffusion", Filters(), cache=True)["cached"] is False
    # surrounding whitespace is not a different query
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "niklas")
    assert search(driver, "  diffusion ", Filters(), cache=True)["cached"] is True


def test_cache_is_off_unless_asked_and_by_the_env_switch(monkeypatch):
    driver = _driver()
    search(driver, "diffusion", Filters())                        # cache=False (MCP, benchmarks)
    assert search(driver, "diffusion", Filters())["cached"] is False
    assert cache.size() == 0
    monkeypatch.setenv("LIBRARY_SEARCH_CACHE", "0")
    search(driver, "diffusion", Filters(), cache=True)
    assert search(driver, "diffusion", Filters(), cache=True)["cached"] is False
    assert cache.size() == 0


def test_a_write_invalidates():
    driver = _driver()
    search(driver, "diffusion", Filters(), cache=True)
    assert search(driver, "diffusion", Filters(), cache=True)["cached"] is True
    cache.bump()
    assert cache.size() == 0
    assert search(driver, "diffusion", Filters(), cache=True)["cached"] is False


def test_a_search_that_raced_with_a_write_is_not_kept():
    key = ("niklas", "q", "lexical", ())
    gen = cache.generation()
    cache.bump()                       # the write lands while the search is still running
    cache.put(key, "stale", gen)
    assert cache.get(key) is None
    cache.put(key, "fresh", cache.generation())
    assert cache.get(key) == "fresh"


def test_entries_expire_after_the_ttl(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cache, "_now", lambda: now[0])
    cache.put(("k",), "v", cache.generation())
    now[0] += cache.TTL - 1
    assert cache.get(("k",)) == "v"
    now[0] += 2
    assert cache.get(("k",)) is None and cache.size() == 0


def test_least_recently_used_entry_goes_first(monkeypatch):
    monkeypatch.setattr(cache, "MAX_ENTRIES", 3)
    g = cache.generation()
    for k in "abc":
        cache.put((k,), k, g)
    assert cache.get(("a",)) == "a"            # a is now the most recent
    cache.put(("d",), "d", g)                  # evicts b
    assert cache.get(("b",)) is None
    assert [cache.get((k,)) for k in "acd"] == ["a", "c", "d"]
    assert cache.size() == 3


def test_failed_sources_are_not_cached():
    driver = _driver(fail={"fulltext"})
    first = search(driver, "diffusion", Filters(), cache=True)
    assert first["failed_sources"] == ["fulltext"]
    assert search(driver, "diffusion", Filters(), cache=True)["cached"] is False
    assert cache.size() == 0


def test_hybrid_while_the_embedding_index_builds_is_not_cached(monkeypatch):
    from services.library_search import semantic

    monkeypatch.setattr(semantic, "status", lambda: {"state": "building", "indexed": 0})
    monkeypatch.setattr(semantic, "query", lambda q, k=200: [])
    driver = _driver()
    res = search(driver, "diffusion", Filters(), mode="hybrid", cache=True)
    assert res["mode"] == "lexical" and res["semantic"]["state"] == "building"
    assert cache.size() == 0
    monkeypatch.setattr(semantic, "status", lambda: {"state": "ready", "indexed": 10})
    search(driver, "diffusion", Filters(), mode="hybrid", cache=True)
    assert cache.size() == 1


def test_cached_response_does_not_share_mutable_state(monkeypatch):
    from services.library_search import semantic

    monkeypatch.setattr(semantic, "status", lambda: {"state": "ready", "indexed": 10})
    monkeypatch.setattr(semantic, "query", lambda q, k=200: [])
    driver = _driver()
    first = search(driver, "diffusion", Filters(), mode="hybrid", cache=True)
    first["semantic"]["state"] = "tampered"
    first["failed_sources"].append("x")
    second = search(driver, "diffusion", Filters(), mode="hybrid", cache=True)
    assert second["cached"] and second["semantic"]["state"] == "ready" and second["failed_sources"] == []


# ── the middleware in main.py ─────────────────────────────────────────────────

async def test_non_get_requests_bump_the_generation_and_get_does_not():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        before = cache.generation()
        await c.get("/health")
        assert cache.generation() == before
        await c.post("/health")                 # 405, but still a write-shaped request
        assert cache.generation() == before + 1
        await c.delete("/papers/does-not-exist")
        assert cache.generation() == before + 2
        await c.options("/health")
        assert cache.generation() == before + 2
