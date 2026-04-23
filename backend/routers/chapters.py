"""Chapters router — book/lecture chapter management."""
import logging
from fastapi import APIRouter, HTTPException, status

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
from services.book_chapter_parser import extract_chapters_with_splits
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
    Existing chapters for this paper are replaced.
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

    # Delete existing chapters first
    deleted = delete_chapters_for_paper(driver, paper_id)
    if deleted:
        log.info("Deleted %d existing chapters for paper %s", deleted, paper_id)

    # Detect chapters via heuristics
    chapter_dicts = extract_chapters_with_splits(raw_text)

    # Optional: refine with AI
    if body.use_ai and not chapter_dicts:
        ai_chapters = detect_chapters_with_ai(paper.get("title", ""), raw_text)
        if ai_chapters:
            # AI only gives titles/numbers — extract text slices heuristically per title
            chapter_dicts = ai_chapters

    if not chapter_dicts:
        raise HTTPException(
            status_code=422,
            detail="Could not detect any chapters in this document. Try uploading a document with clearer chapter headings.",
        )

    log.info("Detected %d chapters for paper %s", len(chapter_dicts), paper_id)

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
