"""Abstract backfill end to end on a fake driver and fake HTTP: source order, safety checks,
dry run, apply, idempotency, races, outages, stubs, title search, undo, API summary."""
import json

import pytest

from services import abstract_backfill as ab
from tests.abstract_backfill_helpers import LONG, FakeDriver, FakeWeb, paper


def text(n: int) -> str:
    return f"{LONG} Variant {n}."


def run(driver, web, **kw):
    kw.setdefault("contact", "")
    kw.setdefault("s2_api_key", "")
    return ab.run_backfill(driver, http=web.http(), **kw)


def by_id(report):
    return {p["id"]: p for p in report["papers"]}


@pytest.fixture
def lib():
    return FakeDriver([
        paper("pa", "10.1111/a", "Alpha scaling of toy systems"),
        paper("pb", "https://doi.org/10.1111/B", "Beta response of toy systems"),
        paper("pc", "10.48550/arXiv.2101.00003", "Gamma models of toy systems"),
        paper("pd", "doi:10.1111/d", "Delta limits of toy systems"),
        paper("pe", "10.1111/e", "Epsilon without any abstract anywhere"),
    ])


@pytest.fixture
def web():
    w = FakeWeb()
    w.openalex["10.1111/a"] = ("Alpha scaling of toy systems", text(1))
    w.s2["10.1111/b"] = ("Beta response of toy systems", text(2))
    w.arxiv["2101.00003"] = ("Gamma models of toy systems", text(3))
    w.crossref["10.1111/d"] = ("Delta limits of toy systems", "<jats:p>" + text(4) + "</jats:p>")
    return w


# ── order and fall-through ────────────────────────────────────────────────────

def test_sources_in_order_and_each_asks_only_for_what_is_missing(lib, web):
    report = run(lib, web, dry_run=False)
    assert [h for i, h in enumerate(web.hosts()) if i == 0 or h != web.hosts()[i - 1]] == [
        "api.openalex.org", "api.semanticscholar.org", "export.arxiv.org", "api.crossref.org"]
    oa = web.to("api.openalex.org")
    assert len(oa) == 1 and len(oa[0].url.params["filter"][4:].split("|")) == 5
    s2_ids = json.loads(web.to("api.semanticscholar.org")[0].content)["ids"]
    assert sorted(s2_ids) == sorted(["DOI:10.1111/b", "DOI:10.48550/arxiv.2101.00003", "DOI:10.1111/d", "DOI:10.1111/e"])
    assert web.to("export.arxiv.org")[0].url.params["id_list"] == "2101.00003"
    assert sorted(r.url.path for r in web.to("api.crossref.org")) == ["/works/10.1111/d", "/works/10.1111/e"]
    assert {pid: lib.get(pid).get("abstract_source") for pid in ("pa", "pb", "pc", "pd", "pe")} == {
        "pa": "openalex", "pb": "semanticscholar", "pc": "arxiv", "pd": "crossref", "pe": None}
    assert lib.get("pd")["abstract"] == text(4)
    c = report["counts"]
    assert (c["candidates"], c["applied"], c["no_abstract_found"], c["errors"]) == (5, 4, 1, 0)
    assert report["accepted_by_source"] == {"openalex": 1, "semanticscholar": 1, "arxiv": 1, "crossref": 1}
    assert by_id(report)["pe"]["outcome"] == "no_abstract_found"


def test_a_source_without_abstract_falls_through_to_the_next(lib, web):
    web.openalex["10.1111/b"] = ("Beta response of toy systems", "")      # known, but no abstract
    run(lib, web, dry_run=False)
    assert lib.get("pb")["abstract_source"] == "semanticscholar"


def test_sources_option_restricts_and_keeps_fixed_order(lib, web):
    report = run(lib, web, sources=["crossref", "openalex"])
    assert set(web.hosts()) == {"api.openalex.org", "api.crossref.org"}
    assert web.hosts()[0] == "api.openalex.org"
    assert list(report["per_source"]) == ["openalex", "crossref"]
    with pytest.raises(ValueError):
        run(lib, web, sources=["nope"])


