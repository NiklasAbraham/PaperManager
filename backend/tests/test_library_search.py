"""Library search: query parsing, Lucene building, matching, ranking, fusion, engine merge.

Pure functions and a scripted fake driver only; nothing here needs Neo4j.
"""
import re

import numpy as np
import pytest

from services.library_search import semantic
from services.library_search.engine import Filters, filter_clause, search
from services.library_search.query import (
    Coverage,
    Unit,
    UnitMatcher,
    detect_identifier,
    escape_lucene,
    fold,
    lucene_all,
    lucene_any,
    lucene_prefix_all,
    mark,
    matchers_for,
    needles,
    on_fields,
    parse_query,
    snippet,
    within_one_edit,
)
from services.library_search.ranking import (
    Candidate,
    fuse,
    hybrid_weights,
    legacy_matched_in,
    rank,
    rrf,
    score_candidates,
    sort_candidates,
)
from services.library_search.suggest import rank_entities


# ── escaping and parsing ──────────────────────────────────────────────────────

def test_escape_lucene_escapes_every_special_character():
    specials = '+-&|!(){}[]^"~*?:\\/'
    escaped = escape_lucene(specials)
    assert escaped == "".join("\\" + c for c in specials)
    assert escape_lucene("plain words 42") == "plain words 42"


def _units(q):
    return [u.text for u in parse_query(q).units]


def test_parse_drops_stop_words_and_splits_at_punctuation():
    assert _units("Flow Matching for Generative Modeling") == ["flow", "matching", "generative", "modeling"]
    assert _units("title: diffusion") == ["title", "diffusion"]
    # A query of nothing but stop words still searches for them.
    assert _units("the") == ["the"]


def test_parse_prefix_and_fuzzy_flags():
    pq = parse_query("EDM diffusion 3 ab")
    by = {u.text: u for u in pq.units}
    assert by["edm"].prefix and not by["edm"].fuzzy          # 3 letters: prefix only
    assert by["diffusion"].prefix and by["diffusion"].fuzzy  # 5+ letters: prefix and ~1
    assert not by["3"].prefix and not by["3"].fuzzy          # numbers are exact
    assert not by["ab"].prefix                               # too short for a prefix
    star = parse_query("diffus*").units[0]
    assert star.prefix and not star.fuzzy


def test_hyphenated_words_are_phrases_that_also_match_the_joined_word():
    pq = parse_query("over-conditioning co-folding models")
    assert [u.text for u in pq.units] == ["over conditioning", "co folding", "models"]
    assert pq.units[0].alt == ("overconditioning",)
    assert lucene_any(pq).startswith('("over conditioning" OR overconditioning) OR ("co folding" OR cofolding)')
    ms = matchers_for(pq)
    text = "Cofolding models and co-folding: over-conditioning, not over and conditioning"
    assert [text[s:e] for s, e in mark(text, ms[:2])] == ["Cofolding", "co-folding", "over-conditioning"]
    assert Coverage(pq.units[:1], ["over and conditioning"]).covered(["over and conditioning"]) == set()


def test_parse_quoted_phrases_and_unclosed_quote():
    pq = parse_query('"flow matching" ode')
    assert pq.units[0] == Unit(("flow", "matching"), quoted=True)
    assert [u.text for u in pq.units] == ["flow matching", "ode"]
    assert parse_query('"score based').units[0].tokens == ("score", "based")
    single = parse_query('"EDM"').units[0]
    assert single.quoted and not single.prefix and not single.fuzzy


def test_parse_phrase_boost_and_unit_cap():
    assert parse_query("score based generative").phrase == ("score", "based", "generative")
    assert parse_query("diffusion").phrase == ()
    assert len(parse_query(" ".join(f"word{i}" for i in range(30))).units) == 12


@pytest.mark.parametrize("q, ident", [
    ("10.1038/s41586-024-07487-w", {"doi": "10.1038/s41586-024-07487-w"}),
    ("https://doi.org/10.1038/S41586-024-07487-W", {"doi": "10.1038/s41586-024-07487-w"}),
    ("doi:10.48550/arXiv.2210.02747", {"doi": "10.48550/arxiv.2210.02747"}),
    ("2210.02747", {"arxiv": "2210.02747"}),
    ("arXiv:2210.02747v2", {"arxiv": "2210.02747"}),
    ("https://arxiv.org/abs/2210.02747", {"arxiv": "2210.02747"}),
    ("diffusion 2210", None),
])
def test_detect_identifier(q, ident):
    assert detect_identifier(q) == ident


# ── case and accents ──────────────────────────────────────────────────────────

