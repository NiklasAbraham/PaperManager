"""Pull a cited reference into the library in the background.

The References tab used to open the upload confirm modal plus the onboarding
wizard for every "Pull". Now a pull is a background job that does exactly what
a drag-and-drop upload does, without asking anything:

1. Fetch the open-access PDF (arXiv, bioRxiv/medRxiv, Unpaywall for other DOIs)
   and send it through ``POST /papers/upload`` — Docling text, Drive, summary,
   embedding, topics, claims, references, figures. Without a PDF the paper is
   added metadata-only via ``/papers/from-url-full``.
2. Merge with the existing reference stub: the upload enriches the stub in
   place when its DOI or title matches; when the pipeline ended up on another
   node (a different DOI form, an already uploaded copy) the stub is merged
   into that node, so the citation link and its tags move with it.
3. Apply the tags the tag suggester picks from the existing tag set, save the
   paper's own references (if asked), and regenerate a failed summary.

Jobs run one at a time on a single worker thread (one GPU is shared by Docling
and the LLM proxy) and live in memory: the frontend polls ``list_jobs``.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ref-import")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_KEEP_FINISHED_S = 6 * 3600

_ARXIV_RE = re.compile(r"(?:arxiv[:/.]\s*|10\.48550/arxiv\.)(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
_BARE_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s?#]+)", re.I)


def entry_for(doi: str | None, url: str | None) -> dict | None:
    """Map a reference's DOI / arXiv id / URL to a `pdf_import` entry."""
    for raw in (doi, url):
        if not raw:
            continue
        s = raw.strip()
        m = _ARXIV_RE.search(s)
        if m:
            return {"arxiv": re.sub(r"v\d+$", "", m.group(1))}
        if _BARE_ARXIV_RE.match(s):
            return {"arxiv": re.sub(r"v\d+$", "", s)}
        m = _DOI_RE.search(s)
        if m:
            d = m.group(1).rstrip(".")
            if d.startswith("10.1101/"):
                return {"biorxiv": d}
            return {"doi": d}
        if s.lower().endswith(".pdf") and s.startswith("http"):
            return {"pdf_url": s}
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _update(job_id: str, **kw) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kw, updated_at=_now(), _t=time.time())


def _prune() -> None:
    cutoff = time.time() - _KEEP_FINISHED_S
    with _lock:
        for jid in [j for j, v in _jobs.items() if v["status"] in ("done", "error") and v["_t"] < cutoff]:
            del _jobs[jid]


def list_jobs(source_paper_id: str | None = None) -> list[dict]:
    _prune()
    with _lock:
        jobs = [_public(j) for j in _jobs.values()
                if not source_paper_id or j.get("source_paper_id") == source_paper_id]
    return sorted(jobs, key=lambda j: j["created_at"])


def get_job(job_id: str) -> dict | None:
    with _lock:
        j = _jobs.get(job_id)
        return _public(j) if j else None


def start_job(
    *,
    stub_id: str | None,
    source_paper_id: str | None,
    doi: str | None,
    url: str | None,
    title: str | None,
    user_name: str | None,
    claims_model: str = "litellm",
    skip_embedding: bool = False,
    save_references: bool = True,
) -> dict:
    """Queue a reference import; an active job for the same stub/DOI is reused."""
    key = stub_id or (doi or url or "").lower()
    with _lock:
        for j in _jobs.values():
            if j["_key"] == key and j["status"] in ("queued", "running"):
                return _public(j)
        job = {
            "id": uuid.uuid4().hex,
            "status": "queued",
            "step": "Waiting in queue",
            "stub_id": stub_id,
            "source_paper_id": source_paper_id,
            "doi": doi,
            "url": url,
            "title": title or doi or url or "",
            "paper_id": None,
            "pdf": None,
            "tags_applied": [],
            "merged": False,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
            "_key": key,
            "_t": time.time(),
        }
        _jobs[job["id"]] = job
    _executor.submit(
        _run, job["id"], user_name=user_name, claims_model=claims_model,
        skip_embedding=skip_embedding, save_references=save_references,
    )
    return _public(job)


# ── The job ────────────────────────────────────────────────────────────────────

def _headers(user_name: str | None) -> dict:
    from services.pdf_import import api_headers
    h = api_headers()
    if user_name:
        h["X-User-Name"] = user_name
    return h


def _detail_409(r: httpx.Response) -> str | None:
    import json
    try:
        return json.loads(r.json()["detail"])["existing_id"]
    except Exception:  # noqa: BLE001
        return None


def _upload(client, headers, data: bytes, name: str, claims_model: str, skip_embedding: bool,
            stub_id: str | None) -> dict:
    from services.pdf_import import API
    form = {"claims_model": claims_model, "skip_embedding": str(skip_embedding).lower()}
    if stub_id:
        form["stub_id"] = stub_id
    r = client.post(
        f"{API}/papers/upload",
        files={"file": (name, data, "application/pdf")},
        data=form,
        headers=headers, timeout=1800,
    )
    if r.status_code == 409 and _detail_409(r):
        return {"id": _detail_409(r), "references_found": [], "existing": True}
    r.raise_for_status()
    return r.json()