# ── safety checks ─────────────────────────────────────────────────────────────

def test_title_mismatch_is_not_applied_and_reported_with_both_titles(lib, web):
    web.openalex["10.1111/a"] = ("A completely different paper about something else", text(1))
    report = run(lib, web, dry_run=False, sources=["openalex"])
    assert not lib.get("pa").get("abstract")
    e = by_id(report)["pa"]
    assert e["outcome"] == "title_mismatch"
    assert e["title_mismatch"] == [{"source": "openalex", "library_title": "Alpha scaling of toy systems",
                                    "returned_title": "A completely different paper about something else"}]
    assert report["counts"]["title_mismatch"] == 1 and report["counts"]["applied"] == 0


def test_mismatch_in_one_source_still_lets_a_later_good_source_win(lib, web):
    web.openalex["10.1111/b"] = ("Unrelated wrong record", text(9))
    report = run(lib, web, dry_run=False)
    assert lib.get("pb")["abstract_source"] == "semanticscholar" and lib.get("pb")["abstract"] == text(2)
    assert by_id(report)["pb"]["outcome"] == "applied"
    assert by_id(report)["pb"]["title_mismatch"][0]["source"] == "openalex"


@pytest.mark.parametrize("bad,reason", [
    ("Too short.", "too_short"),
    ("Abstract not available", "placeholder"),
    ("word " * 2000, "too_long"),
    ("Alpha scaling of toy systems", "title_only"),
])
def test_bad_abstracts_are_rejected(lib, web, bad, reason):
    web.openalex["10.1111/a"] = ("Alpha scaling of toy systems", bad)
    report = run(lib, web, dry_run=False, sources=["openalex"])
    assert not lib.get("pa").get("abstract")
    e = by_id(report)["pa"]
    assert e["outcome"] == "rejected_quality" and e["rejected"] == [{"source": "openalex", "reason": reason}]


def test_abstract_is_cleaned_before_it_is_stored(lib, web):
    web.openalex["10.1111/a"] = ("Alpha scaling of toy systems", "Abstract: " + LONG.replace("synthetic", "<i>synthetic</i> &amp;"))
    run(lib, web, dry_run=False, sources=["openalex"])
    assert lib.get("pa")["abstract"] == LONG.replace("synthetic", "synthetic &")


# ── never overwrite ───────────────────────────────────────────────────────────

def test_existing_abstract_is_never_a_candidate(web):
    d = FakeDriver([paper("px", "10.1111/a", "Alpha scaling of toy systems", abstract="Mine, written by hand.")])
    report = run(d, web, dry_run=False)
    assert report["counts"]["candidates"] == 0 and d.get("px")["abstract"] == "Mine, written by hand."
    assert web.requests == []


def test_whitespace_only_abstract_counts_as_empty(web):
    d = FakeDriver([paper("px", "10.1111/a", "Alpha scaling of toy systems", abstract="  \n ")])
    run(d, web, dry_run=False, sources=["openalex"])
    assert d.get("px")["abstract"] == text(1)


def test_abstract_appearing_between_select_and_write_wins(lib, web):
    lib.before_write = lambda pid, d: d.papers[pid].__setitem__("abstract", "Added by a user meanwhile.") if pid == "pa" else None
    report = run(lib, web, dry_run=False)
    assert lib.get("pa")["abstract"] == "Added by a user meanwhile."
    assert "abstract_source" not in lib.get("pa")
    assert by_id(report)["pa"]["outcome"] == "skipped_has_abstract"
    assert report["counts"]["skipped_has_abstract"] == 1 and report["counts"]["applied"] == 3


def test_write_query_is_guarded_parameterised_and_leaves_updated_at_alone():
    q = ab.WRITE_QUERY
    assert "p.abstract IS NULL OR trim(p.abstract) = ''" in q and "{id: $id}" in q
    assert "abstract_source = $source" in q and "abstract_fetched_at = $now" in q
    assert "updated_at" not in q