def test_fold_lowercases_and_strips_accents():
    assert fold("Kynkäänniemi") == "kynkaanniemi"
    assert fold("Tübingen ŁUKASZ Ørsted Straße") == "tubingen lukasz orsted strasse"
    assert fold("AlphaFold 3") == "alphafold 3"


@pytest.mark.parametrize("variants", [
    ["EDM", "edm", "Edm"],
    ["Karras", "KARRAS", "karras"],
    ["AlphaFold 3", "alphafold 3", "ALPHAFOLD 3"],
    ["Tübingen", "Tubingen", "TÜBINGEN"],
    ['"Flow Matching"', '"flow matching"'],
])
def test_case_and_accent_variants_build_the_same_lucene_query(variants):
    queries = {lucene_any(parse_query(v)) for v in variants}
    assert len(queries) == 1
    assert {lucene_all(parse_query(v)) for v in variants} == {lucene_all(parse_query(variants[0]))}


def test_marks_map_back_to_the_original_accented_text():
    title = "Applying Guidance … Tuomas Kynkäänniemi and Ä Tübingen"
    ms = matchers_for(parse_query("kynkaanniemi TUBINGEN"))
    assert [title[s:e] for s, e in mark(title, ms)] == ["Kynkäänniemi", "Tübingen"]


def test_coverage_ignores_case_and_accents():
    pq = parse_query("tubingen KARRAS")
    texts = ["Universität Tübingen", "Tero Karras"]
    assert Coverage(pq.units, texts).covered(texts) == {0, 1}


# ── Lucene query strings ──────────────────────────────────────────────────────

def test_lucene_any_and_all():
    pq = parse_query("scroe based")
    assert lucene_any(pq) == '(scroe^2 OR scroe* OR scroe~1) OR (based^2 OR based* OR based~1) OR "scroe based"^3'
    assert lucene_all(pq) == '+(scroe^2 OR scroe* OR scroe~1) +(based^2 OR based* OR based~1) "scroe based"^2'
    assert on_fields("x", {"title": 4, "abstract": 1}) == "title:(x)^4 OR abstract:(x)"
    assert lucene_prefix_all(["tero", "kar"]) == "+tero* +kar*"
    assert lucene_prefix_all(["models", "of", "the"]) == "+models* the*"


def test_hostile_input_never_reaches_lucene_unescaped():
    pq = parse_query('a:b -c (d) [e] {f} g~ h^2 \\ / && || ! ? "unbalanced')
    body = lucene_any(pq)
    # Only our own syntax remains: no field colons, no bare minus, balanced parentheses.
    assert ":" not in body and " -" not in body and "[" not in body and "{" not in body
    assert body.count("(") == body.count(")")
    assert body.count('"') % 2 == 0


# ── matching ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b, ok", [
    ("score", "scroe", True),       # swap
    ("modeling", "modelling", True),
    ("diffusion", "difusion", True),
    ("abc", "abd", True),
    ("abc", "cab", False),
    ("kitten", "sitting", False),
    ("same", "same", True),
])
def test_within_one_edit(a, b, ok):
    assert within_one_edit(a, b) is ok


def test_unit_matcher_prefix_fuzzy_and_word_boundaries():
    m = UnitMatcher(parse_query("diffus*").units[0])
    assert m.found("Denoising Diffusion Probabilistic Models")
    assert not m.found("rediffusion")  # prefix only at a word start
    fuzzy = UnitMatcher(parse_query("scroe").units[0])
    assert fuzzy.found("Score-Based Generative Modeling")
    exact = UnitMatcher(parse_query('"EDM"').units[0])
    assert exact.found("the EDM sampler") and not exact.found("EDMs")


def test_coverage_uses_prefix_fuzzy_and_phrases():
    pq = parse_query('scroe "generative modeling" diffus')
    texts = ["Score-Based Generative Modeling through SDEs", "diffusions everywhere"]
    cov = Coverage(pq.units, texts)
    assert cov.covered(texts) == {0, 1, 2}
    assert cov.covered(["generative and modeling apart"]) == set()


def test_mark_and_snippet_offsets_point_at_the_matched_words():
    pq = parse_query("flow matching")
    ms = matchers_for(pq)
    title = "Flow Matching for Generative Modeling"
    assert [title[s:e] for s, e in mark(title, ms)] == ["Flow", "Matching"]
    long = ("x " * 400) + "we train with flow matching objectives. " + ("y " * 400)
    sn = snippet(long, ms)
    assert sn["text"].startswith("…") and sn["text"].endswith("…")
    assert [sn["text"][s:e].lower() for s, e in sn["marks"]] == ["flow", "matching"]
    assert snippet("nothing relevant here", ms) is None


