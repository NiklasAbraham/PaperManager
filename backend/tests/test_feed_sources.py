"""Parsers and paging of the feed sources, on synthetic responses (no network)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from services.feed import sources
from tests.feed_helpers import Resp, atom_page, biorxiv_page, iso

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def entry(n: int, when: datetime, cats=("cs.LG",), **kw) -> dict:
    return {"id": f"2611.{n:05d}", "title": f"Paper  {n}\n  on topic", "summary": "An abstract\n with breaks.",
            "published": iso(when), "categories": list(cats), **kw}


def test_parse_arxiv_fields_and_whitespace():
    page = atom_page([entry(1, NOW, cats=("cs.LG", "stat.ML"), authors=["Ada Example", "Bo Sample"],
                            doi="10.0000/example.1")])
    [c] = sources.parse_arxiv(page)
    assert c.id == "arxiv:2611.00001" and c.source == "arxiv" and c.ext_id == "2611.00001"
    assert c.title == "Paper 1 on topic"
    assert c.abstract == "An abstract with breaks."
    assert c.authors == ["Ada Example", "Bo Sample"]
    assert c.categories == ["cs.LG", "stat.ML"]
    assert c.doi == "10.0000/example.1"
    assert c.url == "https://arxiv.org/abs/2611.00001"
    assert c.published == "2026-11-18T12:00:00Z"


def test_parse_arxiv_old_style_id_and_skips_error_entries():
    page = atom_page([{"id": "hep-th/9901001", "published": "1999-01-05T00:00:00Z", "title": "Old"}])
    page = page.replace("</feed>", "<entry><id>http://arxiv.org/api/errors#x</id><title>Error</title></entry></feed>")
    out = sources.parse_arxiv(page)
    assert [c.id for c in out] == ["arxiv:hep-th/9901001"]


class FakeArxiv:
    """Serves pages of a newest-first list, 100 per page, and records every request."""

    def __init__(self, entries_by_cat: dict[str, list[dict]]):
        self.data, self.calls = entries_by_cat, []

    def __call__(self, url, params=None, **_):
        self.calls.append(params)
        cat = params["search_query"].removeprefix("cat:")
        chunk = self.data[cat][params["start"]:params["start"] + params["max_results"]]
        return Resp(text=atom_page(chunk))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(sources, "_sleep", slept.append)
    monkeypatch.setattr(sources, "_last_arxiv_request", 0.0)
    return slept


def test_fetch_arxiv_pages_until_since_and_drops_older(no_sleep):
    es = [entry(i, NOW - timedelta(hours=i)) for i in range(250)]      # 250 papers, one per hour back
    fake = FakeArxiv({"cs.LG": es})
    got, err = sources.fetch_arxiv(["cs.LG"], NOW - timedelta(hours=120), max_results=1000, get=fake)
    assert err is None
    assert len(got) == 121                          # hours 0..120 inclusive
    assert all(c.published >= iso(NOW - timedelta(hours=120)) for c in got)
    assert [p["start"] for p in fake.calls] == [0, 100]   # stopped after the page that crossed `since`
    assert all(p["sortBy"] == "submittedDate" and p["sortOrder"] == "descending" for p in fake.calls)


def test_fetch_arxiv_waits_three_seconds_between_requests(monkeypatch, no_sleep):
    clock = [100.0]
    monkeypatch.setattr(sources, "_clock", lambda: clock[0])
    monkeypatch.setattr(sources, "_last_arxiv_request", 100.0)
    monkeypatch.setattr(sources, "_sleep", lambda s: (no_sleep.append(s), clock.__setitem__(0, clock[0] + s)))
    fake = FakeArxiv({"cs.LG": [entry(i, NOW) for i in range(100)], "cs.CV": [entry(500 + i, NOW) for i in range(10)]})
    sources.fetch_arxiv(["cs.LG", "cs.CV"], NOW - timedelta(days=1), max_results=1000, get=fake)
    assert len(fake.calls) == 3                     # cs.LG page 1, cs.LG page 2 (empty), cs.CV
    assert no_sleep and all(abs(s - 3.0) < 1e-9 for s in no_sleep)
    assert len(no_sleep) == 3


def test_fetch_arxiv_dedupes_cross_listed_and_caps(no_sleep):
    shared = [entry(i, NOW) for i in range(5)]
    fake = FakeArxiv({"cs.LG": shared, "cs.CV": shared + [entry(99, NOW, cats=("cs.CV",))]})
    got, _ = sources.fetch_arxiv(["cs.LG", "cs.CV"], NOW - timedelta(days=1), max_results=1000, get=fake)
    assert len(got) == 6
    capped, _ = sources.fetch_arxiv(["cs.LG", "cs.CV"], NOW - timedelta(days=1), max_results=3, get=fake)
    assert len(capped) == 3


def test_fetch_arxiv_failing_category_keeps_the_others(no_sleep):
    def get(url, params=None, **_):
        if params["search_query"] == "cat:cs.CV":
            raise sources.SourceError("HTTP 503")
        return Resp(text=atom_page([entry(1, NOW)]))

    got, err = sources.fetch_arxiv(["cs.CV", "cs.LG"], NOW - timedelta(days=1), max_results=100, get=get)
    assert [c.id for c in got] == ["arxiv:2611.00001"]
    assert "cs.CV" in err and "503" in err


def test_fetch_arxiv_garbage_response_is_an_error_not_an_exception(no_sleep):
    got, err = sources.fetch_arxiv(["cs.LG"], NOW - timedelta(days=1), max_results=100,
                                   get=lambda *a, **k: Resp(text="<<not xml"))
    assert got == [] and err


# ── bioRxiv ───────────────────────────────────────────────────────────────────

def item(doi: str, version="1", date_="2026-11-17", **kw) -> dict:
    return {"doi": doi, "title": f"Title of {doi}", "authors": "Ada Example; Bo Sample;", "date": date_,
            "version": version, "category": "neuroscience", "abstract": "Some  abstract", **kw}


def test_parse_biorxiv_first_versions_only():
    data = biorxiv_page([item("10.0000/aaa"), item("10.0000/bbb", version="2"), item("", version="1")])
    out = sources.parse_biorxiv(data, "biorxiv")
    assert [c.id for c in out] == ["biorxiv:10.0000/aaa"]
    c = out[0]
    assert c.authors == ["Ada Example", "Bo Sample"] and c.categories == ["neuroscience"]
    assert c.published == "2026-11-17T00:00:00+00:00"
    assert c.url == "https://www.biorxiv.org/content/10.0000/aaav1"
    assert c.abstract == "Some abstract"


def test_parse_medrxiv_ids_and_url():
    [c] = sources.parse_biorxiv(biorxiv_page([item("10.0000/ccc")]), "medrxiv")
    assert c.id == "medrxiv:10.0000/ccc" and c.source == "medrxiv" and "medrxiv.org" in c.url


def test_fetch_biorxiv_pages_by_cursor(no_sleep):
    pages = {0: biorxiv_page([item(f"10.0000/p{i}") for i in range(100)], total=130, cursor=0),
             100: biorxiv_page([item(f"10.0000/q{i}") for i in range(30)], total=130, cursor=100)}
    urls = []

    def get(url, params=None, **_):
        urls.append(url)
        return Resp(data=pages[int(url.rsplit("/", 1)[1])])

    got, err = sources.fetch_biorxiv("biorxiv", date(2026, 11, 15), date(2026, 11, 18), max_results=1000, get=get)
    assert err is None and len(got) == 130
    assert urls[0] == "https://api.biorxiv.org/details/biorxiv/2026-11-15/2026-11-18/0"
    assert urls[1].endswith("/100") and len(urls) == 2


def test_fetch_biorxiv_failure_is_reported_with_partial_result(no_sleep):
    calls = []

    def get(url, params=None, **_):
        calls.append(url)
        if len(calls) == 2:
            raise sources.SourceError("HTTP 502")
        return Resp(data=biorxiv_page([item(f"10.0000/p{i}") for i in range(100)], total=300))

    got, err = sources.fetch_biorxiv("medrxiv", date(2026, 11, 15), date(2026, 11, 18), max_results=1000, get=get)
    assert len(got) == 100 and "502" in err


def test_fetch_biorxiv_unknown_server():
    assert sources.fetch_biorxiv("elsewhere", date(2026, 1, 1), date(2026, 1, 2)) == ([], "unknown server elsewhere")


# ── transport ─────────────────────────────────────────────────────────────────

def test_http_get_sends_user_agent_and_retries(monkeypatch, no_sleep):
    monkeypatch.setenv("PAPER_FEED_CONTACT", "https://example.invalid/contact")
    seen = []

    def fake_get(url, params=None, headers=None, **kw):
        seen.append(headers["User-Agent"])
        if len(seen) < 3:
            return httpx.Response(503, request=httpx.Request("GET", url))
        return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(sources.httpx, "get", fake_get)
    r = sources._http_get("https://example.invalid/x", {"a": 1})
    assert r.text == "ok"
    assert seen == ["PaperManager-feed (https://example.invalid/contact)"] * 3
    assert no_sleep == [5.0, 10.0]


def test_http_get_gives_up_with_source_error(monkeypatch, no_sleep):
    monkeypatch.delenv("PAPER_FEED_CONTACT", raising=False)

    def fake_get(url, **kw):
        assert kw["headers"]["User-Agent"] == "PaperManager-feed"
        raise httpx.ConnectError("down")

    monkeypatch.setattr(sources.httpx, "get", fake_get)
    with pytest.raises(sources.SourceError):
        sources._http_get("https://example.invalid/x", retries=2)


# ── rate limits, timeouts, one request at a time ──────────────────────────────

def _scripted_get(monkeypatch, replies):
    """Make httpx.get answer from a list of (status, headers) and record every call."""
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        seen.append(timeout)
        status, hdrs = replies[min(len(seen), len(replies)) - 1]
        return httpx.Response(status, text="ok", headers=hdrs, request=httpx.Request("GET", url))

    monkeypatch.setattr(sources.httpx, "get", fake_get)
    return seen


def test_429_without_retry_after_backs_off_30_60_120_then_gives_up(monkeypatch, no_sleep):
    seen = _scripted_get(monkeypatch, [(429, {})])
    with pytest.raises(sources.RateLimited):
        sources._http_get("https://example.invalid/x")
    assert no_sleep == [30.0, 60.0, 120.0] and len(seen) == 4


def test_429_honours_retry_after_seconds_and_http_date(monkeypatch, no_sleep):
    _scripted_get(monkeypatch, [(429, {"Retry-After": "7"}), (200, {})])
    assert sources._http_get("https://example.invalid/x").text == "ok"
    assert no_sleep == [7.0]
    no_sleep.clear()
    soon = (datetime.now(timezone.utc) + timedelta(seconds=45)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    _scripted_get(monkeypatch, [(429, {"Retry-After": soon}), (200, {})])
    sources._http_get("https://example.invalid/x")
    assert 40 <= no_sleep[0] <= 46


def test_429_asking_for_more_than_five_minutes_is_not_waited_for(monkeypatch, no_sleep):
    seen = _scripted_get(monkeypatch, [(429, {"Retry-After": "900"})])
    with pytest.raises(sources.RateLimited):
        sources._http_get("https://example.invalid/x")
    assert no_sleep == [] and len(seen) == 1


def test_429_then_5xx_use_their_own_schedules(monkeypatch, no_sleep):
    _scripted_get(monkeypatch, [(429, {}), (503, {}), (429, {}), (200, {})])
    sources._http_get("https://example.invalid/x")
    assert no_sleep == [30.0, 5.0, 60.0]


def test_arxiv_reads_wait_90_seconds_and_bioRxiv_keeps_30(monkeypatch, no_sleep):
    seen = _scripted_get(monkeypatch, [(200, {})])
    sources._arxiv_get("https://example.invalid/a", {})
    sources._http_get("https://example.invalid/b")
    assert seen[0].read == 90.0 and seen[0].connect == 15.0
    assert seen[1] == 30.0


def test_a_rate_limited_category_is_reported_with_the_429_marker(no_sleep):
    def get(url, params=None, **_):
        raise sources.RateLimited("HTTP 429 (rate limited)")

    got, err = sources.fetch_arxiv(["cs.LG"], NOW - timedelta(days=1), max_results=100, get=get)
    assert got == [] and sources.is_rate_limited(err) and not sources.is_rate_limited(None)


def test_only_one_arxiv_request_is_in_flight_at_a_time(no_sleep):
    import threading
    import time

    active, peak = [0], [0]
    lock = threading.Lock()

    def get(url, params=None, **_):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        return Resp(text=atom_page([entry(1, NOW)]))

    threads = [threading.Thread(target=sources.fetch_arxiv, args=(["cs.LG"], NOW - timedelta(days=1), 100),
                                kwargs={"get": get}) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] == 1


def test_a_page_that_fails_after_a_full_first_page_returns_the_partial_result_with_an_error(no_sleep):
    es = [entry(i, NOW - timedelta(minutes=i)) for i in range(100)]
    calls = []

    def get(url, params=None, **_):
        calls.append(params["start"])
        if params["start"] == 100:
            raise sources.SourceError("ReadTimeout")
        return Resp(text=atom_page(es))

    got, err = sources.fetch_arxiv(["cs.LG"], NOW - timedelta(days=1), max_results=1000, get=get)
    assert len(got) == 100 and "ReadTimeout" in err and calls == [0, 100]
