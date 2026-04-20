"""Bulk import router — process a JSON list of paper entries and stream SSE progress."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.papers import merge_paper_by_doi, find_duplicate
from db.queries.tags import tag_paper
from db.queries.people import get_or_create_person_with_affiliation, link_author
from db.queries.topics import get_or_create_topic, link_paper_topic
from db.queries.projects import add_paper_to_project
from services.bulk_resolver import resolve_entry, download_pdf_for_paper
from services.drive import upload_pdf
from services.ai import summarize_paper, suggest_topics

log = logging.getLogger(__name__)
router = APIRouter(prefix="/papers/bulk-import", tags=["bulk-import"])


class BulkEntry(BaseModel):
    url: str | None = None
    arxiv: str | None = None
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    fetch_pdf: bool | None = None  # per-entry override


class BulkImportBody(BaseModel):
    papers: list[BulkEntry]
    project_id: str | None = None
    fetch_pdf: bool = True


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _safe_filename(title: str) -> str:
    safe = re.sub(r"[^\w\s-]", "", title)[:50].strip()
    return f"{safe}.pdf" if safe else "paper.pdf"


def _process_entry(driver, entry: BulkEntry, project_id: str | None, fetch_pdf: bool) -> dict:
    """Synchronous per-entry processing — run via asyncio.to_thread."""
    entry_dict = {k: v for k, v in entry.model_dump().items() if v is not None}
    input_label = entry.url or entry.arxiv or entry.doi or entry.title or "(unknown)"

    # Resolve metadata
    meta = resolve_entry(entry_dict)
    if not meta or not meta.get("title"):
        return {"status": "error", "input": input_label, "error": "Could not resolve metadata"}

    doi = meta.get("doi")

    # Check if already in DB
    was_existing = bool(doi and find_duplicate(driver, doi=doi))

    # Optionally download PDF
    should_fetch = entry.fetch_pdf if entry.fetch_pdf is not None else fetch_pdf
    drive_file_id = None
    if should_fetch:
        try:
            pdf_bytes = download_pdf_for_paper(meta)
            if pdf_bytes:
                drive_file_id = upload_pdf(pdf_bytes, _safe_filename(meta.get("title", "paper")))
        except Exception as e:
            log.warning("PDF download/upload failed (non-fatal) | input=%s | %s", input_label, e)

    # Summarize from abstract
    summary = None
    if meta.get("abstract"):
        try:
            summary = summarize_paper(meta["abstract"], meta.get("title", ""))
        except Exception as e:
            log.warning("Summary failed (non-fatal) | %s", e)

    # Save to Neo4j (merge by DOI for deduplication)
    paper = merge_paper_by_doi(driver, {
        "title": meta.get("title", ""),
        "year": meta.get("year"),
        "doi": doi,
        "abstract": meta.get("abstract"),
        "summary": summary,
        "drive_file_id": drive_file_id,
        "citation_count": meta.get("citation_count"),
        "metadata_source": meta.get("metadata_source", "bulk"),
        "raw_text": "",
    })

    tag_paper(driver, paper["id"], "bulk-import")

    # Link authors
    authors_detail = meta.get("authors_detail") or []
    aff_map = {d["name"]: d.get("affiliation") for d in authors_detail}
    for name in meta.get("authors", []):
        if name:
            person = get_or_create_person_with_affiliation(driver, name, aff_map.get(name))
            link_author(driver, paper["id"], person["id"])

    # Link topics from metadata source
    for topic_name in meta.get("topics", []):
        if topic_name:
            topic = get_or_create_topic(driver, topic_name)
            link_paper_topic(driver, paper["id"], topic["id"])

    # AI topic suggestion (best-effort)
    try:
        ai_topics = suggest_topics(
            title=meta.get("title", ""),
            abstract=meta.get("abstract", "") or "",
            summary=summary or "",
        )
        for topic_name in ai_topics:
            if topic_name:
                link_paper_topic(driver, paper["id"], topic_name)
    except Exception as e:
        log.warning("AI topic suggestion failed (non-fatal) | %s", e)

    # Add to project
    if project_id:
        try:
            add_paper_to_project(driver, project_id, paper["id"])
        except Exception:
            pass

    if was_existing:
        return {
            "status": "skipped",
            "title": paper.get("title"),
            "id": paper.get("id"),
            "reason": "already in database",
        }
    return {
        "status": "success",
        "title": paper.get("title"),
        "id": paper.get("id"),
        "has_pdf": drive_file_id is not None,
    }


async def _stream_bulk(body: BulkImportBody) -> AsyncGenerator[str, None]:
    driver = get_driver()
    total = len(body.papers)
    imported = skipped = errors = 0

    for idx, entry in enumerate(body.papers):
        input_label = entry.url or entry.arxiv or entry.doi or entry.title or "(unknown)"
        try:
            result = await asyncio.to_thread(
                _process_entry, driver, entry, body.project_id, body.fetch_pdf
            )
            status = result["status"]
            if status == "success":
                imported += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1
            yield _sse({"index": idx, "total": total, **result})
        except Exception as e:
            errors += 1
            log.exception("Bulk import entry failed | input=%s", input_label)
            yield _sse({
                "index": idx, "total": total,
                "status": "error",
                "input": input_label,
                "error": str(e),
            })

    yield _sse({"done": True, "imported": imported, "skipped": skipped, "errors": errors})


@router.post("")
async def bulk_import(body: BulkImportBody):
    """
    Bulk import papers from a JSON list. Streams SSE progress events.

    Each event: data: {index, total, status, ...}
    Final event: data: {done: true, imported, skipped, errors}
    """
    return StreamingResponse(
        _stream_bulk(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
