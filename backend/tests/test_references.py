"""
Tests for reference-list extraction (services/references.py).

The text fixtures are trimmed from real PDF extractions in the library: an ICLR
author-year list, a Nature numbered list with a Methods list, letter-spaced
justified lines, hyperref back-references, and IEEE quoted titles.
"""
from unittest.mock import patch, MagicMock

import pytest

from services import references as R
from services.references import (
    _extract_references_from_text,
    _get_ref_sections,
    _parse_ref_json,
    _s2_paper_id,
    extract_references,
)

AUTHOR_YEAR = """Some conclusion text.
REFERENCES
Michael S Albergo and Eric Vanden-Eijnden. Building normalizing flows with stochastic inter-
polants. arXiv preprint arXiv:2209.15571, 2022.
Dario Amodei, Danny Hernandez, Girish Sastry, Jack Clark, Greg Brockman, and Ilya
Sutskever. Ai and compute. https://openai.com/blog/ai-and-compute/, 2018.
Ricky T. Q. Chen, Yulia Rubanova, Jesse Bettencourt, and David K Duvenaud. Neural ordinary
differential equations. Advances in neural information processing systems, 31, 2018.
Prafulla Dhariwal and Alexander Quinn Nichol. Diffusion models beat GANs on image synthesis.
In A. Beygelzimer, Y . Dauphin, P. Liang, and J. Wortman Vaughan (eds.), Advances in Neu-
ral Information Processing Systems, 2021. URL https://openreview.net/forum?id=AAWuCvzaVt.
Levente Kocsis and Csaba Szepesvari. Bandit based monte-carlo planning. InEuropean conference
on machine learning, pp. 282-293. Springer, 2006.
A PROOFS OF THEOREMS
1. First step of a proof that is not a reference.
2. Second step of the proof.
3. Third step of the proof.
"""

NATURE = """Results text.
References
1. Jumper, J. et al. Highly accurate protein structure prediction with AlphaFold. Nature 596,
583-589 (2021).
2. Romero, P. A. & Arnold, F. H. Exploring protein fitness landscapes
by directed evolution.Nat Rev Mol Cell Bio 10, 866-876 (2009).
3. Smith, J. M. Natural selection and the concept of a protein space. Nature 225, 563-564 (1970).
Online content
Any methods, additional references, Nature Portfolio reporting summaries are available.
Methods
We trained the model on 2021 data. 1 2 3 are not references.
References
4. Packer, M. S. & Liu, D. R. Methods for the directed evolution of proteins. Nat. Rev. Genet. 16, 379-394 (2015).
5. Hie, B. L. & Yang, K. K. Adaptive machine learning for protein
engineering. Curr. Opin. Struct. Biol. 72, 145-152 (2022).
6. Wu, Z., Kan, S. B. J., Lewis, R. D., Wittmann, B. J. & Arnold, F. H. Machine learning-assisted
directed protein evolution with combinatorial libraries. Proc. Natl. Acad. Sci. 116, 8852-8858 (2019).
"""


class TestSections:
    def test_collects_main_and_methods_lists(self):
        sections = _get_ref_sections(NATURE)
        assert len(sections) == 2
        assert "Jumper" in sections[0] and "Online content" not in sections[0]
        assert "Packer" in sections[1]

    def test_appendix_heading_ends_section(self):
        (section,) = _get_ref_sections(AUTHOR_YEAR)
        assert "Kocsis" in section
        assert "First step of a proof" not in section

    def test_header_variants(self):
        for header in ["## References", "7 References", "REFERENCES", "References515", "References XI", "Bibliography"]:
            text = f"Body.\n{header}\n[1] A. Author, \"A long enough title here,\" Venue, 2020.\n"
            assert _get_ref_sections(text), header


