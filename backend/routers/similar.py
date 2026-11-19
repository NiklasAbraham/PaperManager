"""Find papers like this abstract (.specs/020_similar_search.md).

``POST /search/similar`` embeds the text of the request and returns the nearest papers of the
library and, when the optional feed is on, of the feed. ``GET /search/similar/{paper_id}`` does
the same for a paper of the library ("more like this"). A new file next to routers/search.py so
that the ranked text search stays as it is.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from db.connection import get_driver
from services import similar_search as ss
from services.auth import get_current_user

router = APIRouter(prefix="/search/similar", tags=["search"], dependencies=[Depends(get_current_user)])

Scope = Literal["library", "feed", "both"]


class SimilarBody(BaseModel):
    text: str = Field(..., max_length=ss.TEXT_MAX, description="a title and an abstract, or a description of the paper wanted")
    k: int = Field(ss.K_DEFAULT, ge=ss.K_MIN, le=ss.K_MAX)
    scope: Scope = "both"
    since: date | None = Field(None, description="only papers published on or after this date")
    min_score: float = Field(0.0, ge=-1.0, le=1.0, description="cosine floor")
    include_stubs: bool = False

    @field_validator("text")
    @classmethod
    def _length(cls, v: str) -> str:
        v = v.strip()
        if len(v) < ss.TEXT_MIN:
            raise ValueError(f"text must have at least {ss.TEXT_MIN} characters")
        return v


def _fail(exc: ss.SimilarError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.post("")
def similar_by_text(body: SimilarBody, user: str = Depends(get_current_user)) -> dict:
    """Nearest papers to a text. 200 with ``available: false`` and a ``reason`` while the index cannot
    be searched (still building, model changed, search switched off); 404 for ``scope=feed`` when the
    feed is off; 422 for a text outside 20 to 20,000 characters."""
    try:
        return ss.search_by_text(user, body.text, body.k, body.scope, body.since, body.min_score,
                                 body.include_stubs, full_text=True, driver=get_driver())
    except ss.SimilarError as exc:
        raise _fail(exc) from None


@router.get("/{paper_id}")
def similar_to_paper(
    paper_id: str,
    k: int = Query(ss.K_DEFAULT, ge=ss.K_MIN, le=ss.K_MAX),
    scope: Scope = "both",
    since: date | None = None,
    min_score: float = Query(0.0, ge=-1.0, le=1.0),
    include_stubs: bool = False,
    user: str = Depends(get_current_user),
) -> dict:
    """Papers like this library paper (which the caller must be allowed to see: 404 otherwise)."""
    try:
        return ss.search_by_paper(user, paper_id, k, scope, since, min_score, include_stubs,
                                  full_text=True, driver=get_driver())
    except ss.SimilarError as exc:
        raise _fail(exc) from None
