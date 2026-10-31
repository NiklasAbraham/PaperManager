"""Vet the DOIs / arXiv ids of existing citation stubs (papers tagged from-references).

    docker exec -w /app papermanager-backend-1 python scripts/check_reference_ids.py            # dry run
    docker exec -w /app papermanager-backend-1 python scripts/check_reference_ids.py --apply    # write
    ... --limit 500   only the first N stubs (newest first)

Stubs made before services/citecheck.py vetted extraction can carry a DOI cut at a line break
(``10.1063/1``), an id copied from the neighbouring reference, or an id an LLM made up. The same
rules as at extraction (``vet_reference_ids``, source "parser") decide: a dead id is cleared; an id
whose registered title differs is cleared, unless the stub's title is an author fragment, in which
case the registered title replaces it. Only stubs without a PDF are touched. --apply writes a JSON
log of every change to scripts/merge_logs/ first.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["REFERENCE_ID_CHECK"] = "1"

from db.connection import get_driver  # noqa: E402
from services.references import vet_reference_ids  # noqa: E402

_ARXIV = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?$", re.I)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    q = """
        MATCH (p:Paper)-[:TAGGED]->(:Tag {name: 'from-references'})
        WHERE p.doi IS NOT NULL AND p.doi <> '' AND p.drive_file_id IS NULL
        RETURN p.id AS id, p.title AS title, p.doi AS doi ORDER BY p.created_at DESC
    """ + (f" LIMIT {int(a.limit)}" if a.limit else "")
    with get_driver().session() as s:
        stubs = s.run(q).data()
    refs = []
    for st in stubs:
        m = _ARXIV.match(st["doi"].strip())
        refs.append({"title": st["title"] or "", "doi": None if m else st["doi"], "arxiv_id": m.group(1) if m else None})
    t0 = time.time()
    vet_reference_ids(refs, source="parser", budget=3600)
    print(f"{len(stubs)} stubs with an id checked in {time.time() - t0:.0f}s")
    print(dict(Counter(r.get("id_check", "none") for r in refs)))

    changes = []
    for st, r in zip(stubs, refs):
        chk = r.get("id_check", "")
        if chk.startswith("dropped:"):
            changes.append({"id": st["id"], "title": st["title"], "old_doi": st["doi"], "new_doi": None,
                            "new_title": st["title"], "why": chk})
        elif chk.startswith("title_from_"):
            changes.append({"id": st["id"], "title": st["title"], "old_doi": st["doi"], "new_doi": st["doi"],
                            "new_title": r["title"], "why": chk})
    for c in changes[:40]:
        print(f"  {c['why']:24} {c['old_doi'][:40]:40} {c['title'][:50]!r}"
              + (f" → {c['new_title'][:50]!r}" if c["new_title"] != c["title"] else ""))
    if len(changes) > 40:
        print(f"  … {len(changes) - 40} more")
    if not a.apply:
        print(f"dry run: {len(changes)} changes; --apply to write them")
        return 0
    log_dir = Path(__file__).resolve().parent / "merge_logs"
    log_dir.mkdir(exist_ok=True)
    log = log_dir / f"reference_ids_{datetime.now():%Y%m%d_%H%M%S}.json"
    log.write_text(json.dumps(changes, ensure_ascii=False, indent=1))
    with get_driver().session() as s:
        for c in changes:
            s.run("MATCH (p:Paper {id: $id}) SET p.doi = $doi, p.title = $title, p.updated_at = $now",
                  id=c["id"], doi=c["new_doi"], title=c["new_title"], now=datetime.utcnow().isoformat())
    print(f"applied {len(changes)} changes; log {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
