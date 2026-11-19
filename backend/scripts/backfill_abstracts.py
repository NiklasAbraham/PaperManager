#!/usr/bin/env python
"""Fill in missing abstracts of library papers from OpenAlex, Semantic Scholar, arXiv and Crossref.

Run inside the backend container (the API need not be up; this talks to Neo4j directly):

    python scripts/backfill_abstracts.py                                  # dry run, prints the counts
    python scripts/backfill_abstracts.py --report /data/abstracts_dry.json
    python scripts/backfill_abstracts.py --apply --report /data/abstracts_run1.json
    python scripts/backfill_abstracts.py --undo-report /data/abstracts_run1.json --apply

Dry run is the default and writes nothing to the database. ``--apply`` needs ``--report`` so that
every run can be undone; the report holds paper ids, titles and abstract lengths, so it must not
live inside a git repository (the script refuses). ``--undo-report`` (dry run unless ``--apply``)
clears exactly the abstracts that report applied, and only where ``abstract_source`` and the text
still match, so an abstract a user wrote or edited since is never removed.

Options: ``--limit N``, ``--include-stubs`` (reference-list entries, off by default),
``--sources openalex,semanticscholar,arxiv,crossref`` (order is fixed), ``--title-search``
(papers without a DOI, by exact-ish title via OpenAlex). Set ``ABSTRACT_BACKFILL_CONTACT`` to an
e-mail address or URL to join the services' polite pools. See docs/user-guide/abstract-backfill.md.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.connection import get_driver  # noqa: E402
from services import abstract_backfill  # noqa: E402


def inside_git_repo(path: Path) -> Path | None:
    """The repository root if ``path`` (existing or not) lies inside a git work tree."""
    for parent in [path.resolve(strict=False), *path.resolve(strict=False).parents]:
        if (parent / ".git").exists():
            return parent
    return None


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write to the database (default: dry run)")
    ap.add_argument("--report", type=Path, help="write the per-paper JSON report here (outside any git repository)")
    ap.add_argument("--undo-report", type=Path, help="clear the abstracts a previous --apply report lists")
    ap.add_argument("--limit", type=int, help="process at most N papers")
    ap.add_argument("--include-stubs", action="store_true", help="also papers tagged from-references")
    ap.add_argument("--sources", help="comma list out of openalex,semanticscholar,arxiv,crossref")
    ap.add_argument("--title-search", action="store_true", help="look up papers without a DOI by title (OpenAlex)")
    return ap


def main(argv: list[str] | None = None, driver=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.report is not None:
        root = inside_git_repo(args.report)
        if root is not None:
            print(f"error: --report {args.report} is inside a git repository ({root}); the report lists "
                  "library data, pick a path outside it", file=sys.stderr)
            return 2
    if args.apply and not args.undo_report and args.report is None:
        print("error: --apply needs --report PATH (outside any git repository), so the run can be undone",
              file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("error: --limit must be at least 1", file=sys.stderr)
        return 2

    if args.undo_report:
        try:
            data = json.loads(args.undo_report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"error: cannot read {args.undo_report}: {exc}", file=sys.stderr)
            return 2
        result = abstract_backfill.undo_report(driver or get_driver(), data, dry_run=not args.apply)
        print(json.dumps(result, indent=2))
        return 0

    sources = [s for s in (args.sources or "").split(",") if s.strip()] or None
    try:
        abstract_backfill.normalise_sources(sources)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = abstract_backfill.run_backfill(
        driver or get_driver(), dry_run=not args.apply, limit=args.limit,
        include_stubs=args.include_stubs, sources=sources, title_search=args.title_search)
    if args.report is not None:
        write_report(args.report, report)
        print(f"report written to {args.report}", file=sys.stderr)
    summary = {k: v for k, v in report.items() if k != "papers"}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
