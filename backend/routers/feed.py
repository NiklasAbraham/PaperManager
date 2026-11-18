"""Paper feed HTTP API (.specs/018_paper_feed.md).

The router is always mounted so the app can ask ``GET /feed/status`` whether the feed is on.
When ``PAPER_FEED`` is off every other route answers 404 and nothing else happens.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints, field_validator

from db.connection import get_driver
from services.auth import get_current_user
from services.feed import config, pipeline, ranking
from services.feed.store import get_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/feed", tags=["feed"], dependencies=[Depends(get_current_user)])

Source = Literal["arxiv", "biorxiv", "medrxiv"]
Category = Annotated[str, StringConstraints(pattern=config.CATEGORY_RE.pattern, max_length=40)]


def require_enabled() -> None:
    if not config.enabled():
        raise HTTPException(status_code=404, detail="Not found")


on = [Depends(require_enabled)]


class ConfigBody(BaseModel):
    sources: list[Source] = Field(default_factory=lambda: ["arxiv"], max_length=3)
    arxiv_categories: list[Category] = Field(default_factory=list, max_length=config.MAX_CATEGORIES)
    digest_days: int = Field(config.DIGEST_DAYS_DEFAULT, ge=config.DIGEST_DAYS_MIN, le=config.DIGEST_DAYS_MAX)
    min_score: float = Field(0.0, ge=0.0, le=1.0)

    @field_validator("sources", "arxiv_categories")
    @classmethod
    def _unique(cls, v: list) -> list:
        return list(dict.fromkeys(v))


class RateBody(BaseModel):
    value: Literal[1, -1]


class AddBody(BaseModel):
    project_id: str | None = None


def _may_refresh(user: str) -> bool:
    from db.queries import users as users_q
    try:
        driver = get_driver()
        return bool(users_q.is_user_admin(driver, user)) or len(users_q.list_users(driver)) <= 1
    except Exception:  # noqa: BLE001 — when in doubt, no
        log.exception("Admin check failed for %s", user)
        return False


def _candidate_or_404(cid: str):
    cand = get_store().get(cid)
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return cand


@router.get("/status")
def feed_status(user: str = Depends(get_current_user)) -> dict:
    """``{"enabled": false}`` when the feed is off, otherwise the refresh state and the model facts."""
    if not config.enabled():
        return {"enabled": False}
    store = get_store()
    last = store.last_run()
    counts = store.counts()
    info = ranking.user_info(user)
    next_refresh = None
    if last and last.get("finished_at"):
        try:
            next_refresh = (datetime.fromisoformat(last["finished_at"])
                            + timedelta(seconds=config.interval_seconds())).isoformat(timespec="seconds")
        except ValueError:
            pass
    return {
        "enabled": True,
        "state": "refreshing" if pipeline.is_running() else "idle",
        "last_refresh": last["finished_at"] if last else None,
        "next_refresh": next_refresh,
        "candidates": counts["candidates"],
        "embedded": counts["embedded"],
        "mode": info.get("mode"),
        "positives": info.get("positives"),
        "quality": info.get("quality"),
        "error": last["error"] if last else None,
    }


@router.get("/config", dependencies=on)
def get_config(user: str = Depends(get_current_user)) -> dict:
    return (get_store().get_config(user) or config.FeedConfig()).to_dict()


@router.put("/config", dependencies=on)
def put_config(body: ConfigBody, user: str = Depends(get_current_user)) -> dict:
    cfg = config.FeedConfig(sources=body.sources, arxiv_categories=body.arxiv_categories,
                            digest_days=body.digest_days, min_score=body.min_score)
    get_store().set_config(user, cfg)
    return cfg.to_dict()


@router.get("", dependencies=on)
def feed(
    days: int | None = Query(None, ge=1, le=config.DIGEST_DAYS_MAX),
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    include_rated: bool = False,
    source: Source | None = None,
    user: str = Depends(get_current_user),
) -> dict:
    """The ranked digest for the current user."""
    store = get_store()
    cfg = store.get_config(user) or config.FeedConfig()
    out = ranking.digest(get_driver(), store, user, days=days, skip=skip, limit=limit,
                         include_rated=include_rated, source=source)
    out["configured"] = bool(cfg.arxiv_categories) or any(s != "arxiv" for s in cfg.sources)
    return out


@router.post("/refresh", dependencies=on, status_code=202)
def refresh_now(user: str = Depends(get_current_user)) -> dict:
    """Start a refresh now (admins, or anybody on an instance with a single user). 409 while one runs."""
    if not _may_refresh(user):
        raise HTTPException(status_code=403, detail="Only an admin can start a refresh")
    if not pipeline.start_refresh_async():
        raise HTTPException(status_code=409, detail="A refresh is already running")
    return {"started": True}


@router.post("/{cid:path}/rate", dependencies=on)
def rate(cid: str, body: RateBody, user: str = Depends(get_current_user)) -> dict:
    _candidate_or_404(cid)
    get_store().set_label(user, cid, body.value)
    return {"id": cid, "my_label": body.value}


@router.post("/{cid:path}/dismiss", dependencies=on)
def dismiss(cid: str, user: str = Depends(get_current_user)) -> dict:
    _candidate_or_404(cid)
    get_store().set_label(user, cid, 0)
    return {"id": cid, "my_label": 0}


@router.delete("/{cid:path}/label", dependencies=on)
def clear_label(cid: str, user: str = Depends(get_current_user)) -> dict:
    get_store().clear_label(user, cid)
    return {"id": cid, "my_label": None}


@router.post("/{cid:path}/add", dependencies=on)
def add_to_library(cid: str, body: AddBody | None = None, user: str = Depends(get_current_user)) -> dict:
    """Add the paper through the normal URL ingest, optionally to a project, and count it as a thumbs-up."""
    from db.queries.visibility import can_see_project
    from models.schemas import IngestFromUrlBody
    from routers.papers import ingest_from_url

    cand = _candidate_or_404(cid)
    project_id = body.project_id if body else None
    if project_id and not can_see_project(get_driver(), project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    paper = ingest_from_url(IngestFromUrlBody(url=cand.url, project_id=project_id), x_user_name=user)
    get_store().set_label(user, cid, 1)
    paper_id = paper.get("id") if isinstance(paper, dict) else getattr(paper, "id", None)
    return {"id": cid, "my_label": 1, "paper_id": paper_id}
