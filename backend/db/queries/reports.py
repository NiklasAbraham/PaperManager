"""Neo4j queries for Report nodes (.specs/014_reports.md).

A report is ``(:Report {id, owner, title, question, ...})`` with a
``(:Report)-[:CITES_PAPER {n}]->(:Paper)`` edge for every cited paper. Progress writes are
guarded: they only land while the report is ``queued`` or ``running``, so a cancelled or deleted
report is never revived by a job that is still winding down.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from neo4j import Driver

log = logging.getLogger(__name__)

ACTIVE = ("queued", "running")
MAX_STEPS = 50

# Everything except the (large) markdown, as a Cypher map projection, for lists.
_SUMMARY_PROJECTION = ", ".join(
    "." + name
    for name in (
        "id owner title question project_id project_name length model status stage progress "
        "steps_json error paper_count word_count created_at updated_at finished_at"
    ).split()
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_step(steps_json: str | None, message: str, ts: str | None = None) -> str:
    """Return ``steps_json`` with one more ``{"ts", "message"}`` line, keeping the last 50."""
    try:
        steps = json.loads(steps_json or "[]")
    except (TypeError, ValueError):
        steps = []
    if not isinstance(steps, list):
        steps = []
    steps.append({"ts": ts or _now(), "message": message})
    return json.dumps(steps[-MAX_STEPS:], ensure_ascii=False)


def create_report(driver: Driver, data: dict) -> dict:
    """Create a queued report owned by ``data["owner"]`` and return it."""
    now = _now()
    props = {
        "id": str(uuid.uuid4()),
        "owner": data["owner"],
        "title": data.get("title") or "",
        "question": data.get("question") or "",
        "project_id": data.get("project_id") or "",
        "project_name": data.get("project_name") or "",
        "paper_ids_json": json.dumps(list(data.get("paper_ids") or [])),
        "length": data.get("length") or "standard",
        "model": data.get("model") or "fast",
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "steps_json": append_step("[]", "Queued", now),
        "markdown": "",
        "error": "",
        "paper_count": 0,
        "word_count": 0,
        "created_at": now,
        "updated_at": now,
        "finished_at": "",
    }
    with driver.session() as session:
        record = session.run("CREATE (r:Report $props) RETURN r", props=props).single()
        return dict(record["r"])


def get_report(driver: Driver, report_id: str) -> dict | None:
    """The full report node (with markdown), or None."""
    with driver.session() as session:
        record = session.run("MATCH (r:Report {id: $id}) RETURN r", id=report_id).single()
        return dict(record["r"]) if record else None


def list_reports(driver: Driver, owner: str | None = None, limit: int = 500) -> list[dict]:
    """Reports without their markdown, newest first; ``owner=None`` lists every user's."""
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (r:Report)
            WHERE $owner IS NULL OR r.owner = $owner
            RETURN r {{ {_SUMMARY_PROJECTION} }} AS rep
            ORDER BY rep.created_at DESC
            LIMIT $limit
            """,
            owner=owner,
            limit=limit,
        )
        return [dict(rec["rep"]) for rec in result]


def is_active(driver: Driver, report_id: str) -> bool:
    """True while the report exists and is queued or running."""
    with driver.session() as session:
        record = session.run(
            "MATCH (r:Report {id: $id}) RETURN r.status AS status", id=report_id
        ).single()
    return bool(record and record["status"] in ACTIVE)


def update_progress(
    driver: Driver,
    report_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
    step: str | None = None,
    title: str | None = None,
    paper_count: int | None = None,
) -> bool:
    """Persist status / stage / progress and append a step line.

    Returns False (and writes nothing) when the report is gone or no longer queued/running,
    which is how a job learns it was cancelled or deleted.
    """
    with driver.session() as session:
        record = session.run(
            "MATCH (r:Report {id: $id}) WHERE r.status IN $active RETURN r.steps_json AS steps",
            id=report_id,
            active=list(ACTIVE),
        ).single()
        if not record:
            return False
        now = _now()
        props: dict = {"updated_at": now}
        if status is not None:
            props["status"] = status
        if stage is not None:
            props["stage"] = stage
        if progress is not None:
            props["progress"] = max(0, min(100, int(progress)))
        if title:
            props["title"] = title
        if paper_count is not None:
            props["paper_count"] = int(paper_count)
        if step:
            props["steps_json"] = append_step(record["steps"], step, now)
        updated = session.run(
            "MATCH (r:Report {id: $id}) WHERE r.status IN $active SET r += $props RETURN r.id AS id",
            id=report_id,
            active=list(ACTIVE),
            props=props,
        ).single()
        return updated is not None


def finish_report(
    driver: Driver,
    report_id: str,
    *,
    title: str,
    markdown: str,
    word_count: int,
    cited: list[dict],
) -> bool:
    """Mark the report done, store the text and write one CITES_PAPER edge per cited paper.

    ``cited`` is ``[{"id": paper_id, "n": number_in_reference_list}]``. False when the report
    was cancelled or deleted in the meantime.
    """
    now = _now()
    with driver.session() as session:
        record = session.run(
            "MATCH (r:Report {id: $id}) WHERE r.status IN $active RETURN r.steps_json AS steps",
            id=report_id,
            active=list(ACTIVE),
        ).single()
        if not record:
            return False
        props = {
            "status": "done",
            "stage": "done",
            "progress": 100,
            "title": title,
            "markdown": markdown,
            "word_count": int(word_count),
            "paper_count": len(cited),
            "error": "",
            "steps_json": append_step(record["steps"], "Report saved", now),
            "updated_at": now,
            "finished_at": now,
        }
        session.run("MATCH (r:Report {id: $id}) SET r += $props", id=report_id, props=props).consume()
        session.run("MATCH (r:Report {id: $id})-[c:CITES_PAPER]->() DELETE c", id=report_id).consume()
        if cited:
            session.run(
                """
                MATCH (r:Report {id: $id})
                UNWIND $cited AS c
                MATCH (p:Paper {id: c.id})
                MERGE (r)-[e:CITES_PAPER]->(p)
                SET e.n = c.n
                """,
                id=report_id,
                cited=cited,
            ).consume()
    return True


def fail_report(driver: Driver, report_id: str, error: str) -> bool:
    """Mark the report failed with an error text (at most 1000 characters)."""
    return _finish_with(driver, report_id, "failed", (error or "Unknown error")[:1000])


def cancel_report(driver: Driver, report_id: str) -> bool:
    """Mark a queued or running report cancelled. False when it was not active."""
    return _finish_with(driver, report_id, "cancelled", "")


def _finish_with(driver: Driver, report_id: str, status: str, error: str) -> bool:
    now = _now()
    with driver.session() as session:
        record = session.run(
            "MATCH (r:Report {id: $id}) WHERE r.status IN $active RETURN r.steps_json AS steps",
            id=report_id,
            active=list(ACTIVE),
        ).single()
        if not record:
            return False
        message = {"failed": "Failed: " + error[:200], "cancelled": "Cancelled"}.get(status, status)
        session.run(
            "MATCH (r:Report {id: $id}) WHERE r.status IN $active SET r += $props",
            id=report_id,
            active=list(ACTIVE),
            props={
                "status": status,
                "stage": status,
                "error": error,
                "steps_json": append_step(record["steps"], message, now),
                "updated_at": now,
                "finished_at": now,
            },
        ).consume()
    return True


def fail_interrupted(driver: Driver) -> int:
    """Mark every queued / running report failed after a restart. Returns how many."""
    now = _now()
    with driver.session() as session:
        record = session.run(
            """
            MATCH (r:Report) WHERE r.status IN $active
            SET r.status = 'failed', r.stage = 'failed', r.error = $error,
                r.updated_at = $now, r.finished_at = $now
            RETURN count(r) AS n
            """,
            active=list(ACTIVE),
            error="Interrupted by a server restart",
            now=now,
        ).single()
    return int(record["n"]) if record else 0


def delete_report(driver: Driver, report_id: str) -> bool:
    """Delete the report and its CITES_PAPER edges (never the papers)."""
    with driver.session() as session:
        record = session.run(
            "MATCH (r:Report {id: $id}) DETACH DELETE r RETURN count(*) AS n", id=report_id
        ).single()
    return bool(record and record["n"])


def report_papers(driver: Driver, report_id: str) -> list[dict]:
    """The papers a report cites, ``[{"id", "title", "year", "n"}]`` in reference order."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (:Report {id: $id})-[c:CITES_PAPER]->(p:Paper)
            RETURN p.id AS id, p.title AS title, p.year AS year, c.n AS n
            ORDER BY c.n ASC
            """,
            id=report_id,
        )
        return [dict(rec) for rec in result]
