"""Suggestions HTTP API (.specs/015_suggestions.md)."""
from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, StringConstraints

from db.connection import get_driver
from db.queries import suggestions as sq
from db.queries import users as users_q
from services import suggestions as svc
from services.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/suggestions", tags=["suggestions"], dependencies=[Depends(get_current_user)])

Status = Literal["open", "planned", "done", "dismissed"]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=svc.TEXT_MAX)]
Detail = Annotated[str, StringConstraints(strip_whitespace=True, max_length=svc.DETAIL_MAX)]


class SuggestionOut(BaseModel):
    id: str
    text: str
    detail: str
    source: str
    status: str
    created_by: str
    created_at: str | None = None
    updated_at: str | None = None
    votes: int
    voted: bool
    context: str
    conversation_id: str | None = None
    seen: int


class SuggestionCreate(BaseModel):
    text: Text
    detail: Detail = ""


class SuggestionPatch(BaseModel):
    status: Status | None = None
    text: Text | None = None
    detail: Detail | None = None


def _is_admin(username: str) -> bool:
    """Admin check; any failure counts as "not an admin"."""
    try:
        return bool(users_q.is_user_admin(get_driver(), username))
    except Exception:  # noqa: BLE001
        log.exception("Admin check failed for %s", username)
        return False


def _get_or_404(suggestion_id: str) -> dict:
    row = sq.get_suggestion(get_driver(), suggestion_id)
    if not row:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return row


@router.get("", response_model=list[SuggestionOut])
def list_suggestions(
    status: Status | None = None,
    source: Literal["chat", "user", "report"] | None = None,
    sort: Literal["votes", "new"] = Query("votes"),
    user: str = Depends(get_current_user),
):
    """All suggestions; ``votes`` puts open and planned first, then by votes, then newest."""
    rows = sq.list_suggestions(get_driver(), status=status, source=source)
    return [svc.to_out(r, user) for r in svc.sort_rows(rows, sort)]


@router.get("/counts")
def suggestion_counts() -> dict[str, int]:
    return sq.counts(get_driver())


@router.post("", response_model=SuggestionOut, status_code=201)
def create_suggestion(body: SuggestionCreate, user: str = Depends(get_current_user)):
    row = sq.create_suggestion(
        get_driver(), text=body.text, detail=body.detail, source="user", created_by=user
    )
    return svc.to_out(row, user)


@router.patch("/{suggestion_id}", response_model=SuggestionOut)
def update_suggestion(suggestion_id: str, body: SuggestionPatch, user: str = Depends(get_current_user)):
    """Status: admins. Text and detail: the author or an admin."""
    row = _get_or_404(suggestion_id)
    fields = body.model_dump(exclude_none=True)
    admin = _is_admin(user)
    if "status" in fields and not admin:
        raise HTTPException(status_code=403, detail="Only an admin can change the status")
    if ("text" in fields or "detail" in fields) and not (admin or row.get("created_by") == user):
        raise HTTPException(status_code=403, detail="Only the author or an admin can edit this suggestion")
    if not fields:
        return svc.to_out(row, user)
    updated = sq.update_suggestion(get_driver(), suggestion_id, fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return svc.to_out(updated, user)


@router.post("/{suggestion_id}/vote", response_model=SuggestionOut)
def vote(suggestion_id: str, user: str = Depends(get_current_user)):
    """Toggle the current user's vote."""
    _get_or_404(suggestion_id)
    row = sq.toggle_vote(get_driver(), suggestion_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return svc.to_out(row, user)


@router.delete("/{suggestion_id}", status_code=204)
def delete_suggestion(suggestion_id: str, user: str = Depends(get_current_user)):
    row = _get_or_404(suggestion_id)
    if not (row.get("created_by") == user or _is_admin(user)):
        raise HTTPException(status_code=403, detail="Only the author or an admin can delete this suggestion")
    sq.delete_suggestion(get_driver(), suggestion_id)
    return Response(status_code=204)