def test_every_query_sent_is_parameterised(lib, web):
    run(lib, web, dry_run=False)
    for query, params in lib.queries:
        for value in ("10.1111", "Alpha", "pa", "openalex"):
            assert value not in query
    assert any(params.get("abstract") for _, params in lib.queries)


# ── dry run, apply, idempotency ───────────────────────────────────────────────

def test_dry_run_is_the_default_and_writes_nothing(lib, web):
    report = run(lib, web)
    assert report["dry_run"] is True
    assert lib.writes == [] and not any(lib.get(p).get("abstract") for p in lib.papers)
    assert not any(q == ab.WRITE_QUERY for q, _ in lib.queries)
    c = report["counts"]
    assert c["would_apply"] == 4 and "applied" not in c
    assert by_id(report)["pa"]["outcome"] == "would_apply" and by_id(report)["pa"]["abstract_length"] == len(text(1))


def test_apply_writes_source_and_time_and_reports_counts(lib, web):
    report = run(lib, web, dry_run=False)
    p = lib.get("pa")
    assert p["abstract"] == text(1) and p["abstract_source"] == "openalex" and p["abstract_fetched_at"]
    assert "updated_at" not in p
    assert len(lib.writes) == 4 and report["counts"]["applied"] == 4
    assert by_id(report)["pa"]["abstract_sha1"]
    assert report["per_source"]["openalex"] == {"requests": 1, "found": 1, "accepted": 1, "errors": 0, "disabled": False}


def test_second_run_only_handles_what_is_still_missing(lib, web):
    run(lib, web, dry_run=False)
    web.requests.clear()
    second = run(lib, web, dry_run=False)
    assert second["counts"]["candidates"] == 1            # only the paper nobody had an abstract for
    assert second["counts"]["applied"] == 0 and len(lib.writes) == 4
    assert set(by_id(second)) == {"pe"}


def test_limit_cuts_the_stable_id_ordered_list(lib, web):
    report = run(lib, web, limit=2, dry_run=False)
    assert report["counts"]["candidates"] == 2 and report["counts"]["candidates_total"] == 5
    assert set(by_id(report)) == {"pa", "pb"}


def test_two_papers_with_one_doi_both_get_the_abstract(web):
    d = FakeDriver([paper("p1", "10.1111/a", "Alpha scaling of toy systems"),
                    paper("p2", "https://doi.org/10.1111/A", "Alpha scaling of toy systems.")])
    report = run(d, web, dry_run=False, sources=["openalex"])
    assert report["counts"]["applied"] == 2 and len(json.loads(json.dumps(report))["papers"]) == 2
    assert len(web.to("api.openalex.org")) == 1


# ── stubs, missing DOIs ───────────────────────────────────────────────────────

def test_reference_stubs_are_left_alone_unless_asked(web):
    d = FakeDriver([paper("p1", "10.1111/a", "Alpha scaling of toy systems", tags=["from-references"]),
                    paper("p2", "10.1111/b", "Beta response of toy systems", tags=["to-read"])])
    web.openalex["10.1111/b"] = ("Beta response of toy systems", text(2))
    report = run(d, web, dry_run=False, sources=["openalex"])
    assert set(by_id(report)) == {"p2"} and not d.get("p1").get("abstract")
    report = run(d, web, dry_run=False, sources=["openalex"], include_stubs=True)
    assert d.get("p1")["abstract"] == text(1) and report["options"]["include_stubs"] is True


def test_papers_without_a_usable_doi_are_counted_and_skipped(web):
    d = FakeDriver([paper("p1", None, "No doi here at all"), paper("p2", "  ", "Blank doi"),
                    paper("p3", "not-a-doi", "Garbage doi"), paper("p4", "10.1111/a", "Alpha scaling of toy systems")])
    report = run(d, web, dry_run=False)
    c = report["counts"]
    assert (c["no_doi"], c["invalid_doi"], c["candidates"]) == (2, 1, 1)
    assert set(by_id(report)) == {"p4"}