def test_snippet_prefers_the_window_with_most_distinct_units():
    ms = matchers_for(parse_query("antibody docking"))
    text = "antibody " + "filler " * 80 + "antibody docking benchmark " + "filler " * 80
    sn = snippet(text, ms, width=120)
    assert "antibody docking" in sn["text"]


def test_snippet_strips_markdown_and_marks_cut_texts():
    ms = matchers_for(parse_query("contribution"))
    sn = snippet("## Contribution\n**Main** contribution here", ms, cut_before=True)
    assert "#" not in sn["text"] and "**" not in sn["text"]
    assert sn["text"].startswith("…")


def test_needles_most_specific_first():
    assert needles(parse_query("flow matching ode")) == ["flow matching ode", "matching", "flow", "ode"]


# ── ranking ───────────────────────────────────────────────────────────────────

def _cand(pid, title, **kw):
    c = Candidate(id=pid, title=title)
    for source, score in kw.pop("scores", {}).items():
        c.add(source, score)
    for fld, texts in kw.pop("texts", {}).items():
        for t in texts:
            c.add(fld if fld not in ("abstract", "summary") else "paper", 1.0, fld, t)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_title_match_outranks_abstract_only_match():
    pq = parse_query("flow matching")
    title_hit = _cand("a", "Flow Matching for Generative Modeling", scores={"paper": 8.0})
    abstract_hit = _cand("b", "Neural ODEs", scores={"paper": 3.0},
                         texts={"abstract": ["we compare with flow matching"]})
    cands = [abstract_hit, title_hit]
    score_candidates(cands, pq)
    ranked, relaxed = rank(cands)
    assert [c.id for c in ranked] == ["a", "b"] and not relaxed
    assert title_hit.fields == ["title"]
    assert abstract_hit.fields == ["abstract"]


def test_partial_matches_drop_unless_nothing_covers_everything():
    pq = parse_query("antibody docking")
    full = _cand("full", "Antibody docking benchmark", scores={"paper": 5.0})
    half = _cand("half", "Antibody structures", scores={"paper": 9.0})
    score_candidates([full, half], pq)
    ranked, relaxed = rank([full, half])
    assert [c.id for c in ranked] == ["full"] and not relaxed
    ranked, relaxed = rank([half])
    assert [c.id for c in ranked] == ["half"] and relaxed


def test_cross_source_coverage_author_plus_title():
    pq = parse_query("karras diffusion")
    edm = _cand("edm", "Elucidating the Design Space of Diffusion-Based Generative Models",
                scores={"paper": 4.0}, texts={"author": ["Tero Karras"]})
    other = _cand("other", "Diffusion models beat GANs", scores={"paper": 6.0})
    score_candidates([edm, other], pq)
    ranked, _ = rank([edm, other])
    assert [c.id for c in ranked] == ["edm"]
    assert edm.fields == ["title", "author"]


def test_fulltext_hit_covers_every_unit_and_references_rank_lower():
    pq = parse_query("antibody docking")
    ft = _cand("ft", "Some paper", scores={"fulltext": 2.0})
    ref = _cand("ref", "Antibody docking", scores={"paper": 5.0}, ref=True)
    lib = _cand("lib", "Antibody docking", scores={"paper": 5.0})
    score_candidates([ft, ref, lib], pq)
    assert ft.coverage == 1.0 and ft.fields == ["fulltext"]
    assert lib.score > ref.score


def test_papers_by_an_author_rank_above_papers_mentioning_the_name():
    pq = parse_query("Karras")
    by = _cand("by", "eDiff-I", scores={"author": 2.0}, texts={"author": ["Tero Karras"]})
    cites = _cand("cites", "On Memorization", scores={"paper": 6.0, "highlight": 4.0},
                  texts={"summary": ["uses EDM (Karras et al., 2022)"], "highlight": ["Karras et al."]})
    score_candidates([by, cites], pq)
    assert by.score > cites.score


def test_library_citations_lift_foundational_papers():
    pq = parse_query("flow matching")
    canon = _cand("canon", "Flow Matching for Generative Modeling", scores={"paper": 5.0}, cited=16)
    other = _cand("other", "Discrete Flow Matching", scores={"paper": 5.2})
    score_candidates([canon, other], pq)
    assert canon.score > other.score


def test_word_number_terms_match_the_spaced_spelling():
    pq = parse_query("alphafold3")
    assert pq.units[0].alt == ("alphafold", "3")
    assert '"alphafold 3"' in lucene_any(pq)
    title = "Accurate structure prediction with AlphaFold 3"
    assert Coverage(pq.units, [title]).covered([title]) == {0}
    assert [title[s:e] for s, e in mark(title, matchers_for(pq))] == ["AlphaFold 3"]


