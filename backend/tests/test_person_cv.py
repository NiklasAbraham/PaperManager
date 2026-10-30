"""Offline rules of services/person_cv.py: name matching, DOI mapping, author resolution."""
from collections import Counter

from services import person_cv
from services.person_cv import _openalex_doi, _resolve_author, same_person_name


def test_same_person_name_initials_nicknames_hyphens_and_comma_order():
    assert same_person_name("C. P. Robert", "Christian P. Robert")
    assert same_person_name("Tom Rainforth", "Thomas Rainforth")
    assert same_person_name("Ya-Nan Li", "Yanan Li")
    assert same_person_name("Doe, Jane", "Jane Doe")
    assert same_person_name("Jürgen Schmidhuber", "Jurgen Schmidhuber")
    assert not same_person_name("Christian Robert", "Claire Robert")
    assert not same_person_name("Jane Doe", "Jane Roe")


def test_openalex_doi_maps_arxiv_ids_and_doi_urls():
    assert _openalex_doi("arXiv:2507.06037") == "10.48550/arxiv.2507.06037"
    assert _openalex_doi("2307.14973v2") == "10.48550/arxiv.2307.14973"
    assert _openalex_doi("https://doi.org/10.1214/12-STS406") == "10.1214/12-sts406"
    assert _openalex_doi("not a doi") is None


def test_resolve_author_prefers_stored_id_then_paper_votes():
    papers = [{"id": "p1", "title": "A Paper"}]
    assert _resolve_author({"openalex_id": "A1"}, Counter(), papers) == ("A1", "stored")
    votes = Counter({"https://openalex.org/A2": 3, "https://openalex.org/A3": 1})
    assert _resolve_author({"name": "Jane Doe"}, votes, papers) == ("A2", "papers")


def test_resolve_author_rejects_a_namesake_without_a_shared_paper(monkeypatch):
    found = {"results": [{"id": "https://openalex.org/A9", "display_name": "Jane Doe"}]}
    monkeypatch.setattr(person_cv, "_openalex", lambda path, **kw: found)
    monkeypatch.setattr(person_cv, "_author_works", lambda aid, limit=600: ({"title": "Unrelated Chemistry"},))
    papers = [{"id": "p1", "title": "Bayesian Adversarial Privacy"}]
    assert _resolve_author({"name": "Jane Doe"}, Counter(), papers) == (None, "not-found")

    monkeypatch.setattr(person_cv, "_author_works", lambda aid, limit=600: ({"title": "Bayesian adversarial privacy"},))
    assert _resolve_author({"name": "Jane Doe"}, Counter(), papers) == ("A9", "name+title")