# ── outages ───────────────────────────────────────────────────────────────────

def test_failing_source_is_recorded_and_the_next_one_takes_over(lib, web):
    web.down.add("api.openalex.org")
    web.s2["10.1111/a"] = ("Alpha scaling of toy systems", text(1))
    report = run(lib, web, dry_run=False)
    assert lib.get("pa")["abstract_source"] == "semanticscholar"
    assert report["per_source"]["openalex"]["errors"] == 1
    assert report["errors"][0]["source"] == "openalex" and "503" in report["errors"][0]["message"]
    assert report["counts"]["errors"] == 1 and report["counts"]["applied"] == 4


def test_everything_down_never_crashes_and_reports_incomplete_lookups(lib, web):
    web.down.update(["api.openalex.org", "api.semanticscholar.org", "export.arxiv.org", "api.crossref.org"])
    report = run(lib, web, dry_run=False)
    assert report["counts"]["applied"] == 0 and report["counts"]["no_abstract_found"] == 5
    assert report["counts"]["incomplete_lookup"] == 5 and report["counts"]["errors"] >= 4
    assert by_id(report)["pa"]["failed_sources"] == ["crossref", "openalex", "semanticscholar"]
    assert lib.writes == []


def test_a_dead_source_is_switched_off_after_repeated_failures():
    web = FakeWeb()
    web.down.add("api.crossref.org")
    d = FakeDriver([paper(f"p{i}", f"10.1111/x{i}", f"Title {i}") for i in range(20)])
    report = run(d, web, sources=["crossref"])
    assert report["per_source"]["crossref"]["disabled"] is True
    assert len(web.requests) == 5 * (ab.MAX_RETRIES + 1)          # five failed DOIs, then no more
    assert report["counts"]["incomplete_lookup"] == 20


def test_unexpected_parser_error_is_contained(lib, web, monkeypatch):
    monkeypatch.setattr(ab, "parse_openalex", lambda payload: (_ for _ in ()).throw(KeyError("boom")))
    report = run(lib, web, dry_run=False)
    assert report["per_source"]["openalex"]["errors"] == 1
    assert report["counts"]["applied"] == 3                         # the others filled the gap


def test_429_with_retry_after_is_waited_out(lib, web):
    web.limited["api.openalex.org"] = 1
    web.retry_after = "11"
    report = run(lib, web, dry_run=False)
    assert 11.0 in web.clock.sleeps and report["counts"]["errors"] == 0
    assert lib.get("pa")["abstract_source"] == "openalex"


def test_database_write_failure_is_counted_not_raised(lib, web):
    lib.fail_write.add("pa")
    report = run(lib, web, dry_run=False)
    assert by_id(report)["pa"]["outcome"] == "error" and report["counts"]["errors"] == 1
    assert report["counts"]["applied"] == 3


def test_candidate_query_failure_returns_an_error_report(web):
    class Broken:
        def session(self):
            raise RuntimeError("no database")

    report = run(Broken(), web)
    assert report["errors"][0]["source"] == "database" and report["counts"] == {"errors": 1}


# ── title search (default off) ────────────────────────────────────────────────

def test_title_search_is_off_by_default(web):
    d = FakeDriver([paper("p1", None, "Alpha scaling of toy systems under load")])
    web.openalex_by_title["Alpha scaling of toy systems under load"] = [("Alpha scaling of toy systems under load", text(1))]
    run(d, web, dry_run=False)
    assert web.requests == [] and not d.get("p1").get("abstract")


