"""Report rendering: citation markers, references, Markdown -> HTML, the standalone page."""
from __future__ import annotations

import re

from services.reports import render

SOURCES = {
    1: {"id": "aaa", "title": "First *paper*", "year": 2021, "venue": "NeurIPS", "authors": ["A One", "B Two"]},
    2: {"id": "bbb", "title": "Second", "year": None, "venue": "", "authors": ["C Three", "D Four", "E Five", "F Six"]},
    3: {"id": "ccc", "title": "Third", "year": 2019, "venue": "ICML", "authors": []},
}


def test_slugify():
    assert render.slugify("Diffusion models: what the library shows!") == "diffusion-models-what-the-library-shows"
    assert render.slugify("Über Größe") == "uber-groe"
    assert render.slugify("???") == "report"
    assert len(render.slugify("word " * 50)) <= 60


def test_citations_single_multi_and_adjacent_markers():
    text = "A [S3]. B [S1, S2]. C [S2][S3]."
    out, order = render.convert_citations(text, SOURCES)
    assert out == (
        "A [[1]](/paper/ccc). B [[2]](/paper/aaa), [[3]](/paper/bbb). "
        "C [[3]](/paper/bbb), [[1]](/paper/ccc)."
    )
    assert order == [3, 1, 2]


def test_unknown_markers_are_dropped_with_their_space():
    out, order = render.convert_citations("Claim [S99] here [S1, S99]. More [S4].", SOURCES)
    assert out == "Claim here [[1]](/paper/aaa). More."
    assert order == [1]


def test_references_follow_first_cited_order_and_format():
    result = render.assemble(
        "Title", "Lede.", "Intro [S3].",
        [{"title": "One", "body": "Text [S1] and [S2]."}], "Closing [S1].", SOURCES,
    )
    md = result["markdown"]
    assert md.startswith("# Title\n\nLede.\n\n## Introduction\n\nIntro [[1]](/paper/ccc).")
    assert "## One\n\nText [[2]](/paper/aaa) and [[3]](/paper/bbb)." in md
    assert "## What the library shows and what it does not\n\nClosing [[2]](/paper/aaa)." in md
    refs = md.split("## References\n\n")[1].strip().splitlines()
    assert refs == [
        "1. (2019). *Third*. ICML. [Open in library](/paper/ccc)",
        "2. A One, B Two (2021). *First paper*. NeurIPS. [Open in library](/paper/aaa)",
        "3. C Three, D Four, E Five et al. (n.d.). *Second*. [Open in library](/paper/bbb)",
    ]
    assert [c for c in result["cited"]] == [{"id": "ccc", "n": 1}, {"id": "aaa", "n": 2}, {"id": "bbb", "n": 3}]


def test_word_count_ignores_references_and_link_targets():
    result = render.assemble("T", "one two three.", "", [{"title": "S", "body": "four five six seven [S1]."}],
                             "", SOURCES)
    # lede 3 + body 4 + headings "T" and "S" (2) = 9; the reference list and markers add nothing
    assert result["word_count"] == 9
    assert render.count_words("a b\n\n## References\n\n1. lots of words here") == 2


def test_no_citations_means_no_reference_section():
    result = render.assemble("T", "lede", "", [{"title": "S", "body": "no markers"}], "", SOURCES)
    assert "## References" not in result["markdown"] and result["cited"] == []


# ------------------------------------------------------------------ Markdown -> HTML

def md(text: str, **kw) -> str:
    return render.markdown_to_html(text, **kw)


def test_headings_paragraphs_and_inline():
    html = md("## Title here\n\nFirst **bold** and *it* and _it2_ and `a<b` code.\nSecond line.")
    assert '<h2 id="title-here">Title here</h2>' in html
    assert "<p>First <strong>bold</strong> and <em>it</em> and <em>it2</em> and <code>a&lt;b</code> code.\nSecond line.</p>" in html


def test_everything_else_is_escaped():
    html = md("<script>alert(1)</script> & <b>x</b> \"q\"")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp;" in html and "<b>" not in html
    assert md("```\n<div>&</div>\n```") == "<pre><code>&lt;div&gt;&amp;&lt;/div&gt;</code></pre>"


