"""Abstract backfill: each source's request shape and parser on synthetic payloads, the HTTP layer
(rate limit, retries, Retry-After) and batching. All HTTP goes through httpx.MockTransport."""
import httpx
import pytest

from services import abstract_backfill as ab
from tests.abstract_backfill_helpers import LONG, FakeWeb, _invert


# ── parsers ───────────────────────────────────────────────────────────────────

def test_parse_openalex_builds_abstract_and_keys_by_doi():
    payload = {"results": [
        {"id": "W1", "doi": "https://doi.org/10.1234/ABC", "title": "Toy models",
         "abstract_inverted_index": _invert(LONG)},
        {"id": "W2", "doi": "https://doi.org/10.1234/none", "title": "No abstract", "abstract_inverted_index": None},
        {"id": "W3", "doi": None, "title": "No doi", "abstract_inverted_index": _invert(LONG)},
        "junk",
    ]}
    hits = ab.parse_openalex(payload)
    assert set(hits) == {"10.1234/abc", "10.1234/none"}
    assert hits["10.1234/abc"].abstract == LONG and hits["10.1234/abc"].title == "Toy models"
    assert hits["10.1234/none"].abstract == ""
    assert ab.parse_openalex({}) == {} and ab.parse_openalex(None) == {}


def test_parse_s2_batch_aligns_with_request_and_skips_null():
    keys = ["10.1111/a", "10.1111/b", "10.1111/c"]
    payload = [{"title": "A", "abstract": "x"}, None, {"title": "C", "abstract": None}]
    hits = ab.parse_s2_batch(keys, payload)
    assert set(hits) == {"10.1111/a", "10.1111/c"}
    assert hits["10.1111/c"].abstract == ""
    assert ab.parse_s2_batch(keys, {"error": "x"}) == {}


ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2101.00001v2</id><title>Toy
  models of things</title><summary>  We study things.
 More text. </summary></entry>
<entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_x</id><title>Error</title><summary>bad id</summary></entry>
<entry><id>http://arxiv.org/abs/cs/0010026v1</id><title>Old style</title><summary>old</summary></entry>
</feed>"""


def test_parse_arxiv_feed_versions_errors_and_old_ids():
    hits = ab.parse_arxiv_feed(ATOM)
    assert set(hits) == {"10.48550/arxiv.2101.00001", "10.48550/arxiv.cs/0010026"}
    h = hits["10.48550/arxiv.2101.00001"]
    assert h.title == "Toy models of things" and "We study things." in h.abstract
    with pytest.raises(ab.SourceError):
        ab.parse_arxiv_feed("<not xml")


def test_parse_crossref_strips_jats():
    payload = {"message": {"title": ["Toy models"], "abstract":
               "<jats:title>Abstract</jats:title><jats:p>We study <jats:italic>x</jats:italic>.</jats:p>"}}
    hit = ab.parse_crossref(payload)
    assert hit.title == "Toy models"
    assert ab.clean_abstract(hit.abstract) == "We study x."
    assert ab.parse_crossref({}) is None and ab.parse_crossref({"message": "x"}) is None


# ── request shapes ────────────────────────────────────────────────────────────

def test_openalex_request_shape_and_polite_params():
    web = FakeWeb()
    web.openalex["10.1111/a"] = ("A", LONG)
    http = web.http(contact="ops@example.invalid")
    hits = ab.OpenAlex(http).fetch(["10.1111/a", "10.1111/b"])
    assert set(hits) == {"10.1111/a"}
    req = web.requests[0]
    p = req.url.params
    assert p["filter"] == "doi:https://doi.org/10.1111/a|https://doi.org/10.1111/b"
    assert p["per-page"] == "50"
    assert p["select"] == "id,doi,title,abstract_inverted_index,publication_year"
    assert p["mailto"] == "ops@example.invalid"
    assert req.headers["User-Agent"] == "PaperManager-abstract-backfill/1.0 (ops@example.invalid)"


def test_no_contact_means_no_mailto_and_plain_user_agent():
    web = FakeWeb()
    ab.OpenAlex(web.http()).fetch(["10.1111/a"])
    ab.Crossref(web.http()).fetch(["10.1111/a"])
    for req in web.requests:
        assert "mailto" not in req.url.params
        assert req.headers["User-Agent"] == "PaperManager-abstract-backfill/1.0"


def test_openalex_skips_dois_that_break_its_filter_syntax():
    oa = ab.OpenAlex(FakeWeb().http())
    assert oa.accepts("10.1111/a") and not oa.accepts("10.1111/a,b") and not oa.accepts("10.1111/a|b")


def test_s2_request_shape_with_and_without_key():
    web = FakeWeb()
    web.s2["10.1111/a"] = ("A", LONG)
    anon = ab.SemanticScholar(web.http(), "")
    assert anon.batch_size == 100
    assert set(anon.fetch(["10.1111/a", "10.1111/b"])) == {"10.1111/a"}
    req = web.requests[0]
    assert req.method == "POST" and req.url.path == "/graph/v1/paper/batch"
    assert req.url.params["fields"] == "title,abstract,externalIds"
    import json

    assert json.loads(req.content) == {"ids": ["DOI:10.1111/a", "DOI:10.1111/b"]}
    assert "x-api-key" not in req.headers
    keyed = ab.SemanticScholar(web.http(), "test-key")
    assert keyed.batch_size == 500 and keyed.interval < anon.interval
    keyed.fetch(["10.1111/a"])
    assert web.requests[-1].headers["x-api-key"] == "test-key"


def test_arxiv_only_takes_arxiv_dois_and_asks_by_id_list():
    web = FakeWeb()
    web.arxiv["2101.00001"] = ("Toy", LONG)
    src = ab.Arxiv(web.http())
    assert src.batch_size == 100
    assert src.accepts("10.48550/arxiv.2101.00001") and not src.accepts("10.1111/a")
    hits = src.fetch(["10.48550/arxiv.2101.00001", "10.48550/arxiv.2101.00002"])
    assert set(hits) == {"10.48550/arxiv.2101.00001"}
    assert web.requests[0].url.params["id_list"] == "2101.00001,2101.00002"


def test_crossref_one_doi_per_request_404_is_not_an_error():
    web = FakeWeb()
    web.crossref["10.1111/a(b)"] = ("A", "<jats:p>" + LONG + "</jats:p>")
    src = ab.Crossref(web.http())
    assert src.batch_size == 1
    hits = src.fetch(["10.1111/a(b)"])
    assert hits["10.1111/a(b)"].title == "A"
    assert src.fetch(["10.1111/missing"]) == {}
    assert web.requests[0].url.path == "/works/10.1111/a(b)"


# ── HTTP layer ────────────────────────────────────────────────────────────────

def test_min_interval_per_host_is_kept():
    web = FakeWeb()
    http = web.http()
    for _ in range(3):
        http.request("GET", ab.ARXIV_URL, interval=3.1, params={"id_list": "1"})
    assert web.clock.sleeps == [pytest.approx(3.1), pytest.approx(3.1)]
    # another host is not held back by arXiv
    web.clock.sleeps.clear()
    http.request("GET", ab.CROSSREF_URL + "/10.1111/a", interval=0.25)
    assert web.clock.sleeps == []


def test_429_waits_retry_after_then_succeeds():
    web = FakeWeb()
    web.limited["api.openalex.org"] = 2
    web.retry_after = "7"
    web.openalex["10.1111/a"] = ("A", LONG)
    hits = ab.OpenAlex(web.http()).fetch(["10.1111/a"])
    assert "10.1111/a" in hits
    assert web.clock.sleeps.count(7.0) == 2
    assert len(web.requests) == 3


def test_retry_after_longer_than_the_cap_gives_the_source_up():
    web = FakeWeb()
    web.limited["api.openalex.org"] = 1
    web.retry_after = "3600"
    with pytest.raises(ab.SourceError, match="Retry-After"):
        ab.OpenAlex(web.http()).fetch(["10.1111/a"])
    assert len(web.requests) == 1 and 3600.0 not in web.clock.sleeps


def test_5xx_is_retried_with_exponential_backoff_then_raises():
    web = FakeWeb()
    web.down.add("api.openalex.org")
    with pytest.raises(ab.SourceError, match="503"):
        ab.OpenAlex(web.http(backoff=1.0, max_retries=3)).fetch(["10.1111/a"])
    assert len(web.requests) == 4
    backoffs = [s for s in web.clock.sleeps if s >= 1.0]
    assert backoffs == [1.0, 2.0, 4.0]


def test_timeouts_and_connection_errors_are_retried_then_raise():
    calls = []

    def boom(request):
        calls.append(1)
        raise httpx.ConnectTimeout("slow")

    clock_sleeps = []
    http = ab.Http(httpx.Client(transport=httpx.MockTransport(boom)), sleep=clock_sleeps.append,
                   clock=lambda: 0.0, max_retries=2, backoff=0.5)
    with pytest.raises(ab.SourceError, match="ConnectTimeout"):
        ab.OpenAlex(http).fetch(["10.1111/a"])
    assert len(calls) == 3


def test_other_4xx_is_not_retried():
    web = FakeWeb()
    http = web.http()
    r = http.request("GET", "https://example.invalid/x", interval=0)
    assert r.status_code == 404 and len(web.requests) == 1
    with pytest.raises(ab.SourceError, match="HTTP 404"):
        ab._json(r, "example.invalid")


# ── batching ──────────────────────────────────────────────────────────────────

def _run_sources(n, sources, web, **kw):
    from tests.abstract_backfill_helpers import FakeDriver, paper

    driver = FakeDriver([paper(f"p{i:04d}", f"10.9999/x{i}", f"Title number {i} of the synthetic set") for i in range(n)])
    return ab.run_backfill(driver, sources=sources, http=web.http(), contact="", s2_api_key="", **kw)


def test_openalex_batches_of_fifty():
    web = FakeWeb()
    _run_sources(120, ["openalex"], web)
    sizes = [len(r.url.params["filter"][4:].split("|")) for r in web.to("api.openalex.org")]
    assert sizes == [50, 50, 20]


def test_s2_batches_of_one_hundred_anonymous_and_spaced():
    web = FakeWeb()
    _run_sources(250, ["semanticscholar"], web)
    import json

    sizes = [len(json.loads(r.content)["ids"]) for r in web.to("api.semanticscholar.org")]
    assert sizes == [100, 100, 50]
    assert sum(1 for s in web.clock.sleeps if s >= 2.9) == 2


def test_s2_batches_of_five_hundred_with_a_key():
    from tests.abstract_backfill_helpers import FakeDriver, paper

    web = FakeWeb()
    driver = FakeDriver([paper(f"p{i:04d}", f"10.9999/x{i}", f"Title {i}") for i in range(600)])
    ab.run_backfill(driver, sources=["semanticscholar"], http=web.http(), contact="", s2_api_key="k")
    import json

    assert [len(json.loads(r.content)["ids"]) for r in web.to("api.semanticscholar.org")] == [500, 100]


def test_arxiv_batches_of_one_hundred_with_three_seconds_between():
    from tests.abstract_backfill_helpers import FakeDriver, paper

    web = FakeWeb()
    driver = FakeDriver([paper(f"p{i:04d}", f"10.48550/arXiv.2101.{i:05d}", f"Title {i}") for i in range(230)])
    ab.run_backfill(driver, sources=["arxiv"], http=web.http(), contact="", s2_api_key="")
    sizes = [len(r.url.params["id_list"].split(",")) for r in web.to("export.arxiv.org")]
    assert sizes == [100, 100, 30]
    assert sum(1 for s in web.clock.sleeps if s >= 3.0) == 2
