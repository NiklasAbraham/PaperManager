"""HTTP API for reports (.specs/014_reports.md): create, list, view, export, cancel, delete."""
from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from config import settings
from db.connection import get_driver
from db.queries import reports as rq
from services.auth import get_current_user
from services.reports import jobs, llm, render, retrieval

log = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])

LENGTHS = ["short", "standard", "long"]
_SUMMARY_KEYS = (
    "id title question project_id project_name status stage progress model length owner "
    "created_at updated_at finished_at paper_count word_count error"
).split()


class ReportCreate(BaseModel):
    question: str | None = Field(default=None, max_length=4000)
    project_id: str | None = None
    paper_ids: list[str] | None = Field(default=None, max_length=200)
    length: Literal["short", "standard", "long"] = "standard"
    model: Literal["fast", "claude", "claude-work"] = "fast"


def _is_admin(username: str) -> bool:
    try:
        from db.queries.users import is_user_admin

        return bool(is_user_admin(get_driver(), username))
    except Exception as exc:  # noqa: BLE001
        log.warning("admin check failed for %s: %s", username, exc)
        return False


def _summary(report: dict) -> dict:
    out = {k: report.get(k) for k in _SUMMARY_KEYS}
    for key in ("title", "question", "project_id", "project_name", "stage", "error", "finished_at"):
        out[key] = out[key] or ""
    for key in ("progress", "paper_count", "word_count"):
        out[key] = int(out[key] or 0)
    return out


def _steps(report: dict) -> list[dict]:
    try:
        steps = json.loads(report.get("steps_json") or "[]")
    except (TypeError, ValueError):
        return []
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def _load(report_id: str, user: str) -> dict:
    """The report if it exists and belongs to ``user`` (or ``user`` is an admin), else 404."""
    report = rq.get_report(get_driver(), report_id)
    if not report or (report.get("owner") != user and not _is_admin(user)):
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/options")
def options(user: str = Depends(get_current_user)) -> dict:
    """The models a report can be written with and which of them are usable now."""
    return {"models": llm.available_models(user), "lengths": LENGTHS, "default_model": llm.DEFAULT_MODEL}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_report(body: ReportCreate, user: str = Depends(get_current_user)) -> dict:
    """Queue a report on a question and/or a project; it is written in the background."""
    question = (body.question or "").strip()
    project_id = (body.project_id or "").strip()
    paper_ids = [p for p in (body.paper_ids or []) if p]
    if not question and not project_id:
        raise HTTPException(status_code=422, detail="Give a question or a project")
    chosen = next((m for m in llm.available_models(user) if m["id"] == body.model), None)
    if not chosen or not chosen["available"]:
        raise HTTPException(status_code=422, detail=f"The model '{body.model}' is not available")
    driver = get_driver()
    project_name = ""
    if project_id:
        project = retrieval.project_info(driver, project_id, user)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project_name = project["name"]
    report = rq.create_report(
        driver,
        {
            "owner": user,
            "question": question,
            "project_id": project_id,
            "project_name": project_name,
            "paper_ids": paper_ids,
            "length": body.length,
            "model": body.model,
            "title": question[:120] or project_name,
        },
    )
    jobs.start(report["id"])
    return _summary(report)


@router.get("")
def list_reports(show_all: bool = Query(False, alias="all"), user: str = Depends(get_current_user)) -> list[dict]:
    """The caller's reports, newest first; admins may pass ``all=true`` for everyone's."""
    owner = None if show_all and _is_admin(user) else user
    return [_summary(r) for r in rq.list_reports(get_driver(), owner)]


@router.get("/{report_id}")
def get_report(report_id: str, user: str = Depends(get_current_user)) -> dict:
    """One report with its text, progress lines and cited papers."""
    report = _load(report_id, user)
    out = _summary(report)
    out["markdown"] = report.get("markdown") or ""
    out["steps"] = _steps(report)
    out["papers"] = [
        {"id": p["id"], "title": p.get("title") or "", "year": p.get("year"), "n": p.get("n")}
        for p in rq.report_papers(get_driver(), report_id)
    ]
    return out


@router.get("/{report_id}/export")
def export_report(
    report_id: str,
    format: Literal["md", "html"] = Query("md"),
    user: str = Depends(get_current_user),
) -> Response:
    """Download a finished report as Markdown or as one self-contained HTML page."""
    report = _load(report_id, user)
    if report.get("status") != "done":
        raise HTTPException(status_code=409, detail="The report is not finished yet")
    markdown = report.get("markdown") or ""
    slug = render.slugify(report.get("title") or "report")
    if format == "html":
        content = render.to_html(
            markdown,
            model_label=llm.model_label(report.get("model") or "fast"),
            date=report.get("finished_at") or report.get("created_at"),
            frontend_url=settings.frontend_url,
            papers=report.get("paper_count"),
        )
        media = "text/html; charset=utf-8"
    else:
        content, media = markdown, "text/markdown; charset=utf-8"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{slug}.{format}"'},
    )


@router.post("/{report_id}/cancel")
def cancel_report(report_id: str, user: str = Depends(get_current_user)) -> dict:
    """Stop a queued or running report (a finished one is returned unchanged)."""
    report = _load(report_id, user)
    if report.get("status") in rq.ACTIVE:
        rq.cancel_report(get_driver(), report_id)
        jobs.cancel(report_id)
        report = rq.get_report(get_driver(), report_id) or report
    return _summary(report)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: str, user: str = Depends(get_current_user)) -> Response:
    """Delete a report (cancelling it first if it is still running)."""
    report = _load(report_id, user)
    if report.get("status") in rq.ACTIVE:
        jobs.cancel(report_id)
    rq.delete_report(get_driver(), report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