def test_links_only_safe_schemes():
    html = md("[ok](https://example.org/a?b=1&c=2) [mail](mailto:a@b.c) [rel](/paper/x) [frag](#top) "
              "[bad](javascript:alert(1)) [bad2](data:text/html,x) [proto](//evil.example/x) [rel2](foo/bar)")
    assert '<a href="https://example.org/a?b=1&amp;c=2" rel="noopener">ok</a>' in html
    assert '<a href="mailto:a@b.c"' in html and '<a href="/paper/x"' in html and '<a href="#top"' in html
    for bad in ("javascript", "data:", "evil.example", "foo/bar"):
        assert bad not in re.sub(r">[^<]*<", "><", html)  # not inside any attribute
    assert ">bad</a>" not in html and "bad" in html


def test_citation_links_render_with_brackets_and_absolute_base():
    assert md("x [[1]](/paper/abc).") == '<p>x <a href="/paper/abc" rel="noopener">[1]</a>.</p>'
    html = md("x [[1]](/paper/abc).", base_url="https://pm.example.org/")
    assert 'href="https://pm.example.org/paper/abc"' in html


def test_lists_ordered_unordered_and_one_nesting_level():
    html = md("- one\n- two\n  - nested a\n  - nested b\n- three\n\n1. first\n2. second")
    assert html == (
        "<ul><li>one</li><li>two<ul><li>nested a</li><li>nested b</li></ul></li><li>three</li></ul>\n"
        "<ol><li>first</li><li>second</li></ol>"
    )
    assert md("3. third\n4. fourth").startswith('<ol start="3">')
    assert md("- wrapped item\n  continues here") == "<ul><li>wrapped item continues here</li></ul>"


def test_blockquote_hr_and_table():
    assert md("> quoted **text**\n> more") == "<blockquote><p>quoted <strong>text</strong>\nmore</p></blockquote>"
    assert md("a\n\n---\n\nb") == "<p>a</p>\n<hr>\n<p>b</p>"
    html = md("| Model | Score |\n|:--|--:|\n| A | 1 |\n| B \\| x | 2 |")
    assert "<table><thead><tr><th style=\"text-align:left\">Model</th><th style=\"text-align:right\">Score</th></tr></thead>" in html
    assert '<td style="text-align:left">A</td><td style="text-align:right">1</td>' in html
    assert "B | x" in html


def test_code_spans_protect_markup():
    assert md("`**not bold** [x](/y)`") == "<p><code>**not bold** [x](/y)</code></p>"


def test_h2_numbering_skips_references():
    html = md("## Intro\n\ntext\n\n## Next\n\n## References\n\n1. x", number_sections=True)
    assert '<span class="num">01</span>Intro' in html and '<span class="num">02</span>Next' in html
    assert '<h2 id="references">References</h2>' in html


# ------------------------------------------------------------------ the page

def _report() -> str:
    return render.assemble(
        "A <title> & more", "The answer first.", "Intro [S1].",
        [{"title": "Methods", "body": "Body text [S1, S2].\n\n- point"}], "Closing.", SOURCES,
    )["markdown"]


def test_html_page_is_standalone_and_has_the_report_parts():
    page = render.to_html(_report(), model_label="Claude Haiku 4.5", date="2026-11-12T09:00:00+00:00",
                          frontend_url="https://pm.example.org")
    assert page.startswith("<!doctype html>") and "<title>A &lt;title&gt; &amp; more</title>" in page
    assert "<h1>A &lt;title&gt; &amp; more</h1>" in page
    assert '<p class="lede">The answer first.</p>' in page
    assert '<p class="eyebrow">Report · PaperManager library · November 2026</p>' in page
    assert "Written by an AI (Claude Haiku 4.5)" in page and "12 November 2026" in page
    assert "Every [n] links to the paper it draws on; check the claims against the papers before relying on them." in page
    assert '<span class="num">01</span>Introduction' in page and '<span class="num">02</span>Methods' in page
    assert '<h2 id="references">References</h2>' in page
    assert 'href="https://pm.example.org/paper/aaa"' in page and 'href="/paper/' not in page
    assert "prefers-color-scheme:dark" in page and "max-width:720px" in page
    # no external requests: no stylesheet links, scripts, images, imports or url() fetches
    assert not re.search(r"<link|<script|<img|@import|url\(|src=", page)


def test_html_page_without_frontend_url_keeps_relative_links_and_handles_missing_date():
    page = render.to_html(_report(), model_label="", date=None)
    assert 'href="/paper/aaa"' in page and "Written by an AI</strong>" in page