class TestParser:
    def test_author_year_entries(self):
        refs = _extract_references_from_text(AUTHOR_YEAR)
        titles = [r["title"] for r in refs]
        assert titles == [
            "Building normalizing flows with stochastic interpolants",
            "Ai and compute",
            "Neural ordinary differential equations",
            "Diffusion models beat GANs on image synthesis",
            "Bandit based monte-carlo planning",
        ]
        assert refs[0]["authors"] == ["Michael S Albergo", "Eric Vanden-Eijnden"]
        assert refs[0]["arxiv_id"] == "2209.15571"
        assert refs[0]["year"] == 2022
        assert refs[4]["year"] == 2006

    def test_numbered_nature_style_title_after_initials(self):
        refs = _extract_references_from_text(NATURE)
        titles = [r["title"] for r in refs]
        assert titles[:3] == [
            "Highly accurate protein structure prediction with AlphaFold",
            "Exploring protein fitness landscapes by directed evolution",
            "Natural selection and the concept of a protein space",
        ]
        assert len(refs) == 6
        assert refs[1]["authors"] == ["Romero, P. A", "Arnold, F. H"]
        assert refs[1]["year"] == 2009

    def test_kingma_and_welling_is_not_a_title_boundary(self):
        text = "Body.\nReferences\n[1] D. P. Kingma and M. Welling. Auto-encoding variational bayes. ICLR, 2014.\n" \
               "[2] A. Vaswani, N. Shazeer. Attention is all you need. NeurIPS, 2017.\n" \
               "[3] I. Goodfellow et al. Generative adversarial nets. NeurIPS, 2014.\n"
        refs = _extract_references_from_text(text)
        assert [r["title"] for r in refs] == [
            "Auto-encoding variational bayes",
            "Attention is all you need",
            "Generative adversarial nets",
        ]

    def test_ieee_quoted_titles(self):
        text = (
            "Body.\nReferences\n"
            "[1] Y. Bengio, “Learning deep architectures for ai,” Foundations and trends, 2009.\n"
            "[2] P. Dayan, G. E. Hinton, R. M. Neal, and R. S. Zemel, “The helmholtz machine,” Neural computation, 1995.\n"
            "[3] I. Goodfellow, “Generative adversarial nets,” in NeurIPS, 2014.\n"
        )
        refs = _extract_references_from_text(text)
        assert [r["title"] for r in refs] == [
            "Learning deep architectures for ai",
            "The helmholtz machine",
            "Generative adversarial nets",
        ]

    def test_letter_spaced_numbers_keep_the_sequence(self):
        text = (
            "Body.\nReferences\n"
            "1. Alpha, A. First paper title about proteins. Nature 1, 1-2 (2020).\n"
            "2. Beta, B. Second paper title about proteins. Nature 1, 1-2 (2020).\n"
            "1 2 . G a m m a ,G . Third paper.\n"
            "3. Gamma, G. Third paper title about proteins. Nature 1, 1-2 (2020).\n"
            "4. Delta, D. Fourth paper title about proteins. Nature 1, 1-2 (2020).\n"
        )
        refs = _extract_references_from_text(text)
        assert len(refs) == 4
        lines = R._clean_lines("1 2 . W u ,Z .\n")
        assert lines == ["12. W u ,Z ."]

    def test_hyperref_backrefs_and_running_headers(self):
        header = "Published as a conference paper at ICLR 2026"
        text = (
            "Body.\nREFERENCES\n"
            "Josh Abramson and Jonas Adler. Accurate structure prediction of biomolecular\n"
            "interactions with alphafold 3. Nature, 630:493-500, 2024. 1, 25, 27,\n"
            "29, 50\n"
            f"{header}\n"
            "Woody Ahern and Jason Yim. Atom level enzyme active site scaffolding\n"
            "using rfdiffusion2. bioRxiv, 2025. 2, 6\n"
            f"{header}\n"
            "Rebecca F. Alford and Jeffrey J. Gray. The rosetta all-atom energy function for\n"
            "macromolecular modeling and design. JCTC, 13(6):3031-3048, 2017. 6, 25, 50\n"
            f"{header}\n"
        )
        refs = _extract_references_from_text(text)
        assert [r["title"] for r in refs] == [
            "Accurate structure prediction of biomolecular interactions with alphafold 3",
            "Atom level enzyme active site scaffolding using rfdiffusion2",
            "The rosetta all-atom energy function for macromolecular modeling and design",
        ]
        assert [r["year"] for r in refs] == [2024, 2025, 2017]

    def test_headerless_numbered_tail(self):
        body = "Intro text.\n" * 200
        refs_text = "".join(f"{i}. Author{i}, A. Title number {i} about something. J. Biol. 1, 2 (2020).\n" for i in range(1, 15))
        refs = _extract_references_from_text(body + refs_text)
        assert len(refs) == 14

    def test_short_headerless_list_is_ignored(self):
        text = "Intro.\n" * 50 + "1. Do this.\n2. Then that.\n3. Finally this.\n"
        assert _extract_references_from_text(text) == []