def test_exact_title_bonus():
    pq = parse_query("Discrete Flow Matching")
    exact = _cand("e", "Discrete Flow Matching", scores={"paper": 5.0})
    longer = _cand("l", "Discrete Flow Matching for Graphs and Text", scores={"paper": 5.0})
    score_candidates([exact, longer], pq)
    assert exact.score > longer.score


def test_legacy_matched_in():
    assert legacy_matched_in(["title", "abstract", "note"]) == "note+paper"
    assert legacy_matched_in(["author"]) == "paper"
    assert legacy_matched_in(["fulltext", "claim"]) == "claim+fulltext"
    assert legacy_matched_in([]) == "paper"


def test_rrf_and_fuse():
    scores = rrf({"lexical": ["a", "b"], "semantic": ["b", "c"]}, {"lexical": 1.0, "semantic": 1.0}, k=10)
    assert scores["b"] > scores["a"] > scores["c"]
    lex = [_cand("a", "A"), _cand("b", "B")]
    for c in lex:
        c.fields = ["title"]
    sem = [_cand("b", "B", semantic=0.8), _cand("c", "C", semantic=0.7)]
    out = fuse(lex, sem, {"lexical": 1.0, "semantic": 1.0})
    assert [c.id for c in out] == ["b", "a", "c"]
    assert out[0].fields == ["title", "semantic"] and out[2].fields == ["semantic"]


def test_hybrid_weights():
    assert hybrid_weights(2, False, 0.85) == {"lexical": 1.0, "semantic": 0.7}
    assert hybrid_weights(7, False, 0.8)["lexical"] == 0.4
    assert hybrid_weights(2, True, 0.8)["lexical"] == pytest.approx(0.6)
    assert hybrid_weights(1, False, 0.6)["semantic"] == 0.0
    assert hybrid_weights(1, False, None)["semantic"] == 0.7


def test_sort_candidates():
    cs = [Candidate(id="a", title="b", year=2020, created_at="2026-01-02"),
          Candidate(id="b", title="A", year=2024, created_at="2026-01-01")]
    assert [c.id for c in sort_candidates(cs, "year_desc")] == ["b", "a"]
    assert [c.id for c in sort_candidates(cs, "date_desc")] == ["a", "b"]
    assert [c.id for c in sort_candidates(cs, "title_asc")] == ["b", "a"]
    assert sort_candidates(cs, "relevance") is cs


def test_rank_entities_groups_and_orders():
    rows = [
        {"kind": "Person", "id": "1", "name": "Tero Karras", "papers": 3, "score": 2.0},
        {"kind": "Person", "id": "2", "name": "Karras Doe", "papers": 0, "score": 3.0},
        {"kind": "Topic", "id": "3", "name": "Diffusion Models", "papers": 40, "score": 1.0},
        {"kind": "Project", "id": "4", "name": "Thesis", "papers": 5, "score": 1.0},
    ]
    out = rank_entities(rows, per_kind=5)
    assert [a["name"] for a in out["authors"]] == ["Tero Karras", "Karras Doe"]
    assert out["topics"][0]["papers"] == 40 and out["projects"][0]["id"] == "4"
    assert out["tags"] == []


# ── semantic helpers ──────────────────────────────────────────────────────────

def test_paper_text_and_cut():
    assert semantic.paper_text("T", "", "## Summary\n**bold** body") == "T\nSummary bold body"
    assert semantic.paper_text("T", "abs", "sum") == "T\nabs"
    assert semantic.text_hash("x") == semantic.text_hash("x") != semantic.text_hash("y")

    class H:
        def __init__(self, s):
            self.semantic = s
    hits = [H(0.9), H(0.8), H(0.75), H(0.6)]
    assert [h.semantic for h in semantic.cut(hits, min_sim=0.62, rel_sim=0.12)] == [0.9, 0.8]
    assert semantic.cut([], 0.5, 0.1) == []


def test_semantic_query_is_empty_without_a_loaded_model(monkeypatch):
    import services.conferences.embedder as emb
    monkeypatch.setattr(emb, "ready", lambda: False)
    assert semantic.query("diffusion") == []


