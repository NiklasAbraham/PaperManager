"""Service for detecting and extracting chapters from book/lecture PDFs."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Pattern 1: "Chapter N" headings — capture everything on that line
_CHAPTER_WORD_RE = re.compile(
    r"^[ \t]*(?:chapter)\s+(\d+)[:\.\s]*([^\n]{0,80})",
    re.IGNORECASE | re.MULTILINE,
)

# Pattern 2: "N.M Title" sub-section headings (e.g. "1.2 Background")
_SUB_SECTION_RE = re.compile(
    r"^[ \t]*(\d{1,3})\.(\d{1,3})\.?\s+([A-Z][^\n]{3,80})",
    re.MULTILINE,
)

# Pattern 3: "N. Title" or "N Title" top-level numbered section (e.g. "1. Introduction")
_NUMBERED_SECTION_RE = re.compile(
    r"^[ \t]*(\d{1,3})[\.:\s]\s+([A-Z][^\n]{3,80})",
    re.MULTILINE,
)

# Fallback: ALL-CAPS short lines that look like headings
_FALLBACK_HEADING_RE = re.compile(
    r"^[ \t]*([A-Z][A-Z\s\d\-:]{4,60}[A-Z\d])\s*$",
    re.MULTILINE,
)

# Max characters per chapter before we recommend a sub-chapter split
MAX_CHAPTER_CHARS = 6_000


@dataclass
class ChapterCandidate:
    number: float          # sortable numeric key, e.g. 1.0 or 1.1
    title: str
    level: int             # 1 = chapter, 2 = sub-chapter
    start_char: int
    end_char: int = -1     # filled in after all candidates are found
    text: str = field(default="", repr=False)


def _deduplicate(candidates: list[ChapterCandidate]) -> list[ChapterCandidate]:
    """Remove candidates whose normalized title is already in the list."""
    seen: set[str] = set()
    result: list[ChapterCandidate] = []
    for c in candidates:
        norm = re.sub(r"\s+", " ", c.title.lower()).strip()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(c)
    return result


def detect_chapters(raw_text: str) -> list[ChapterCandidate]:
    """
    Detect chapter/section boundaries in *raw_text*.

    Returns a list of ChapterCandidate objects with .text populated.
    """
    if not raw_text or not raw_text.strip():
        return []

    candidates: list[ChapterCandidate] = []

    # --- Pass 1: "Chapter N: Title" style ---
    for m in _CHAPTER_WORD_RE.finditer(raw_text):
        num = float(m.group(1))
        title_part = m.group(2).strip().lstrip(":.- ")
        title = title_part if title_part else f"Chapter {int(num)}"
        candidates.append(ChapterCandidate(number=num, title=title, level=1, start_char=m.start()))

    # --- Pass 2: "N.M Title" sub-sections ---
    for m in _SUB_SECTION_RE.finditer(raw_text):
        num = float(f"{m.group(1)}.{m.group(2)}")
        title = m.group(3).strip()
        candidates.append(ChapterCandidate(number=num, title=title, level=2, start_char=m.start()))

    # If no "Chapter N" style, try numbered sections for top-level chapters
    if not any(c.level == 1 for c in candidates):
        for m in _NUMBERED_SECTION_RE.finditer(raw_text):
            num = float(m.group(1))
            title = m.group(2).strip()
            # Skip if this looks like it's part of a figure/table caption
            if re.match(r"^(figure|table|fig\.|tab\.)", title, re.IGNORECASE):
                continue
            candidates.append(ChapterCandidate(number=num, title=title, level=1, start_char=m.start()))

    # If still nothing, fall back to ALL-CAPS headings
    if not candidates:
        for m in _FALLBACK_HEADING_RE.finditer(raw_text):
            title = m.group(1).strip().title()
            candidates.append(ChapterCandidate(
                number=float(len(candidates) + 1),
                title=title,
                level=1,
                start_char=m.start(),
            ))

    if not candidates:
        return []

    # Sort by position in text to handle ToC refs (numbered chapters sometimes appear out of order)
    candidates.sort(key=lambda c: c.start_char)

    # Deduplicate
    candidates = _deduplicate(candidates)

    # Assign end positions and extract text slices
    for i, cand in enumerate(candidates):
        next_start = candidates[i + 1].start_char if i + 1 < len(candidates) else len(raw_text)
        cand.end_char = next_start
        cand.text = raw_text[cand.start_char:next_start].strip()

    return candidates


def split_long_chapter(chapter: ChapterCandidate, max_chars: int = MAX_CHAPTER_CHARS) -> list[ChapterCandidate]:
    """
    If *chapter* is longer than *max_chars*, split it into sub-chapters by
    paragraph boundaries.  Returns a list of new ChapterCandidate objects
    (may just be [chapter] if not too long).
    """
    if len(chapter.text) <= max_chars:
        return [chapter]

    paragraphs = re.split(r"\n{2,}", chapter.text)
    sub_chapters: list[ChapterCandidate] = []
    buf = ""
    sub_num = 1

    for para in paragraphs:
        if len(buf) + len(para) > max_chars and buf:
            sub_chapters.append(ChapterCandidate(
                number=round(chapter.number + sub_num * 0.01, 2),
                title=f"{chapter.title} (part {sub_num})",
                level=2,
                start_char=0,
                text=buf.strip(),
            ))
            buf = para
            sub_num += 1
        else:
            buf += ("\n\n" if buf else "") + para

    if buf.strip():
        sub_chapters.append(ChapterCandidate(
            number=round(chapter.number + sub_num * 0.01, 2),
            title=f"{chapter.title} (part {sub_num})",
            level=2,
            start_char=0,
            text=buf.strip(),
        ))

    if not sub_chapters:
        return [chapter]

    # If only one sub-chapter was produced, keep original
    if len(sub_chapters) == 1:
        return [chapter]

    return sub_chapters


def extract_chapters_with_splits(raw_text: str) -> list[dict]:
    """
    High-level entry point: detect chapters, optionally split long ones,
    and return a list of chapter dicts ready to be stored.
    """
    candidates = detect_chapters(raw_text)

    result: list[dict] = []
    seq = 1
    for cand in candidates:
        parts = split_long_chapter(cand)
        for part in parts:
            result.append({
                "number": seq,
                "title": part.title,
                "level": part.level,
                "text": part.text,
                "summary": None,
            })
            seq += 1

    return result


def assign_page_numbers(chapters: list[dict], pdf_bytes: bytes) -> list[dict]:
    """
    Given a list of chapter dicts (with 'title' and 'text') and the raw PDF bytes,
    determine which pages each chapter spans and set 'start_page' / 'end_page'.

    Uses pypdf to extract per-page text and matches chapter headings to pages.
    Returns the chapters with start_page/end_page filled in (1-indexed).
    """
    try:
        from pypdf import PdfReader  # type: ignore
        from io import BytesIO

        reader = PdfReader(BytesIO(pdf_bytes))
        page_texts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        log.warning("PDF page parsing failed; skipping page number assignment | %s", exc)
        return chapters

    total_pages = len(page_texts)
    if total_pages == 0:
        return chapters

    def _find_page_for_text(heading: str) -> int | None:
        """Return 1-indexed page number where heading first appears."""
        norm = re.sub(r"\s+", " ", heading.strip().lower())
        for i, pt in enumerate(page_texts):
            if norm in re.sub(r"\s+", " ", pt.lower()):
                return i + 1  # 1-indexed
        return None

    # Assign start pages
    for ch in chapters:
        page = _find_page_for_text(ch.get("title", ""))
        if page is not None:
            ch["start_page"] = page

    # Assign end pages: each chapter ends where the next one starts
    for i, ch in enumerate(chapters):
        if "start_page" not in ch:
            continue
        if i + 1 < len(chapters) and "start_page" in chapters[i + 1]:
            ch["end_page"] = max(ch["start_page"], chapters[i + 1]["start_page"] - 1)
        else:
            ch["end_page"] = total_pages

    return chapters
