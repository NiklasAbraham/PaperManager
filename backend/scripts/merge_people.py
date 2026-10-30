"""Find and merge duplicate Person nodes (the People page's "Duplicates" button does the same).

    docker exec -w /app papermanager-backend-1 python scripts/merge_people.py            # list groups
    docker exec -w /app papermanager-backend-1 python scripts/merge_people.py --apply

Matching rules and the merge itself: services/person_duplicates.py. ``--no-initials`` skips the
initials rule ("C. P. Robert" = "Christian P. Robert"). ``--exclude`` takes id prefixes whose
groups are skipped. A JSON backup of every affected node is written first.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.connection import get_driver  # noqa: E402
from services.person_duplicates import find_duplicate_groups, merge  # noqa: E402

LOGS = Path(__file__).resolve().parent / "merge_logs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--no-initials", action="store_true")
    args = ap.parse_args()
    excl = [e for e in args.exclude.split(",") if e]
    driver = get_driver()
    gs = [g["people"] for g in find_duplicate_groups(driver, initials=not args.no_initials)]
    gs = [g for g in gs if not any(p["id"].startswith(e) for p in g for e in excl)]
    print(f"{len(gs)} duplicate groups")
    for g in gs:
        print(f"  keep {g[0]['id'][:8]} {g[0]['name']!r} ({g[0]['degree']})  <- "
              + ", ".join(f"{p['id'][:8]} {p['name']!r} ({p['degree']})" for p in g[1:]))
    if not args.apply or not gs:
        return
    LOGS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ids = [p["id"] for g in gs for p in g]
    with driver.session() as s:
        backup = s.run("""
            MATCH (p:Person) WHERE p.id IN $ids
            OPTIONAL MATCH (p)-[r]-(x)
            RETURN properties(p) AS person,
                   collect({type: type(r), out: startNode(r) = p, other: x.id, props: properties(r)}) AS rels
        """, ids=ids).data()
        (LOGS / f"people_backup_{stamp}.json").write_text(json.dumps(backup, default=str, indent=1))
        print(f"backup: {LOGS / f'people_backup_{stamp}.json'}")
        for g in gs:
            for p in g[1:]:
                n = s.execute_write(merge, g[0]["id"], p["id"])
                print(f"  merged {p['name']!r} -> {g[0]['name']!r} ({n} rels)")


if __name__ == "__main__":
    main()
