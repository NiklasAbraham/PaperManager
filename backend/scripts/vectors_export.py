#!/usr/bin/env python
"""Export the texts to embed for a new embedding model, to be embedded elsewhere (``embed_bulk.py``).

Run inside the backend environment (it reads the graph database and the feed database directly; the
API need not be up), for example

    python scripts/vectors_export.py --out /data/vector_export --model <model id>

or with the target model in the environment (``EMBED_MODEL``, plus ``EMBED_DIM`` / ``EMBED_POOLING`` /
``EMBED_DOC_PREFIX`` for a model that ``services/vectorstore/model_config.KNOWN`` does not list).

It writes, into ``--out``:

    spec.json          the target model (model, dim, pooling, query_prefix, doc_prefix, text_format),
                       ``max_length`` (the backend's 256 tokens), and ``counts`` per namespace
    library.jsonl      every paper of the library: {"id", "text", "hash", "meta"}, text = the text the
                       semantic index embeds (``library_search.semantic.paper_text``)
    feed.jsonl         the feed's stored candidates (text: ``feed.pipeline._candidate_text``)
    feed_library.jsonl the library papers the feed would cache itself: those the search index does not
                       hold (none when the library search is on, since the library file covers every paper)

``hash`` and ``meta`` are not read by ``embed_bulk.py``; ``vectors_import.py`` needs them so that the
imported vectors carry the same text hashes and metadata the live sync writes, and the normal sync
afterwards embeds only the papers that changed.

This is an *operator* tool with direct database access: it reads every paper and does no per-user
visibility filtering, exactly like the semantic sync thread (the vector index is not per user either).
The files are private data (titles, abstracts, summaries of the whole library), so ``--out`` is refused
when it lies inside a git repository or inside the backend's code directory, and the directory is
created readable by its owner only. Copy it only to machines you trust and delete it afterwards.

Nothing is written to the databases or the vector store.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FORMAT = 1
NAMESPACES = ("library", "feed", "feed_library")
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def refuse_unsafe_output(out: Path) -> Path:
    """The resolved ``out``, or ``SystemExit`` when it is inside a git repository (a ``.git`` in it or in
    any parent directory, the directory need not exist yet) or inside the backend's code directory."""
    out = Path(out).expanduser().resolve()
    for p in (out, *out.parents):
        if (p / ".git").exists():
            raise SystemExit(f"refusing to write the export into {out}: it is inside the git repository {p}. "
                             "The files hold the whole library's text; choose a directory outside any repository.")
    if _inside(out, BACKEND_DIR):
        raise SystemExit(f"refusing to write the export into {out}: it is inside the code directory {BACKEND_DIR}.")
    return out


def apply_overrides(args) -> None:
    """Put the command-line model settings into the environment, where ``model_config.current()`` reads them."""
    for flag, var in (("model", "EMBED_MODEL"), ("dim", "EMBED_DIM"), ("pooling", "EMBED_POOLING"),
                      ("query_prefix", "EMBED_QUERY_PREFIX"), ("doc_prefix", "EMBED_DOC_PREFIX")):
        value = getattr(args, flag)
        if value is not None:
            os.environ[var] = str(value)


def library_records(texts: dict[str, str]) -> list[dict]:
    from services.library_search.semantic import text_hash

    return [{"id": pid, "text": t, "hash": text_hash(t), "meta": {"kind": "paper", "source": "library"}}
            for pid, t in sorted(texts.items())]


def feed_records(candidates) -> list[dict]:
    from services.feed.pipeline import _candidate_text
    from services.feed.store import _vector_meta

    return [{"id": c.id, "text": _candidate_text(c),
             "meta": _vector_meta(c.source, c.published, c.fetched_at)} for c in candidates]


def feed_library_records(texts: dict[str, str], indexed: set[str]) -> list[dict]:
    """What the feed would cache for itself: library papers the search index does not hold."""
    from services.library_search.semantic import text_hash

    return [{"id": pid, "text": t, "hash": text_hash(t), "meta": {"kind": "library", "source": "feed_cache"}}
            for pid, t in sorted(texts.items()) if pid not in indexed]