def test_title_search_accepts_only_a_very_strict_match(web):
    t = "Alpha scaling of toy systems under load"
    d = FakeDriver([paper("p1", None, t), paper("p2", None, "Beta scaling of toy systems under repeated load")])
    web.openalex_by_title[t] = [(t.upper() + ".", text(1))]
    web.openalex_by_title["Beta scaling of toy systems under repeated load"] = [
        ("Beta scaling of toy systems under repeated load and stress", text(2))]
    report = run(d, web, dry_run=False, title_search=True)
    assert d.get("p1")["abstract"] == text(1) and d.get("p1")["abstract_source"] == "openalex"
    assert not d.get("p2").get("abstract")
    assert by_id(report)["p2"]["outcome"] == "no_abstract_found"
    assert report["counts"]["no_doi"] == 2


def test_title_search_ambiguity_is_refused(web):
    t = "Alpha scaling of toy systems under load"
    d = FakeDriver([paper("p1", None, t)])
    web.openalex_by_title[t] = [(t, text(1)), (t, text(2))]
    report = run(d, web, dry_run=False, title_search=True)
    assert not d.get("p1").get("abstract") and by_id(report)["p1"]["rejected"][0]["reason"] == "ambiguous_title"


# ── undo ──────────────────────────────────────────────────────────────────────

def test_undo_clears_only_what_the_report_applied_and_still_matches(lib, web):
    report = run(lib, web, dry_run=False)
    lib.get("pb")["abstract"] = "Edited by the user afterwards."          # same source tag, other text
    lib.get("pc")["abstract_source"] = "manual"                          # source changed
    lib.papers["pz"] = {"id": "pz", "abstract": "Written by hand", "doi": "10.1111/z", "title": "Z"}
    report["papers"].append({"id": "pz", "outcome": "applied", "source": "openalex", "abstract_sha1": "0" * 40})
    report["papers"].append({"id": "gone", "outcome": "applied", "source": "openalex"})

    dry = ab.undo_report(lib, report, dry_run=True)
    assert dry["would_clear"] == 2 and dry["cleared"] == 0 and lib.get("pa")["abstract"] == text(1)

    res = ab.undo_report(lib, report, dry_run=False)
    assert res["cleared"] == 2 and res["skipped_source_mismatch"] == 2 and res["skipped_text_changed"] == 1
    assert res["not_found"] == 1
    for pid in ("pa", "pd"):
        assert "abstract" not in lib.get(pid) and "abstract_source" not in lib.get(pid)
    assert lib.get("pb")["abstract"] == "Edited by the user afterwards."
    assert lib.get("pc")["abstract"] == text(3)
    assert lib.get("pz")["abstract"] == "Written by hand"


def test_undo_ignores_would_apply_entries(lib, web):
    report = run(lib, web)                                               # dry run
    assert ab.undo_report(lib, report, dry_run=False)["listed"] == 0


def test_undo_then_run_again_restores_the_same_abstracts(lib, web):
    report = run(lib, web, dry_run=False)
    ab.undo_report(lib, report, dry_run=False)
    assert not any(lib.get(p).get("abstract") for p in lib.papers)
    run(lib, web, dry_run=False)
    assert lib.get("pa")["abstract"] == text(1)


# ── API summary ───────────────────────────────────────────────────────────────

def test_api_summary_has_counts_samples_but_no_titles():
    web = FakeWeb()
    d = FakeDriver([paper(f"p{i:03d}", f"10.1111/x{i}", f"Confidential-looking title {i}") for i in range(120)])
    for i in range(120):
        web.openalex[f"10.1111/x{i}"] = (f"Confidential-looking title {i}" if i % 2 else "Something else entirely", text(i))
    report = run(d, web)
    summary = ab.summarize_for_api(report)
    assert len(summary["sample_ids"]) == 50
    assert {s["outcome"] for s in summary["sample_ids"]} == {"would_apply", "title_mismatch"}
    assert summary["counts"]["would_apply"] == 60 and summary["counts"]["title_mismatch"] == 60
    dumped = json.dumps(summary)
    assert "Confidential" not in dumped and "Something else" not in dumped and "papers" not in summary
