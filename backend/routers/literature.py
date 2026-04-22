"""Literature search router — stream recent papers from arXiv, PubMed, bioRxiv."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db.connection import get_driver
from services.literature_search import (
    _KEYWORDS_FILE,
    load_keywords,
    mark_existing,
    search_arxiv,
    search_biorxiv,
    search_pubmed,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/literature", tags=["literature"])


class LiteratureSearchBody(BaseModel):
    days: int = 7
    max_per_source: int = 100
    sources: list[str] = ["arxiv", "pubmed", "biorxiv"]


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _stream_search(body: LiteratureSearchBody) -> AsyncGenerator[str, None]:
    driver = get_driver()
    keywords = load_keywords()
    end   = date.today()
    start = end - timedelta(days=body.days)
    counts: dict[str, int] = {}

    source_fns = {
        "arxiv":   lambda: search_arxiv(keywords, start, end, body.max_per_source),
        "pubmed":  lambda: search_pubmed(keywords, start, end, body.max_per_source),
        "biorxiv": lambda: search_biorxiv(keywords, start, end, body.max_per_source),
    }

    for source in body.sources:
        fn = source_fns.get(source)
        if fn is None:
            continue

        yield _sse({"searching": source})

        try:
            papers = await asyncio.to_thread(fn)
        except Exception as e:
            log.warning("Literature search failed for %s: %s", source, e)
            yield _sse({"source": source, "error": str(e)})
            counts[source] = 0
            continue

        # Mark which ones are already in the library
        try:
            await asyncio.to_thread(mark_existing, papers, driver)
        except Exception as e:
            log.warning("mark_existing failed: %s", e)

        counts[source] = len(papers)

        for paper in papers:
            yield _sse({"source": source, "paper": paper.to_dict()})

    yield _sse({"done": True, "counts": counts})


class KeywordsBody(BaseModel):
    content: str


@router.get("/keywords")
def get_keywords():
    """Return the raw text of the keywords file."""
    try:
        return {"content": _KEYWORDS_FILE.read_text(encoding="utf-8")}
    except FileNotFoundError:
        return {"content": ""}


@router.put("/keywords")
def put_keywords(body: KeywordsBody):
    """Overwrite the keywords file with new content."""
    _KEYWORDS_FILE.write_text(body.content, encoding="utf-8")
    # Return parsed keyword list so UI can preview what will be used
    return {"content": body.content, "keywords": load_keywords()}


@router.post("/search")
async def literature_search(body: LiteratureSearchBody):
    return StreamingResponse(
        _stream_search(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
