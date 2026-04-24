"""Chapters router — book/lecture chapter management."""
import logging
import re
from fastapi import APIRouter, HTTPException, Response, status

log = logging.getLogger(__name__)

from db.connection import get_driver
from db.queries.papers import get_paper
from db.queries.chapters import (
    create_chapter,
    list_chapters,
    get_chapter,
    update_chapter,
    delete_chapters_for_paper,
)
from services.book_chapter_parser import extract_chapters_with_splits, assign_page_numbers
from services.ai import summarize_chapter, chat_with_chapter, detect_chapters_with_ai
from models.schemas import ChapterOut, ChapterDetectRequest, ChapterChatRequest, ChatResponse

router = APIRouter(prefix="/papers", tags=["chapters"])


@router.get("/{paper_id}/chapters", response_model=list[ChapterOut])
def get_chapters(paper_id: str):
    """Return all chapters for a paper/book."""
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return list_chapters(driver, paper_id)


@router.post("/{paper_id}/chapters/detect", response_model=list[ChapterOut], status_code=status.HTTP_201_CREATED)
def detect_and_create_chapters(paper_id: str, body: ChapterDetectRequest):
    """
    Detect chapters from the stored raw_text of a book/lecture document.
    Existing chapters for this paper are replaced only on success.
    Each chapter receives an AI-generated summary automatically.
    If body.use_ai is True, Claude is also consulted to refine the chapter list.
    """
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    raw_text = paper.get("raw_text") or ""
    if not raw_text.strip():
        raise HTTPException(status_code=422, detail="No raw text available for this document; cannot detect chapters.")

    # --- Detect first, delete only if we succeed ---

    # Detect chapters via heuristics
    chapter_dicts = extract_chapters_with_splits(raw_text)

    # Optional: refine with AI when heuristics fail
    if body.use_ai and not chapter_dicts:
        ai_chapters = detect_chapters_with_ai(paper.get("title", ""), raw_text)
        if ai_chapters:
            # AI returns {number, title, level} — slice text by searching for each title
            for ch in ai_chapters:
                title = ch.get("title", "")
                idx = raw_text.find(title) if title else -1
                if idx != -1:
                    ch["text"] = raw_text[idx:idx + 8000]
                else:
                    ch["text"] = ""
            chapter_dicts = ai_chapters

    if not chapter_dicts:
        raise HTTPException(
            status_code=422,
            detail="Could not detect any chapters in this document. Try uploading a document with clearer chapter headings.",
        )

    # Try to assign page numbers from the stored PDF (best-effort)
    if paper.get("drive_file_id"):
        try:
            from services.drive import download_pdf
            pdf_bytes = download_pdf(paper["drive_file_id"])
            chapter_dicts = assign_page_numbers(chapter_dicts, pdf_bytes)
        except Exception as exc:
            log.warning("Page number assignment failed (non-fatal) | paper_id=%s | %s", paper_id, exc)

    log.info("Detected %d chapters for paper %s", len(chapter_dicts), paper_id)

    # Detection succeeded — now replace existing chapters
    deleted = delete_chapters_for_paper(driver, paper_id)
    if deleted:
        log.info("Deleted %d existing chapters for paper %s", deleted, paper_id)

    created: list[dict] = []
    for ch in chapter_dicts:
        # Generate AI summary per chapter (best-effort)
        summary = None
        try:
            summary = summarize_chapter(ch.get("title", ""), ch.get("text", ""))
        except Exception as exc:
            log.warning("Chapter summary failed (non-fatal) | chapter=%s | %s", ch.get("title"), exc)

        node = create_chapter(driver, {
            "paper_id": paper_id,
            "number": ch.get("number", len(created) + 1),
            "title": ch.get("title", f"Chapter {len(created) + 1}"),
            "level": ch.get("level", 1),
            "text": ch.get("text", ""),
            "summary": summary,
            "start_page": ch.get("start_page"),
            "end_page": ch.get("end_page"),
        })
        created.append(node)

    log.info("Created %d chapter nodes for paper %s", len(created), paper_id)
    return created


@router.get("/{paper_id}/chapters/{chapter_id}", response_model=ChapterOut)
def get_single_chapter(paper_id: str, chapter_id: str):
    """Return a single chapter."""
    driver = get_driver()
    chapter = get_chapter(driver, chapter_id)
    if not chapter or chapter.get("paper_id") != paper_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


@router.get("/{paper_id}/chapters/{chapter_id}/pdf")
def get_chapter_pdf(paper_id: str, chapter_id: str):
    """
    Return a PDF containing only the pages for this chapter.

    Uses the start_page / end_page stored on the chapter node.
    Falls back to returning the full book PDF if page info is not available.
    """
    driver = get_driver()
    paper = get_paper(driver, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    chapter = get_chapter(driver, chapter_id)
    if not chapter or chapter.get("paper_id") != paper_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

    file_id = paper.get("drive_file_id")
    if not file_id:
        raise HTTPException(status_code=404, detail="No PDF stored for this document")

    try:
        from services.drive import download_pdf
        pdf_bytes = download_pdf(file_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Drive download failed: {exc}")

    start_page = chapter.get("start_page")
    end_page = chapter.get("end_page")

    # If we have page info, slice the PDF; otherwise serve the full PDF
    if start_page and end_page:
        try:
            from pypdf import PdfReader, PdfWriter  # type: ignore
            from io import BytesIO

            reader = PdfReader(BytesIO(pdf_bytes))
            writer = PdfWriter()
            total = len(reader.pages)
            # Pages are 1-indexed; clamp to valid range
            p_start = max(1, int(start_page)) - 1  # convert to 0-indexed
            p_end = min(total, int(end_page))        # 1-indexed inclusive
            for i in range(p_start, p_end):
                writer.add_page(reader.pages[i])
            out = BytesIO()
            writer.write(out)
            pdf_bytes = out.getvalue()
        except Exception as exc:
            log.warning("PDF split failed, falling back to full PDF | %s", exc)

    safe_title = re.sub(r"[^\w\s-]", "", chapter.get("title", "chapter"))[:40].strip()
    filename = f"{safe_title}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{paper_id}/chapters/{chapter_id}/summarize", response_model=ChapterOut)
def regenerate_chapter_summary(paper_id: str, chapter_id: str):
    """Re-generate the AI summary for a single chapter."""
    driver = get_driver()
    chapter = get_chapter(driver, chapter_id)
    if not chapter or chapter.get("paper_id") != paper_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        summary = summarize_chapter(chapter.get("title", ""), chapter.get("text", ""))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI summarization failed: {exc}")

    updated = update_chapter(driver, chapter_id, {"summary": summary})
    return updated


@router.post("/{paper_id}/chapters/{chapter_id}/chat", response_model=ChatResponse)
def chat_chapter(paper_id: str, chapter_id: str, body: ChapterChatRequest):
    """Chat with a specific chapter of a book."""
    driver = get_driver()
    chapter = get_chapter(driver, chapter_id)
    if not chapter or chapter.get("paper_id") != paper_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

    history = [{"role": m.role, "content": m.content} for m in body.history]
    try:
        answer = chat_with_chapter(
            chapter_title=chapter.get("title", ""),
            chapter_text=chapter.get("text", ""),
            question=body.question,
            history=history,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Chat failed: {exc}")

    return {"answer": answer}
