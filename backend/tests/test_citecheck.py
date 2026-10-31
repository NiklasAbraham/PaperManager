"""citecheck (identifier resolution) and its use on extracted references. No network: the
resolvers are patched."""
from unittest.mock import patch

from services import citecheck as cc
import pytest

from services.references import vet_reference_ids


@pytest.fixture(autouse=True)
def _id_check_on(monkeypatch):
    monkeypatch.setenv("REFERENCE_ID_CHECK", "1")


def test_classify_routes_arxiv_dois_and_links():
    assert cc.classify("doi", "https://doi.org/10.48550/arXiv.2206.00364") == ("arxiv", "2206.00364")
    assert cc.classify("url", "https://arxiv.org/abs/2206.00364v2") == ("arxiv", "2206.00364")
    assert cc.classify("url", "https://doi.org/10.1038/s41586-024-07487-w") == ("doi", "10.1038/s41586-024-07487-w")
    assert cc.classify("doi", "doi:10.1021/ct300112v.") == ("doi", "10.1021/ct300112v")


def test_title_similarity():
    t = "Accurate structure prediction of biomolecular interactions with AlphaFold 3"
    assert cc.title_similarity(t, "Accurate structure prediction of biomolecular interactions with {AlphaFold} 3") == 1.0
    assert cc.title_similarity("GPTQ", t) < cc.TITLE_MIN
    # subtitle added or dropped still matches
    assert cc.title_similarity("Boltz-2", "Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction") < 1
    assert cc.title_similarity("Elucidating the Design Space of Diffusion-Based Generative Models",
                               "Elucidating the design space of diffusion-based generative models: an extended study") >= cc.TITLE_MIN


def _fake_doi(doi, timeout):
    known = {"10.1/real": "A real paper about proteins"}
    if doi in known:
        return cc.Result("doi", doi, cc.OK, "", known[doi])
    return cc.Result("doi", doi, cc.DEAD, "DOI not registered")


def _fake_arxiv(ids, timeout):
    known = {"2206.00364": "Elucidating the Design Space of Diffusion-Based Generative Models"}
    return {i: cc.Result("arxiv", i, cc.OK, "", known[i]) if i in known else cc.Result("arxiv", i, cc.DEAD)
            for i in ids}


def test_check_items_statuses_and_dedup():
    items = [
        cc.Item("doi", "10.1/real", title="A real paper about proteins"),
        cc.Item("doi", "10.1/real", title="Something else entirely different here"),
        cc.Item("doi", "10.1/fake", title="x"),
        cc.Item("arxiv", "2206.00364v1", title="Elucidating the Design Space of Diffusion-Based Generative Models"),
        cc.Item("arxiv", "not-an-id"),
    ]
    with patch.object(cc, "check_doi", side_effect=_fake_doi) as d, \
         patch.object(cc, "check_arxiv_batch", side_effect=_fake_arxiv):
        res = cc.check_items(items)
    assert d.call_count == 2                       # duplicate DOI fetched once
    assert [r.status for r in res] == [cc.OK, cc.MISMATCH, cc.DEAD, cc.OK, cc.DEAD]


def test_vet_drops_invented_ids_from_ai_refs():
    refs = [
        {"title": "A real paper about proteins", "doi": "10.1/real", "arxiv_id": None},
        {"title": "Elucidating the Design Space of Diffusion-Based Generative Models", "doi": None, "arxiv_id": "2206.00365"},
        {"title": "Some other work on folding", "doi": "10.1/real", "arxiv_id": None},
        {"title": "No ids at all", "doi": None, "arxiv_id": None},
    ]
    with patch.object(cc, "check_doi", side_effect=_fake_doi), \
         patch.object(cc, "check_arxiv_batch", side_effect=_fake_arxiv):
        out = vet_reference_ids(refs, source="ai")
    assert out[0]["doi"] == "10.1/real" and out[0]["id_check"] == "ok"
    assert out[1]["arxiv_id"] is None and out[1]["id_check"] == "dropped:arxiv:dead"
    assert out[2]["doi"] is None and out[2]["id_check"] == "dropped:doi:mismatch"
    assert "id_check" not in out[3]


def test_vet_parser_refs_fix_author_fragments_and_drop_stray_ids():
    refs = [{"title": "Chen, H. T. Nguyen, N. Nguyen, D. Cipriano", "doi": "10.1/real", "arxiv_id": None},
            {"title": "Building a large annotated corpus of English", "doi": "10.1/real", "arxiv_id": None}]
    with patch.object(cc, "check_doi", side_effect=_fake_doi):
        out = vet_reference_ids(refs, source="parser")
    assert out[0]["doi"] == "10.1/real"
    assert out[0]["title"] == "A real paper about proteins"
    assert out[0]["id_check"] == "title_from_doi"
    assert out[1]["doi"] is None and out[1]["id_check"] == "dropped:doi:mismatch"
    assert out[1]["title"] == "Building a large annotated corpus of English"


def test_vet_keeps_ids_on_network_errors(monkeypatch):
    refs = [{"title": "T", "doi": "10.1/x", "arxiv_id": None}]
    with patch.object(cc, "check_doi", return_value=cc.Result("doi", "10.1/x", cc.ERROR, "network")):
        out = vet_reference_ids(refs)
    assert out[0]["doi"] == "10.1/x" and out[0]["id_check"] == "unchecked"


def test_vet_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("REFERENCE_ID_CHECK", "0")
    refs = [{"title": "T", "doi": "10.1/fake"}]
    assert vet_reference_ids(refs) == [{"title": "T", "doi": "10.1/fake"}]


def test_bib_and_text_extraction(tmp_path):
    bib = tmp_path / "x.bib"
    bib.write_text("@article{k, title={{AlphaFold} 3}, doi={10.1038/abc}, eprint={2206.00364}, archivePrefix={arXiv}}\n")
    kinds = {(i.kind, i.ident) for i in cc.items_from_bib(bib)}
    assert kinds == {("doi", "10.1038/abc"), ("arxiv", "2206.00364")}
    md = tmp_path / "x.md"
    md.write_text("See https://example.org/a. and doi 10.1021/ct300112v, arXiv:2301.07041\n")
    kinds = {(i.kind, i.ident) for i in cc.items_from_text(md)}
    assert ("url", "https://example.org/a") in kinds and ("doi", "10.1021/ct300112v,") not in kinds
    assert ("arxiv", "2301.07041") in kinds


def test_renamed_versions_keep_their_name():
    assert cc.title_similarity("Controlnet-xs: Designing an efficient and effective architecture",
                               "ControlNet-XS: Rethinking the Control of Text-to-Image Diffusion Models") >= cc.TITLE_MIN
    assert cc.title_similarity("Shadowdiffusion: Diffusion-based shadow removal",
                               "DeS3: Adaptive Attention-driven Self and Soft Shadow Removal") < cc.TITLE_MIN
    assert cc.title_similarity("Survey: one thing", "Survey: another thing entirely different") < cc.TITLE_MIN
    assert cc.normalise_doi("https://doi.org/10.1101/2025.09.03.25334985v1") == "10.1101/2025.09.03.25334985"
