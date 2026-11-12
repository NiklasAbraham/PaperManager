"""Citation markers -> links, the reference list, and Markdown -> standalone HTML.

No dependencies beyond the standard library: the converter understands what the pipeline writes
(headings, paragraphs, lists, quotes, fenced code, tables, rules, bold, italic, code, links) and
HTML-escapes everything else. Links keep only http(s), mailto, ``/`` and ``#`` targets.
"""
from __future__ import annotations

import html
import logging
import re
import unicodedata
from datetime import datetime

log = logging.getLogger(__name__)

CLOSING_TITLE = "What the library shows and what it does not"
_GROUP_RE = re.compile(r"([ \t]*)\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")
_REFS_HEADING = re.compile(r"^#{1,3}\s+References\s*$", re.IGNORECASE | re.MULTILINE)
_CITE_LINK_RE = re.compile(r"\[\[\d+\]\]\([^)]*\)")


# --------------------------------------------------------------------------- assembly

def slugify(text: str, fallback: str = "report", limit: int = 60) -> str:
    """A filesystem-safe ASCII slug."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:limit].strip("-")
    return slug or fallback


def convert_citations(text: str, sources: dict[int, dict], order: list[int] | None = None) -> tuple[str, list[int]]:
    """Replace ``[S3]`` / ``[S3, S5]`` / ``[S3][S5]`` by ``[[n]](/paper/<id>)``.

    ``sources`` maps the source number to its paper dict (with ``id``). Numbers ``n`` follow
    the order of first citation (continuing ``order``, the source numbers cited so far);
    markers for unknown sources are dropped. Returns the new text and the updated order.
    """
    order = list(order or [])

    def number(s: int) -> int:
        if s not in order:
            order.append(s)
        return order.index(s) + 1

    def repl(m: re.Match) -> str:
        wanted = [int(x) for x in re.findall(r"S(\d+)", m.group(2))]
        links, seen = [], set()
        for s in wanted:
            if s in sources and s not in seen:
                seen.add(s)
                links.append(f"[[{number(s)}]](/paper/{sources[s]['id']})")
        return m.group(1) + ", ".join(links) if links else ""

    out = _GROUP_RE.sub(repl, text)
    out = re.sub(r"(\]\(/paper/[^)\s]*\))(?=\[\[)", r"\1, ", out)  # [S3][S5] -> "[1], [2]"
    return out, order


def _reference_line(n: int, paper: dict) -> str:
    authors = [a for a in (paper.get("authors") or []) if a]
    names = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
    year = paper.get("year") or "n.d."
    title = re.sub(r"[*\[\]]", "", paper.get("title") or "Untitled").strip()
    venue = (paper.get("venue") or "").strip()
    head = f"{names} ({year})." if names else f"({year})."
    parts = [head, f"*{title}*."]
    if venue:
        parts.append(venue.rstrip(".") + ".")
    parts.append(f"[Open in library](/paper/{paper['id']})")
    return f"{n}. " + " ".join(parts)


def count_words(markdown: str) -> int:
    """Words of the text without the reference list and citation links."""
    match = _REFS_HEADING.search(markdown)
    body = markdown[: match.start()] if match else markdown
    body = _CITE_LINK_RE.sub("", body)
    body = re.sub(r"\]\([^)]*\)", "]", body)
    return len(re.findall(r"\w+(?:['’-]\w+)*", body))


def assemble(
    title: str,
    lede: str,
    intro: str,
    sections: list[dict],
    closing: str,
    sources: dict[int, dict],
) -> dict:
    """Join the parts into one Markdown report.

    ``sections`` is ``[{"title", "body"}]``; ``sources`` maps ``S`` numbers to paper dicts
    (``id``, ``title``, ``year``, ``venue``, ``authors``). Returns ``{"markdown", "cited",
    "word_count"}`` with ``cited = [{"id", "n"}]`` in reference order.
    """
    parts = [f"# {title.strip()}", lede.strip()]
    if intro.strip():
        parts += ["## Introduction", intro.strip()]
    for sec in sections:
        parts += [f"## {sec['title'].strip()}", sec["body"].strip()]
    if closing.strip():
        parts += [f"## {CLOSING_TITLE}", closing.strip()]
    body, order = convert_citations("\n\n".join(p for p in parts if p), sources)
    cited = [{"id": sources[s]["id"], "n": i + 1} for i, s in enumerate(order)]
    markdown = body
    if order:
        refs = [_reference_line(i + 1, sources[s]) for i, s in enumerate(order)]
        markdown += "\n\n## References\n\n" + "\n".join(refs)
    markdown += "\n"
    return {"markdown": markdown, "cited": cited, "word_count": count_words(markdown)}


# --------------------------------------------------------------------------- inline

_LINK_RE = re.compile(
    r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*([^()\s]*(?:\([^()\s]*\)[^()\s]*)*)(?:\s+\"[^\"]*\")?\s*\)"
)
_CODE_RE = re.compile(r"(`+)(.+?)\1")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_ITALIC_UNDER = re.compile(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)")
_TOKEN_RE = re.compile("\x00(\\d+)\x00")


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _safe_url(url: str, base_url: str) -> str | None:
    """The URL to link to, or None when its scheme is not allowed."""
    url = html.unescape(url).strip()
    if re.match(r"^(https?://|mailto:)", url, re.IGNORECASE):
        return url
    if url.startswith("#"):
        return url
    if url.startswith("/") and not url.startswith("//"):
        return base_url.rstrip("/") + url if base_url else url
    return None


def inline(text: str, base_url: str = "") -> str:
    """Inline Markdown to HTML (everything else is escaped)."""
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    text = text.replace("\x00", "")
    text = _CODE_RE.sub(lambda m: keep(f"<code>{_esc(m.group(2).strip())}</code>"), text)

    def link(m: re.Match) -> str:
        label = inline(m.group(1), base_url)
        url = _safe_url(m.group(2), base_url)
        if url is None:
            return keep(label)
        return keep(f'<a href="{_esc(url)}" rel="noopener">{label}</a>')

    text = _LINK_RE.sub(link, text)
    text = _esc(text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_STAR.sub(r"<em>\1</em>", text)
    text = _ITALIC_UNDER.sub(r"<em>\1</em>", text)
    while _TOKEN_RE.search(text):
        text = _TOKEN_RE.sub(lambda m: stash[int(m.group(1))], text)
    return text


# --------------------------------------------------------------------------- blocks

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)\s*([\w+-]*)\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _is_item(line: str) -> bool:
    return bool(_ITEM.match(line)) and not _HR.match(line)


def _starts_block(line: str) -> bool:
    return bool(_HEADING.match(line) or _HR.match(line) or _FENCE.match(line) or _QUOTE.match(line))


def _split_cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]


class _Converter:
    """Block-level Markdown converter; ``number_sections`` prefixes h2 headings with 01, 02, …"""

    def __init__(self, base_url: str = "", number_sections: bool = False) -> None:
        self.base_url = base_url
        self.number_sections = number_sections
        self.h2 = 0

    def inline(self, text: str) -> str:
        return inline(text, self.base_url)

    def convert(self, markdown: str) -> str:
        return self.blocks(markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"))

    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            fence = _FENCE.match(line)
            if fence:
                code: list[str] = []
                i += 1
                while i < n and not lines[i].strip().startswith(fence.group(1)):
                    code.append(lines[i])
                    i += 1
                i += 1
                out.append(f"<pre><code>{_esc(chr(10).join(code))}</code></pre>")
                continue
            heading = _HEADING.match(line)
            if heading:
                out.append(self.heading(len(heading.group(1)), heading.group(2)))
                i += 1
                continue
            if _HR.match(line):
                out.append("<hr>")
                i += 1
                continue
            if _QUOTE.match(line):
                inner = []
                while i < n and _QUOTE.match(lines[i]):
                    inner.append(_QUOTE.match(lines[i]).group(1))
                    i += 1
                out.append(f"<blockquote>{self.blocks(inner)}</blockquote>")
                continue
            if "|" in line and i + 1 < n and "|" in lines[i + 1] and _TABLE_SEP.match(lines[i + 1]):
                html_table, i = self.table(lines, i)
                out.append(html_table)
                continue
            if _is_item(line):
                items, i = self.collect_list(lines, i)
                out.append(self.render_list(items))
                continue
            para = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not _starts_block(lines[i]):
                if _is_item(lines[i]) and re.match(r"^\s*([-*+]|1[.)])\s", lines[i]):
                    break
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{self.inline(chr(10).join(para))}</p>")
        return "\n".join(out)

    def heading(self, level: int, text: str) -> str:
        slug = slugify(re.sub(r"[*_`\[\]()]", "", text), "section")
        if level == 2 and self.number_sections and text.strip().lower() != "references":
            self.h2 += 1
            return f'<h2 id="{slug}"><span class="num">{self.h2:02d}</span>{self.inline(text)}</h2>'
        return f'<h{level} id="{slug}">{self.inline(text)}</h{level}>'

    def table(self, lines: list[str], i: int) -> tuple[str, int]:
        header = _split_cells(lines[i])
        aligns = []
        for cell in _split_cells(lines[i + 1]):
            left, right = cell.startswith(":"), cell.endswith(":")
            aligns.append("center" if left and right else "right" if right else "left" if left else "")
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            rows.append(_split_cells(lines[i]))
            i += 1

        def cell(tag: str, text: str, k: int) -> str:
            style = f' style="text-align:{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
            return f"<{tag}{style}>{self.inline(text)}</{tag}>"

        head = "".join(cell("th", c, k) for k, c in enumerate(header))
        body = "".join(
            "<tr>" + "".join(cell("td", c, k) for k, c in enumerate(r)) + "</tr>" for r in rows
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>", i

    def collect_list(self, lines: list[str], i: int) -> tuple[list[dict], int]:
        items: list[dict] = []
        n = len(lines)

        def continues(line: str) -> bool:
            """An item that belongs to this list (a top-level item of the other kind starts a new one)."""
            if not _is_item(line):
                return False
            if not items:
                return True
            m = _ITEM.match(line)
            ordered = m.group(2)[0].isdigit()
            indent = len(m.group(1).expandtabs(4))
            return indent >= items[0]["indent"] + 2 or ordered == items[0]["ordered"]

        while i < n:
            line = lines[i]
            if continues(line):
                m = _ITEM.match(line)
                ordered = m.group(2)[0].isdigit()
                items.append({
                    "indent": len(m.group(1).expandtabs(4)),
                    "ordered": ordered,
                    "start": int(re.match(r"\d+", m.group(2)).group()) if ordered else 1,
                    "text": m.group(3),
                })
                i += 1
            elif not line.strip():
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and continues(lines[j]):
                    i = j
                    continue
                break
            elif items and not _starts_block(line) and not _is_item(line):
                items[-1]["text"] += " " + line.strip()
                i += 1
            else:
                break
        return items, i

    def render_list(self, items: list[dict]) -> str:
        top = min(it["indent"] for it in items)
        ordered = items[0]["ordered"]
        tag = "ol" if ordered else "ul"
        start = items[0]["start"]
        attr = f' start="{start}"' if ordered and start != 1 else ""
        parts, i = [], 0
        while i < len(items):
            it = items[i]
            children, j = [], i + 1
            while j < len(items) and items[j]["indent"] >= top + 2:
                children.append(items[j])
                j += 1
            nested = self.render_list(children) if children else ""
            parts.append(f"<li>{self.inline(it['text'])}{nested}</li>")
            i = j
        return f"<{tag}{attr}>" + "".join(parts) + f"</{tag}>"


def markdown_to_html(markdown: str, base_url: str = "", number_sections: bool = False) -> str:
    """Convert Markdown to an HTML fragment (see the module docstring for the dialect)."""
    return _Converter(base_url, number_sections).convert(markdown)


# --------------------------------------------------------------------------- page

_CSS = """
:root{--bg:#fff;--text:#2b3240;--strong:#111827;--muted:#6b7280;--rule:#e3e8f0;--panel:#f4f5f2;
--accent:#0b4fc0;--mark:#c2255c;--ink:#04204b;
--head:'Space Grotesk','Hanken Grotesk','Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
--body:'Hanken Grotesk','Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#15171c;--text:#d7dbe2;--strong:#f1f3f6;--muted:#9aa1ad;
--rule:#2c313b;--panel:#1f232b;--accent:#7aa2ff;--mark:#f06595;--ink:#9db8ec;color-scheme:dark}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:17px/1.72 var(--body);overflow-x:hidden}
a{color:var(--accent);text-underline-offset:2px}
article{max-width:720px;margin:0 auto;padding:2.6rem 16px 5rem}
.eyebrow{font:.74rem var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--mark);margin:0 0 .6rem}
h1{font:700 clamp(2rem,5.4vw,2.9rem)/1.08 var(--head);letter-spacing:-.035em;color:var(--strong);margin:0 0 1rem;text-wrap:balance}
.lede{font-size:1.17rem;line-height:1.6;color:var(--muted);margin:0 0 1.2rem}
.meta{font-size:.85rem;color:var(--muted);margin:0 0 1.6rem}
.note{border-left:3px solid var(--mark);background:var(--panel);border-radius:0 10px 10px 0;padding:.75rem 1rem;
margin:1.5rem 0 2.4rem;font-size:.95rem;line-height:1.62}
.note p{margin:0}
h2{font:700 1.5rem/1.22 var(--head);letter-spacing:-.025em;color:var(--strong);margin:3rem 0 1rem;text-wrap:balance}
h2 .num{font:500 .86rem var(--mono);color:var(--mark);margin-right:.6rem;vertical-align:.18rem;letter-spacing:0}
h3,h4{font-family:var(--head);color:var(--strong);margin:2rem 0 .6rem}
h3{font-size:1.14rem}h4{font-size:1rem}
p{margin:0 0 1.15rem}ul,ol{padding-left:1.3rem;margin:0 0 1.15rem}li{margin-bottom:.4rem}
strong{color:var(--strong);font-weight:650}
blockquote{margin:0 0 1.15rem;padding:.1rem 0 .1rem 1rem;border-left:2px solid var(--ink)}
code{font:.86em var(--mono);background:var(--panel);padding:.05em .3em;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--panel);padding:.8rem 1rem;border-radius:8px;overflow-x:auto;font-size:.88rem}
pre code{background:none;padding:0}
hr{border:0;border-top:1px solid var(--rule);margin:2rem 0}
table{border-collapse:collapse;margin:0 0 1.15rem;font-size:.92rem;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--rule);padding:.4rem .7rem;text-align:left}
th{color:var(--strong)}
h2#references+ol{font-size:.93rem;line-height:1.55}
@media print{body{font-size:11pt}article{max-width:none;padding:0}a{color:inherit}}
"""


def _split_report(markdown: str) -> tuple[str, str, str]:
    """Title (first H1), lede (the paragraph before the first H2) and the rest."""
    lines = markdown.strip().split("\n")
    title = ""
    if lines and re.match(r"^#\s+\S", lines[0]):
        title = re.sub(r"^#\s+", "", lines.pop(0)).strip()
    while lines and not lines[0].strip():
        lines.pop(0)
    lede: list[str] = []
    while lines and lines[0].strip() and not _starts_block(lines[0]):
        lede.append(lines.pop(0).strip())
    return title, " ".join(lede), "\n".join(lines)


def _human_date(value: str | None) -> str:
    try:
        d = datetime.strptime((value or "")[:10], "%Y-%m-%d")
    except ValueError:
        d = datetime.now()
    return f"{d.day} {d.strftime('%B %Y')}"


def to_html(
    markdown: str,
    *,
    model_label: str = "",
    date: str | None = None,
    frontend_url: str = "",
    papers: int | None = None,
) -> str:
    """One self-contained HTML page (inline CSS, no external requests) for a report.

    ``/paper/<id>`` links become absolute with ``frontend_url``.
    """
    title, lede, rest = _split_report(markdown)
    when = _human_date(date)
    words = count_words(markdown)
    minutes = max(1, round(words / 220))
    cited = len(set(re.findall(r"\]\(/paper/([^)\s]+)\)", rest)))
    count = papers if papers is not None else cited
    meta = [f"Written by an AI", when, f"about {minutes} min read"]
    if count:
        meta.append(f"{count} paper{'s' if count != 1 else ''} from the library")
    who = f"an AI ({model_label})" if model_label else "an AI"
    note = (
        f"<p><strong>Written by {_esc(who)}</strong> from your PaperManager library on {_esc(when)}. "
        "Every [n] links to the paper it draws on; check the claims against the papers before relying on them.</p>"
    )
    body = markdown_to_html(rest, base_url=frontend_url, number_sections=True)
    lede_html = f'<p class="lede">{inline(lede, frontend_url)}</p>' if lede else ""
    return (
        '<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title or 'Report')}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n<article>\n"
        f'<p class="eyebrow">Report · PaperManager library · {_esc(when.split(" ", 1)[1])}</p>\n'
        f"<h1>{inline(title or 'Report')}</h1>\n{lede_html}\n"
        f'<p class="meta">{" · ".join(_esc(m) for m in meta)}</p>\n'
        f'<div class="note">{note}</div>\n{body}\n</article>\n</body>\n</html>\n'
    )