class TestLlmJson:
    def test_object_wrapper(self):
        raw = '{"references": [{"title": "A", "authors": ["X"], "year": "2020"}]}'
        assert _parse_ref_json(raw) == [{"title": "A", "authors": ["X"], "year": 2020, "doi": None, "arxiv_id": None}]

    def test_bare_array_with_fences(self):
        raw = '```json\n[{"title": "B", "authors": "Y", "year": null}]\n```'
        assert _parse_ref_json(raw)[0]["authors"] == ["Y"]

    def test_garbage(self):
        assert _parse_ref_json("not json") == []

    def test_chunks_cover_whole_section(self):
        section = "".join(f"[{i}] Author {i}. A title for reference {i}. Venue, 2020.\n" for i in range(1, 400))
        chunks = R._chunk_section(section)
        assert len(chunks) > 1
        assert all(len(c) <= R._AI_CHUNK_CHARS for c in chunks)
        joined = "\n".join(chunks)
        assert "reference 1." in joined and "reference 399." in joined

    def test_ai_merges_and_dedupes_chunks(self):
        section = "".join(f"[{i}] Author {i}. A title for reference {i}. Venue, 2020.\n" for i in range(1, 400))
        calls = []

        def fake(text):
            calls.append(text)
            return [{"title": "Shared", "authors": [], "year": None, "doi": None, "arxiv_id": None},
                    {"title": f"T{len(calls)}", "authors": [], "year": None, "doi": None, "arxiv_id": None}]

        with patch.object(R, "_litellm_extract", side_effect=fake):
            refs = R._extract_references_with_ai(section)
        assert len(calls) > 1
        assert len(refs) == len(calls) + 1      # one "Shared" + one unique per chunk

    def test_litellm_failure_falls_back_to_claude(self):
        section = "[1] Author. A title for the reference. Venue, 2020.\n" * 3
        claude_refs = [{"title": "From Claude", "authors": [], "year": None, "doi": None, "arxiv_id": None}]
        with patch.object(R, "_litellm_extract", side_effect=TimeoutError("slow")), \
             patch.object(R, "_claude_extract", return_value=claude_refs) as claude:
            refs = R._extract_references_with_ai(section)
        assert claude.called
        assert refs == claude_refs


class TestSemanticScholar:
    def test_paper_id_forms(self):
        assert _s2_paper_id("10.48550/arXiv.2604.05181") == "ArXiv:2604.05181"
        assert _s2_paper_id("arXiv:2210.02747") == "ArXiv:2210.02747"
        assert _s2_paper_id("2210.02747") == "ArXiv:2210.02747"
        assert _s2_paper_id("10.1038/s41586-024-07487-w") == "DOI:10.1038/s41586-024-07487-w"

    @staticmethod
    def _resp(status, payload=None):
        r = MagicMock()
        r.status_code = status
        r.headers = {}
        r.json.return_value = payload or {}
        return r

    def test_retries_on_429_then_paginates(self):
        page1 = {"data": [{"citedPaper": {"title": f"P{i}", "externalIds": {}}} for i in range(1000)], "next": 1000}
        page2 = {"data": [{"citedPaper": {"title": "Last", "authors": [{"name": "A"}], "year": 2020,
                                          "externalIds": {"DOI": "10.1/x", "ArXiv": "2001.00001"}}}]}
        responses = [self._resp(429), self._resp(200, page1), self._resp(200, page2)]
        with patch.object(R.httpx, "get", side_effect=responses) as get, patch.object(R.time, "sleep"):
            refs = R._fetch_s2_references("arXiv:2210.02747")
        assert get.call_count == 3
        assert get.call_args_list[2].kwargs["params"]["offset"] == 1000
        assert len(refs) == 1001
        assert refs[-1] == {"title": "Last", "authors": ["A"], "year": 2020, "doi": "10.1/x", "arxiv_id": "2001.00001"}

    def test_gives_up_after_retries(self):
        with patch.object(R.httpx, "get", return_value=self._resp(429)) as get, patch.object(R.time, "sleep"):
            assert R._fetch_s2_references("10.1/x") is None
        assert get.call_count == len(R._S2_RETRY_DELAYS) + 1

    def test_404_is_not_retried(self):
        with patch.object(R.httpx, "get", return_value=self._resp(404)) as get:
            assert R._fetch_s2_references("10.1/x") is None
        assert get.call_count == 1


class TestCombination:
    def _refs(self, n, prefix):
        return [{"title": f"{prefix} {i}", "authors": [], "year": None, "doi": None, "arxiv_id": None} for i in range(n)]

    def test_incomplete_s2_falls_through_to_ai(self):
        """S2 returning 3 of ~6 parsed references is not accepted."""
        with patch.object(R, "_fetch_s2_references", return_value=self._refs(3, "S2")), \
             patch.object(R, "_extract_references_with_ai", return_value=self._refs(6, "AI")):
            refs = extract_references(NATURE, doi="10.1/x")
        assert refs[0]["title"] == "AI 0"

    def test_complete_s2_skips_ai(self):
        with patch.object(R, "_fetch_s2_references", return_value=self._refs(6, "S2")), \
             patch.object(R, "_extract_references_with_ai") as ai:
            refs = extract_references(NATURE, doi="10.1/x")
        assert not ai.called
        assert len(refs) == 6

    def test_parser_wins_when_others_fail(self):
        with patch.object(R, "_fetch_s2_references", return_value=None), \
             patch.object(R, "_extract_references_with_ai", return_value=[]):
            refs = extract_references(AUTHOR_YEAR, doi=None)
        assert len(refs) == 5

    def test_no_text_returns_s2(self):
        with patch.object(R, "_fetch_s2_references", return_value=self._refs(2, "S2")):
            assert len(extract_references("", doi="10.1/x")) == 2
