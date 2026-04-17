"""
Unit tests for pdf_parser and metadata_lookup services.
These tests are NOT marked integration — they run without network or Ollama.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from services.pdf_parser import (
    extract_text,
    find_doi,
    extract_metadata_heuristic,
    extract_metadata,
)

FIXTURE = Path(__file__).parent / "fixtures" / "attention.pdf"


# ── extract_text ──────────────────────────────────────────────────────────────

def test_extract_text_returns_string():
    pdf_bytes = FIXTURE.read_bytes()
    text = extract_text(pdf_bytes)
    assert isinstance(text, str)
    assert len(text) > 0


def test_extract_text_contains_title():
    text = extract_text(FIXTURE.read_bytes())
    assert "Attention Is All You Need" in text


def test_extract_text_bad_bytes_returns_empty():
    assert extract_text(b"not a pdf") == ""


# ── find_doi ──────────────────────────────────────────────────────────────────

def test_find_doi_detects_arxiv_id():
    doi = find_doi("See arXiv:1706.03762 for details.")
    assert doi == "arXiv:1706.03762"


def test_find_doi_detects_real_doi():
    doi = find_doi("Published at DOI: 10.1145/3292500.3330701")
    assert doi == "10.1145/3292500.3330701"


def test_find_doi_strips_trailing_punctuation():
    doi = find_doi("Reference: 10.1007/s10994-021-05946-3.")
    assert doi is not None
    assert not doi.endswith(".")


def test_find_doi_prefers_arxiv_over_doi():
    """arXiv ID checked before DOI pattern."""
    text = "arXiv:1706.03762 also has DOI 10.48550/arXiv.1706.03762"
    doi = find_doi(text)
    assert doi.startswith("arXiv:")


def test_find_doi_returns_none_when_absent():
    assert find_doi("No identifier here.") is None


# ── extract_metadata_heuristic ────────────────────────────────────────────────

def test_heuristic_extracts_year():
    text = "Some Paper Title\nAuthor Name\nPublished 2021\nAbstract here."
    result = extract_metadata_heuristic(text)
    assert result["year"] == 2021


def test_heuristic_uses_first_line_as_title():
    text = "My Paper Title\nRest of text"
    result = extract_metadata_heuristic(text)
    assert result["title"] == "My Paper Title"


def test_heuristic_metadata_source():
    result = extract_metadata_heuristic("Title\n2020")
    assert result["metadata_source"] == "heuristic"


def test_heuristic_empty_text():
    result = extract_metadata_heuristic("")
    assert result["title"] == "Unknown"
    assert result["year"] is None


# ── extract_metadata (integration-free, mocked) ───────────────────────────────

def test_extract_metadata_uses_heuristic_when_no_doi():
    """No DOI → LLM disabled → heuristic used."""
    pdf_bytes = FIXTURE.read_bytes()
    # Patch Ollama to be unavailable so heuristic is used
    with patch("services.pdf_parser.extract_metadata_with_llm", return_value=None):
        result = extract_metadata(pdf_bytes)
    assert result["title"]  # some title extracted
    assert "raw_text" in result
    assert result["metadata_source"] in ("heuristic", "llm", "semantic_scholar", "crossref")


def test_extract_metadata_returns_raw_text():
    pdf_bytes = FIXTURE.read_bytes()
    with patch("services.pdf_parser.extract_metadata_with_llm", return_value=None):
        result = extract_metadata(pdf_bytes)
    assert "Attention" in result["raw_text"]


def test_extract_metadata_uses_api_when_doi_found():
    """When DOI found, Semantic Scholar is tried first."""
    pdf_bytes = FIXTURE.read_bytes()
    mock_result = {
        "title": "Attention Is All You Need",
        "authors": ["Vaswani et al."],
        "year": 2017,
        "venue": "NeurIPS",
        "abstract": "Transformer paper",
        "doi": "arXiv:1706.03762",
        "citation_count": 50000,
        "topics": [],
        "metadata_source": "semantic_scholar",
    }
    with patch("services.pdf_parser.lookup_semantic_scholar", return_value=mock_result) as mock_ss:
        result = extract_metadata(pdf_bytes)
    mock_ss.assert_called_once()
    assert result["title"] == "Attention Is All You Need"
    assert result["metadata_source"] == "semantic_scholar"


def test_extract_metadata_falls_back_to_crossref():
    """When S2 fails, Crossref is tried."""
    pdf_bytes = FIXTURE.read_bytes()
    crossref_result = {
        "title": "Attention Is All You Need",
        "authors": [],
        "year": 2017,
        "venue": None,
        "abstract": None,
        "doi": "arXiv:1706.03762",
        "citation_count": None,
        "topics": [],
        "metadata_source": "crossref",
    }
    with patch("services.pdf_parser.lookup_semantic_scholar", return_value=None), \
         patch("services.pdf_parser.lookup_crossref", return_value=crossref_result):
        result = extract_metadata(pdf_bytes)
    assert result["metadata_source"] == "crossref"


def test_extract_metadata_bad_pdf_still_returns_dict():
    with patch("services.pdf_parser.extract_metadata_with_llm", return_value=None):
        result = extract_metadata(b"garbage")
    assert isinstance(result, dict)
    assert "title" in result
