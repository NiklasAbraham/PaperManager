"""Project concept map: build it with Gemma in the background, serve it as one graph."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.concept_map import (
    get_project_map,
    unmapped_project_papers,
    project_papers_for_mapping,
    project_vocabulary,
    save_paper_concepts,
    set_mapping_error,
)
from db.queries.projects import get_project
from db.queries.visibility import can_see_project
from config import settings
from services.auth import get_current_user
from services.concept_map import ConceptMapError, extract_paper_concepts

log = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["concept-map"], dependencies=[Depends(get_current_user)])

BUILD_CONCURRENCY = 2
# Auto-mapping: how often to look for unmapped project papers, and how long a
# paper without a summary waits (its upload pipeline may still be writing one).
SWEEP_INTERVAL_S = 600
SUMMARY_GRACE = timedelta(minutes=30)

# One build job per project. Model calls run in parallel; saves are serialised so
# two papers introducing the same new concept cannot both create it.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_save_lock = threading.Lock()
# Gemma calls in flight across all projects: more than two at once time out on the proxy.
_llm_slots = threading.Semaphore(BUILD_CONCURRENCY)


class BuildBody(BaseModel):
    # Re-extract papers that are already mapped (otherwise only new papers run).
    force: bool = False
    paper_ids: list[str] | None = None


class JobOut(BaseModel):
    total: int = 0
    done: int = 0
    failed: int = 0
    running: bool = False
    errors: list[dict] = []


def _project_or_404(project_id: str) -> dict:
    driver = get_driver()
    project = get_project(driver, project_id)
    if not project or not can_see_project(driver, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _job_status(project_id: str) -> JobOut:
    with _jobs_lock:
        job = _jobs.get(project_id)
        if not job:
            return JobOut()
        return JobOut(total=job["total"], done=job["done"], failed=job["failed"],
                      running=job["running"], errors=list(job["errors"][-20:]))


def _map_one(project_id: str, paper: dict, job: dict) -> None:
    driver = get_driver()
    error = None
    try:
        vocabulary = project_vocabulary(driver, project_id)
        with _llm_slots:
            extraction = extract_paper_concepts(paper, paper["authors"], paper["claims"], vocabulary)
        with _save_lock:
            save_paper_concepts(driver, paper["id"], extraction)
    except ConceptMapError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 — one paper must not stop the job
        log.exception("Concept map: paper %s failed", paper["id"])
        error = f"{type(exc).__name__}: {exc}"
    if error:
        try:
            set_mapping_error(driver, paper["id"], error)
        except Exception:  # noqa: BLE001
            log.exception("Concept map: could not store error for %s", paper["id"])
    with _jobs_lock:
        job["done"] += 1
        if error:
            job["failed"] += 1
            job["errors"].append({"paper_id": paper["id"], "title": paper.get("title"), "error": error})


def _run(project_id: str, papers: list[dict], job: dict) -> None:
    try:
        with ThreadPoolExecutor(max_workers=BUILD_CONCURRENCY) as pool:
            for f in [pool.submit(_map_one, project_id, p, job) for p in papers]:
                f.result()
    finally:
        with _jobs_lock:
            job["running"] = False
        log.info("Concept map for project %s: %d papers, %d failed", project_id, job["total"], job["failed"])


@router.get("/{project_id}/concept-map")
def get_concept_map(project_id: str):
    _project_or_404(project_id)
    return {**get_project_map(get_driver(), project_id), "job": _job_status(project_id)}


@router.get("/{project_id}/concept-map/status", response_model=JobOut)
def get_status(project_id: str):
    _project_or_404(project_id)
    return _job_status(project_id)


@router.post("/{project_id}/concept-map/build", response_model=JobOut)
def build(project_id: str, body: BuildBody | None = None):
    """Map every paper of the project that has no concepts yet (all of them with force)."""
    body = body or BuildBody()
    _project_or_404(project_id)
    papers = project_papers_for_mapping(get_driver(), project_id)
    if body.paper_ids:
        wanted = set(body.paper_ids)
        papers = [p for p in papers if p["id"] in wanted]
    if not body.force:
        papers = [p for p in papers if not p["mapped_at"]]
    if not _start_job(project_id, papers):
        raise HTTPException(status_code=409, detail="A build is already running for this project")
    return _job_status(project_id)


def _start_job(project_id: str, papers: list[dict]) -> bool:
    """Start a build over *papers*; False if one is already running for the project."""
    papers = [p for p in papers if p["abstract"] or p["summary"] or p["claims"] or p["raw_text"]]
    with _jobs_lock:
        running = _jobs.get(project_id)
        if running and running["running"]:
            return False
        if not papers:
            return True
        job = {"total": len(papers), "done": 0, "failed": 0, "running": True, "errors": []}
        _jobs[project_id] = job
        threading.Thread(target=_run, args=(project_id, papers, job),
                         name=f"concept-map-{project_id}", daemon=True).start()
    return True


def sweep_once() -> int:
    """Start a build for every project with ready, unmapped papers; return how many papers."""
    driver = get_driver()
    ready_before = (datetime.now(timezone.utc) - SUMMARY_GRACE).isoformat()
    started = 0
    for project_id, ids in unmapped_project_papers(driver, ready_before).items():
        wanted = set(ids)
        papers = [p for p in project_papers_for_mapping(driver, project_id) if p["id"] in wanted]
        if papers and _start_job(project_id, papers):
            log.info("Concept map auto-build: project %s, %d new papers", project_id, len(papers))
            started += len(papers)
    return started


def _sweep_forever() -> None:
    time.sleep(60)  # let startup finish
    from services import heartbeat

    while True:
        ok, error = True, None
        try:
            sweep_once()
        except Exception as exc:  # noqa: BLE001 — never kill the sweeper
            log.exception("Concept map sweep failed")
            ok, error = False, f"{type(exc).__name__}: {exc}"
        heartbeat.beat("concept-map-sweeper", ok=ok, error=error, interval_s=SWEEP_INTERVAL_S)
        time.sleep(SWEEP_INTERVAL_S)


def start_auto_mapping() -> None:
    """Map new project papers in the background (CONCEPT_MAP_AUTO=false turns it off)."""
    if settings.concept_map_auto:
        threading.Thread(target=_sweep_forever, name="concept-map-sweeper", daemon=True).start()
        log.info("Concept map auto-mapping on (every %ds)", SWEEP_INTERVAL_S)
