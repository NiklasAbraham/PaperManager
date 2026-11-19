"""Abstract backfill: text cleaning, title matching, quality checks, DOI and header parsing (pure)."""
from datetime import datetime, timezone

import pytest

from services import abstract_backfill as ab
from tests.abstract_backfill_helpers import LONG


# ── inverted index ────────────────────────────────────────────────────────────

def test_inverted_index_rebuilds_word_order():
    index = {"The": [0, 5], "model": [1], "fits": [2], "data": [3], "and": [4], "model.": [6]}
    assert ab.rebuild_inverted_index(index) == "The model fits data and The model."


def test_inverted_index_tolerates_gaps_none_and_junk():
    assert ab.rebuild_inverted_index(None) == ""
    assert ab.rebuild_inverted_index({}) == ""
    assert ab.rebuild_inverted_index({"b": [5], "a": [2]}) == "a b"          # gaps do not matter
    assert ab.rebuild_inverted_index({"a": "oops", "b": [0, -1, "x"]}) == "b"


# ── cleaning ──────────────────────────────────────────────────────────────────

def test_clean_jats_heading_tags_and_entities():
    raw = ("<jats:title>Abstract</jats:title><jats:p>We show that p &lt; 0.05 for "
           "H<jats:sub>2</jats:sub>O &amp; <jats:italic>more</jats:italic>.</jats:p>")
    assert ab.clean_abstract(raw) == "We show that p < 0.05 for H2O & more."


def test_clean_keeps_bare_comparisons_and_real_words_after_abstract():
    assert ab.clean_abstract("Rates fell when p<0.05 and q > 0.1 held.") == "Rates fell when p<0.05 and q > 0.1 held."
    assert ab.clean_abstract("Abstract concepts are hard to learn.") == "Abstract concepts are hard to learn."


@pytest.mark.parametrize("raw", ["Abstract: We study x.", "ABSTRACT We study x.", "Abstract\nWe study x.",
                                 "Abstract. We study x.", "Abstract — We study x."])
def test_clean_strips_abstract_heading(raw):
    assert ab.clean_abstract(raw) == "We study x."


def test_clean_collapses_whitespace_and_handles_empty():
    assert ab.clean_abstract("  a \n\n b\t c ") == "a b c"
    assert ab.clean_abstract(None) == "" and ab.clean_abstract("") == "" and ab.clean_abstract(5) == ""


# ── titles ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Scaling Laws for Synthetic Systems", "scaling laws for synthetic systems."),
    ("A Study of <i>Toy</i> Models: Part 2", "A study of toy models - part 2"),
    ("Réseaux de neurones synthétiques et leur étude", "Reseaux de neurones synthetiques et leur etude"),
    ("Learning toy representations of synthetic data in practice", "Learning toy representations of synthetic data in practice today"),
    ("Models of toy systems under repeated stress testing", "Stress testing under repeated models of toy systems"),
])
def test_titles_match(a, b):
    assert ab.titles_match(a, b)


@pytest.mark.parametrize("a,b", [
    ("Scaling Laws for Synthetic Systems", "A Survey of Synthetic Data Generators"),
    ("Deep learning", "Deep learning methods and applications in synthetic worlds"),
    ("", "Anything"), ("Anything", None),
    ("Part 1: Toy models", "Part 2: Toy models"),
])
def test_titles_mismatch(a, b):
    assert not ab.titles_match(a, b)


def test_strict_title_match_is_stricter():
    a = "Learning toy representations of synthetic data in practice"
    b = "Learning toy representations of synthetic data in practice today"
    assert ab.titles_match(a, b) and not ab.titles_match(a, b, strict=True)
    assert ab.titles_match(a, a.upper() + ".", strict=True)


# ── quality ───────────────────────────────────────────────────────────────────

def test_quality_accepts_normal_abstract():
    assert ab.quality_problem(LONG, "Another title") is None


@pytest.mark.parametrize("text,problem", [
    ("", "empty"),
    ("Too short to be an abstract.", "too_short"),
    ("x " * 4000, "too_long"),
    ("Abstract not available", "placeholder"),
    ("No abstract available.", "placeholder"),
    ("n/a", "placeholder"),
    ("[No abstract]", "placeholder"),
    ("Abstract is not available for this article at the present time, see the publisher.", "placeholder"),
    ("1234 5678 9012 3456 7890 1234 5678 9012 3456 7890 1234 5678 9012 3456 7890 1234 5678 9012 ####", "not_text"),
])
def test_quality_rejects(text, problem):
    assert ab.quality_problem(text, "Some title") == problem


def test_quality_rejects_title_repeated_as_abstract():
    title = "A synthetic study of repeated perturbation in toy systems and their responses"
    assert ab.quality_problem(title + ".", title) == "title_only"


# ── DOI and headers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,key", [
    ("10.1234/ABC.def", "10.1234/abc.def"),
    ("https://doi.org/10.1234/Abc", "10.1234/abc"),
    ("doi:10.1234/abc", "10.1234/abc"),
    ("http://dx.doi.org/10.1234/abc", "10.1234/abc"),
    (" 10.1234/abc. ", "10.1234/abc"),
    ("arXiv:2101.00001v2", "10.48550/arxiv.2101.00001"),
    ("10.48550/arXiv.2101.00001", "10.48550/arxiv.2101.00001"),
    ("not a doi", None), ("", None), (None, None),
])
def test_doi_for_lookup(raw, key):
    assert ab.doi_for_lookup(raw) == key


def test_arxiv_id_of():
    assert ab.arxiv_id_of("10.48550/arxiv.2101.00001") == "2101.00001"
    assert ab.arxiv_id_of("10.48550/arxiv.2101.00001v3") == "2101.00001"
    assert ab.arxiv_id_of("10.1234/abc") is None


def test_parse_retry_after():
    assert ab.parse_retry_after("7") == 7.0
    assert ab.parse_retry_after("0") == 0.0
    assert ab.parse_retry_after("-3") == 0.0
    assert ab.parse_retry_after(None) is None and ab.parse_retry_after("soon") is None
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert ab.parse_retry_after("Thu, 01 Jan 2026 12:00:30 GMT", now) == 30.0


def test_user_agent_and_contact_from_env(monkeypatch):
    monkeypatch.delenv("ABSTRACT_BACKFILL_CONTACT", raising=False)
    assert ab.contact_from_env() == ""
    assert ab.user_agent("") == "PaperManager-abstract-backfill/1.0"
    monkeypatch.setenv("ABSTRACT_BACKFILL_CONTACT", "  ops@example.invalid\n ")
    assert ab.contact_from_env() == "ops@example.invalid"
    assert ab.user_agent("ops@example.invalid") == "PaperManager-abstract-backfill/1.0 (ops@example.invalid)"


def test_normalise_sources_order_and_aliases():
    assert ab.normalise_sources(None) == list(ab.SOURCES)
    assert ab.normalise_sources(["crossref", "semantic_scholar", "OpenAlex"]) == ["openalex", "semanticscholar", "crossref"]
    with pytest.raises(ValueError):
        ab.normalise_sources(["pubmed"])