def _from_url(client, headers, url: str, stub_id: str | None) -> dict:
    from services.pdf_import import API
    r = client.post(f"{API}/papers/from-url-full", json={"url": url, "stub_id": stub_id},
                    headers=headers, timeout=900)
    if r.status_code == 409 and _detail_409(r):
        return {"id": _detail_409(r), "references_found": [], "existing": True}
    r.raise_for_status()
    return r.json()


def _metadata_url(entry: dict | None, doi: str | None, url: str | None) -> str | None:
    if url:
        return url
    if entry and entry.get("arxiv"):
        return f"https://arxiv.org/abs/{entry['arxiv']}"
    d = (entry or {}).get("doi") or (entry or {}).get("biorxiv") or doi
    return f"https://doi.org/{d}" if d else None


def _auto_tags(client, headers, paper: dict) -> list[str]:
    """Apply the suggester's picks from the existing tag set (no new tags invented)."""
    from services.pdf_import import API
    title = paper.get("title") or ""
    if not title:
        return []
    r = client.post(f"{API}/tags/suggest", json={"title": title, "abstract": paper.get("abstract")},
                    headers=headers, timeout=180)
    if r.status_code >= 300:
        return []
    picks = [t for t in (r.json().get("existing") or []) if t]
    for name in picks:
        client.post(f"{API}/papers/{paper['id']}/tags", json={"name": name}, headers=headers, timeout=30)
    return picks


def _run(job_id: str, *, user_name, claims_model, skip_embedding, save_references) -> None:
    from db.connection import get_driver
    from db.queries.papers import get_paper
    from db.queries.tags import tag_paper
    from services.pdf_import import API, fetch_pdf, pdf_name, regenerate_summary

    job = get_job(job_id)
    if not job:
        return
    _update(job_id, status="running", step="Looking for an open-access PDF")
    driver = get_driver()
    try:
        stub = get_paper(driver, job["stub_id"]) if job["stub_id"] else None
        doi = job["doi"] or (stub or {}).get("doi")
        if stub and stub.get("drive_file_id"):
            _update(job_id, status="done", step="Already in library", paper_id=stub["id"], pdf=True)
            return

        entry = entry_for(doi, job["url"])
        headers = _headers(user_name)
        with httpx.Client() as client:
            data, source = (None, "no DOI or arXiv id")
            if entry:
                data, source = fetch_pdf(client, entry, attempts=2, backoff=30)
            if data:
                _update(job_id, step="Importing PDF (summary, figures, claims…)", pdf=True)
                paper = _upload(client, headers, data, pdf_name(entry), claims_model, skip_embedding,
                                stub and stub["id"])
            else:
                murl = _metadata_url(entry, doi, job["url"])
                if not murl:
                    raise RuntimeError(f"Nothing to import from: {source}")
                log.info("Reference import without PDF (%s) | %s", source, murl)
                _update(job_id, step="No open PDF — importing metadata", pdf=False)
                paper = _from_url(client, headers, murl, stub and stub["id"])

            paper_id = paper["id"]

            # Merge the reference stub into whatever node the pipeline landed on.
            merged = False
            if stub and paper_id != stub["id"] and get_paper(driver, stub["id"]):
                from services.paper_merge import merge_papers
                _update(job_id, step="Merging with the existing reference")
                merge_papers(driver, keep_id=paper_id, remove_ids=[stub["id"]], dry_run=False)
                merged = True
            elif not stub and job["source_paper_id"]:
                # No stub (URL-only reference): make sure the citation link exists.
                with driver.session() as s:
                    s.run("MATCH (a:Paper {id: $a}), (b:Paper {id: $b}) WHERE a <> b "
                          "MERGE (a)-[:CITES]->(b)", a=job["source_paper_id"], b=paper_id)
            tag_paper(driver, paper_id, "from-references")
            _update(job_id, paper_id=paper_id, merged=merged)

            full = get_paper(driver, paper_id) or {}
            _update(job_id, step="Tagging", title=full.get("title") or job["title"])
            try:
                tags = _auto_tags(client, headers, full | {"id": paper_id})
                _update(job_id, tags_applied=tags)
            except Exception as exc:  # noqa: BLE001
                log.warning("Reference import: auto tags failed (non-fatal) | %s", exc)

            refs = paper.get("references_found") or []
            if save_references and refs:
                _update(job_id, step="Saving its references")
                try:
                    client.post(f"{API}/papers/{paper_id}/references", json={"references": refs},
                                headers=headers, timeout=600)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Reference import: saving references failed (non-fatal) | %s", exc)

            if not paper.get("existing"):
                regenerate_summary(client, headers, driver, paper_id)

        _update(job_id, status="done", step="Done")
        log.info("Reference import done | job=%s | paper=%s | merged=%s", job_id, paper_id, merged)
    except Exception as exc:  # noqa: BLE001
        log.warning("Reference import failed | job=%s | %s", job_id, exc)
        _update(job_id, status="error", step="Failed", error=str(exc)[:300])
