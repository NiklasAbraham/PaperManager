"""Admin endpoints: clear paper data, seed defaults."""
import logging
from fastapi import APIRouter
from db.connection import get_driver
from services.drive import delete_file

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


@router.delete("/clear-papers")
def clear_papers():
    """
    Delete all Paper, Person, Note, and Figure nodes (and their Drive files).
    Tag and Topic nodes are preserved — they are the 'generic infrastructure'.
    Project nodes are also removed since they reference papers.
    Returns counts of deleted items.
    """
    driver = get_driver()
    counts: dict[str, int] = {}

    with driver.session() as session:
        # Collect drive file IDs before deleting
        fig_files = [
            r["fid"] for r in session.run(
                "MATCH (f:Figure) WHERE f.drive_file_id IS NOT NULL RETURN f.drive_file_id AS fid"
            ) if r["fid"]
        ]
        paper_files = [
            r["fid"] for r in session.run(
                "MATCH (p:Paper) WHERE p.drive_file_id IS NOT NULL RETURN p.drive_file_id AS fid"
            ) if r["fid"]
        ]

    # Delete Drive files (best-effort)
    for fid in fig_files + paper_files:
        try:
            delete_file(fid)
        except Exception as exc:
            log.warning("Drive delete failed (non-fatal) | %s", exc)

    with driver.session() as session:
        r = session.run("MATCH (n:Figure) DETACH DELETE n RETURN count(n) AS c").single()
        counts["figures"] = r["c"] if r else 0

        r = session.run("MATCH (n:Note) DETACH DELETE n RETURN count(n) AS c").single()
        counts["notes"] = r["c"] if r else 0

        r = session.run("MATCH (n:Person) DETACH DELETE n RETURN count(n) AS c").single()
        counts["people"] = r["c"] if r else 0

        r = session.run("MATCH (n:Project) DETACH DELETE n RETURN count(n) AS c").single()
        counts["projects"] = r["c"] if r else 0

        r = session.run("MATCH (n:Paper) DETACH DELETE n RETURN count(n) AS c").single()
        counts["papers"] = r["c"] if r else 0

    log.info("clear-papers | %s", counts)
    return counts


@router.post("/seed-defaults")
def seed_defaults():
    """Re-seed the default tags (idempotent — safe to run any time)."""
    from routers.tags import seed_default_tags, DEFAULT_TAGS
    seed_default_tags(get_driver())
    return {"seeded": len(DEFAULT_TAGS)}
