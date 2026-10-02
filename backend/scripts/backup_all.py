"""Run every export PaperManager offers and write them to one backup directory.

Run inside the backend container, then copy the directory out:

    docker exec -w /app papermanager-backend-1 \
        python scripts/backup_all.py --out /tmp/pm_backup [--markdown MasterThesis]
    docker cp papermanager-backend-1:/tmp/pm_backup <host dir>

Contents (all through the app's own export endpoints, as the default user):

    library/snapshot.json        GET /export/snapshot  full graph, restorable via
                                                       POST /export/import/snapshot
    library/graph.ttl            GET /export/rdf       RDF Turtle (no raw_text)
    library/graph_csv.zip        GET /export/csv       one CSV per node/relation type
    library/library.bib          GET /export/bibtex    every paper
    projects/<name>/project.bib  GET /projects/{id}/export/bibtex
    projects/<name>/papers.csv   GET /projects/{id}/export/csv
    projects/<name>/conversations.md  GET /projects/{id}/export/conversations
    projects/<name>/markdown/    GET /export/papers/{id}/markdown, one file per
                                 paper (only for projects named with --markdown)
    manifest.json                sizes, SHA-256 and counts of everything above

PDFs and figure images live in Google Drive and are not part of these exports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from config import settings  # noqa: E402
from db.connection import get_driver  # noqa: E402
from services.auth import create_access_token, set_request_user  # noqa: E402

API = "http://localhost:8000"


def slug(text: str, n: int = 80) -> str:
    return re.sub(r"[^\w.-]+", "_", text).strip("_")[:n] or "untitled"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--markdown", action="append", default=[], metavar="PROJECT",
                    help="also export every paper of this project as Markdown (repeatable)")
    args = ap.parse_args()

    set_request_user(settings.default_user_name)
    driver = get_driver()
    token = create_access_token({"sub": settings.default_user_name}, timedelta(hours=6))
    headers = {"Authorization": f"Bearer {token}", "X-User-Name": settings.default_user_name}
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    errors: list[str] = []

    def save(rel: str, url: str) -> None:
        try:
            r = client.get(f"{API}{url}", headers=headers, timeout=1800)
            r.raise_for_status()
        except httpx.HTTPError as e:
            errors.append(f"{url}: {e}")
            print(f"FAIL {rel}: {e}", flush=True)
            return
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        files.append({"path": rel, "source": url, "bytes": len(r.content),
                      "sha256": hashlib.sha256(r.content).hexdigest()})
        print(f"ok   {rel} ({len(r.content):,} bytes)", flush=True)

    with driver.session() as s:
        projects = [dict(r) for r in s.run("MATCH (p:Project) RETURN p.id AS id, p.name AS name ORDER BY p.name")]
        counts = {r["label"]: r["n"] for r in s.run(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n")}

    with httpx.Client() as client:
        save("library/snapshot.json", "/export/snapshot")
        save("library/graph.ttl", "/export/rdf")
        save("library/graph_csv.zip", "/export/csv")
        save("library/library.bib", "/export/bibtex")
        for p in projects:
            d = f"projects/{slug(p['name'])}"
            save(f"{d}/project.bib", f"/projects/{p['id']}/export/bibtex")
            save(f"{d}/papers.csv", f"/projects/{p['id']}/export/csv")
            save(f"{d}/conversations.md", f"/projects/{p['id']}/export/conversations")
            if p["name"] in args.markdown or p["id"] in args.markdown:
                with driver.session() as s:
                    papers = [dict(r) for r in s.run(
                        "MATCH (x:Paper)-[:IN_PROJECT]->(:Project {id: $id}) RETURN x.id AS id, x.title AS title",
                        id=p["id"])]
                for x in papers:
                    save(f"{d}/markdown/{slug(x['title'] or x['id'])}_{x['id'][:8]}.md",
                         f"/export/papers/{x['id']}/markdown")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "node_counts": counts,
        "projects": projects,
        "files": files,
        "errors": errors,
        "not_included": "PDFs and figure images (Google Drive)",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"done: {len(files)} files, {len(errors)} errors -> {out}", flush=True)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
