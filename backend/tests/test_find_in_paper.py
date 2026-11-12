"""find_in_paper's phrase step across PDF line breaks and end-of-line hyphenation.

Pure-function tests of tools.library_tools._find_hits: no database. The offsets must
point into the original text, since the client passes them to read_paper_text.
"""
from tools.library_tools import _find_hits

PAD = "lorem ipsum " * 80  # keeps the hits apart (context windows of 200 chars)


def _phrase_hits(text, query, context=200):
    mode, hits = _find_hits(text, query, context, 25)
    return mode, hits


def test_plain_phrase_still_matches():
    text = PAD + "We train with denoising score matching on images." + PAD
    mode, hits = _phrase_hits(text, "score matching")
    assert mode == "phrase" and len(hits) == 1
    assert "score matching" in hits[0]["text"]


def test_phrase_split_by_a_line_break():
    text = PAD + "We train with denoising score\nmatching on images." + PAD
    mode, hits = _phrase_hits(text, "score matching")
    assert mode == "phrase" and hits[0]["terms"] == ["score matching"]
    assert "score\nmatching" in hits[0]["text"]


def test_phrase_with_whitespace_runs_and_case():
    text = PAD + "Score   \n\n  Matching works." + PAD
    mode, _ = _phrase_hits(text, "  score  MATCHING ")
    assert mode == "phrase"


def test_word_hyphenated_at_a_line_end():
    text = PAD + "a latent diffu-\nsion model" + PAD
    mode, hits = _phrase_hits(text, "latent diffusion model")
    assert mode == "phrase"
    assert "diffu-\nsion" in hits[0]["text"]


def test_hyphen_with_spaces_and_soft_hyphen_and_bare_break():
    for broken in ["diffu- \n  sion", "diffu-\r\nsion", "diffu­sion", "diffu­\nsion", "diffu\nsion"]:
        text = PAD + f"the {broken} process" + PAD
        mode, _ = _phrase_hits(text, "diffusion process")
        assert mode == "phrase", repr(broken)


def test_offsets_point_into_the_original_text():
    head = "x" * 1000 + "\n"
    text = head + "score-\nbased diffu-\nsion models" + "y" * 1000
    mode, hits = _find_hits(text, "score-based diffusion models", 200, 5)
    assert mode == "phrase" and len(hits) == 1
    a = hits[0]["offset"]
    assert a == len(head) - 100  # window centred on the match start
    assert text[a:a + 200] == hits[0]["text"]
    assert hits[0]["text"][100:].startswith("score-\nbased diffu-\nsion")


def test_a_hyphen_mid_line_is_not_a_line_break():
    # "diffu-sion" without a line break is a different string: no phrase match.
    text = PAD + "diffu-sion process" + PAD
    mode, _ = _phrase_hits(text, "diffusion process")
    assert mode == "words"


def test_fallback_to_words_kept():
    text = PAD + "diffusion here" + PAD + "process there" + PAD
    mode, hits = _phrase_hits(text, "diffusion process")
    assert mode == "words"
    assert {t for h in hits for t in h["terms"]} == {"diffusion", "process"}


def test_regex_characters_in_the_query_are_literal():
    text = PAD + "the loss L(θ) = E[x]" + PAD
    mode, _ = _phrase_hits(text, "L(θ) = E[x]")
    assert mode == "phrase"
    assert _find_hits(PAD + "abc" + PAD, "a.c", 200, 5)[1] == []  # "." is not a wildcard


def test_empty_query():
    assert _find_hits("some text", "   ", 200, 5) == ("words", [])