def write_export(out: Path, spec, records: dict[str, list[dict]], max_length: int) -> dict:
    """Write ``spec.json`` and one ``<namespace>.jsonl`` per entry of ``records``. Returns the spec dict."""
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out, 0o700)
    for ns, recs in records.items():
        tmp = out / f"{ns}.jsonl.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, out / f"{ns}.jsonl")
        for stale in (f"{ns}.npy", f"{ns}.ids.json", f"{ns}.done.json"):   # vectors of an earlier export
            (out / stale).unlink(missing_ok=True)
    doc = {**spec.to_dict(), "format": FORMAT, "max_length": max_length,
           "counts": {ns: len(recs) for ns, recs in records.items()},
           "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    tmp = out / "spec.json.tmp"
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, out / "spec.json")
    return doc


def collect(namespaces: list[str], driver=None, feed_store=None) -> dict[str, list[dict]]:
    """The records of the wanted namespaces, read through the code the live system uses."""
    from services.library_search import semantic

    out: dict[str, list[dict]] = {}
    texts = None
    if "library" in namespaces or "feed_library" in namespaces:
        texts = semantic._fetch_texts(driver)          # the semantic sync's own query: every paper
    if "library" in namespaces:
        out["library"] = library_records(texts)
    if "feed" in namespaces:
        out["feed"] = feed_records(feed_store.all_candidates())
    if "feed_library" in namespaces:
        # with the library search on, its index will hold every paper of the library file
        out["feed_library"] = feed_library_records(texts, set(texts) if semantic.enabled() else set())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export the texts to embed for a new embedding model.")
    ap.add_argument("--out", required=True, help="directory for the export; must be outside any git repository")
    ap.add_argument("--namespaces", default=",".join(NAMESPACES),
                    help="comma list of library, feed, feed_library (default all; the feed ones need PAPER_FEED)")
    ap.add_argument("--model", help="target embedding model id (default: EMBED_MODEL)")
    ap.add_argument("--dim", type=int, help="its dimension (only for a model model_config does not know)")
    ap.add_argument("--pooling", choices=("cls", "mean"))
    ap.add_argument("--query-prefix", dest="query_prefix")
    ap.add_argument("--doc-prefix", dest="doc_prefix")
    args = ap.parse_args(argv)

    out = refuse_unsafe_output(Path(args.out))
    wanted = [n.strip() for n in args.namespaces.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in NAMESPACES]
    if unknown:
        ap.error(f"unknown namespace {unknown}; choose from {', '.join(NAMESPACES)}")
    apply_overrides(args)

    from services.conferences.embedder import DOC_MAX_LENGTH
    from services.vectorstore import model_config

    try:
        spec = model_config.current()
    except model_config.ModelConfigError as exc:
        ap.error(f"{exc}; pass --dim (and --pooling) for a model that is not in the known list")
    driver = feed_store = None
    if "library" in wanted or "feed_library" in wanted:
        from db.connection import get_driver
        driver = get_driver()
    if "feed" in wanted or "feed_library" in wanted:
        from services.feed import config as feed_config
        if not feed_config.enabled():
            print("PAPER_FEED is off: the feed namespaces are skipped")
            wanted = [n for n in wanted if n not in ("feed", "feed_library")]
        elif "feed" in wanted:
            from services.feed.store import get_store as get_feed_store
            feed_store = get_feed_store()
    if not wanted:
        print("nothing to export")
        return 1
    records = collect(wanted, driver, feed_store)
    doc = write_export(out, spec, records, DOC_MAX_LENGTH)
    print(f"exported to {out}: model {spec.model} (dim {spec.dim}, {spec.pooling} pooling)")
    for ns, n in doc["counts"].items():
        print(f"  {ns}: {n} texts")
    print("Copy this directory to the machine with the GPU and run embed_bulk.py there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