def test_semantic_query_ranks_by_cosine(monkeypatch):
    import services.conferences.embedder as emb
    monkeypatch.setattr(semantic, "enabled", lambda: True)
    monkeypatch.setattr(emb, "ready", lambda: True)
    from services import vectorstore
    from services.vectorstore import model_config

    dim = model_config.dim()
    v = np.zeros(dim, dtype=np.float32)
    v[0] = 1.0
    monkeypatch.setattr(emb, "embed_query", lambda q: v)
    e = np.zeros((3, dim), dtype=np.float32)
    e[0, 0], e[0, 1] = 0.6, 0.8
    e[1, 0], e[1, 1] = 0.9, float(np.sqrt(1 - 0.81))
    e[2, 1] = 1.0
    vectorstore.get_store("library").upsert(["a", "b", "c"], e)
    assert [pid for pid, _ in semantic.query("x", k=2)] == ["b", "a"]


# ── engine: merge, pagination, visibility, failures (scripted driver) ────────

class _Session:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.driver.queries.append((query, params))
        m = re.search(r"/\*search:(\w+)\*/", query)
        if m:
            src = m.group(1)
            if src in self.driver.fail:
                raise RuntimeError(f"index {src} is not online")
            return self.driver.rows.get(src, [])
        if "AS authors" in query:
            return [{"id": pid, "p": {"id": pid, "title": self.driver.titles[pid]}, "added_by": None,
                     "added_by_color": None, "authors": ["A. Author"], "text_chars": 0,
                     "has_note": False, "highlight_count": 0, "projects": []}
                    for pid in params["ids"] if pid in self.driver.titles]
        return []


class _Driver:
    def __init__(self, rows, fail=()):
        self.rows, self.fail, self.queries = rows, set(fail), []
        self.titles = {r["id"]: r["title"] for src in rows.values() for r in src}

    def session(self):
        return _Session(self)


def _row(pid, title, score=1.0, **extra):
    return {"id": pid, "title": title, "year": 2024, "created_at": "2026-01-01", "ref": False,
            "score": score, **extra}


def test_engine_merges_sources_and_reports_where_it_matched(monkeypatch):
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "niklas")
    driver = _Driver({
        "paper": [_row("p1", "RoseTTAFold denoisers", 3.0, abstract=None, summary=None),
                  _row("p2", "Protein design", 1.0, abstract="uses RoseTTAFold", summary=None)],
        "note": [_row("p2", "Protein design", 5.0, text="Starts from RoseTTAFold")],
    })
    res = search(driver, "RoseTTAFold", Filters(), limit=10)
    by = {r["id"]: r for r in res["results"]}
    assert res["total"] == 2 and res["mode"] == "lexical"
    assert by["p2"]["matched_in"] == "note+paper"
    assert by["p2"]["matched_fields"] == ["abstract", "note"]
    assert by["p2"]["snippets"][0]["field"] == "note"
    assert by["p1"]["title_marks"] == [[0, 11]]
    assert by["p1"]["authors"] == ["A. Author"]


def test_engine_paginates_after_merging(monkeypatch):
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "niklas")
    driver = _Driver({"paper": [_row(f"p{i}", f"Diffusion {i}", 10 - i, abstract=None, summary=None)
                                for i in range(5)]})
    page = search(driver, "diffusion", Filters(), skip=2, limit=2)
    assert page["total"] == 5
    assert [r["id"] for r in page["results"]] == ["p2", "p3"]


def test_engine_survives_a_failing_source(monkeypatch):
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "niklas")
    driver = _Driver({"paper": [_row("p1", "Diffusion", abstract=None, summary=None)]}, fail={"fulltext"})
    res = search(driver, "diffusion", Filters())
    assert [r["id"] for r in res["results"]] == ["p1"]
    assert res["failed_sources"] == ["fulltext"]


def test_engine_applies_visibility_to_every_source(monkeypatch):
    monkeypatch.setattr("db.queries.visibility.get_request_user", lambda: "carol")
    driver = _Driver({})
    search(driver, "diffusion", Filters())
    source_queries = [(q, p) for q, p in driver.queries if "/*search:" in q]
    assert len(source_queries) == 7
    for q, p in source_queries:
        assert "MEMBER_OF" in q and p["vis_user"] == "carol"


def test_filter_clause_parameters():
    where, params = filter_clause(Filters(tag="t", year_min=2020, include_references=False))
    assert params["tag"] == "t" and params["year_min"] == 2020 and params["refs"] is False
    assert "from-references" in where


def test_filter_clause_compares_names_case_insensitively():
    where, _ = filter_clause(Filters(tag="Foundational", topic="diffusion models", venue="neurips"))
    assert "toLower(_t.name) = toLower($tag)" in where
    assert "toLower(_tp.name) = toLower($topic)" in where
    assert "toLower(p.venue) = toLower($venue)" in where
