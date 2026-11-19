#!/usr/bin/env python
"""Go back to the vector generation a model switch replaced (the rollback target).

When the backend swaps in a generation built with another embedding model (adopting an imported one or
finishing a rebuild), it keeps the generation it replaces on disk: ``VECTOR_STORE_KEEP_GENERATIONS``
(default 2) counts the live one, so by default one older generation is kept per namespace. This script
makes the newest kept generation live again and keeps the current one in its place, so running it twice
undoes itself.

    python scripts/vectors_rollback.py --status      # what is live, kept and prepared, per namespace
    python scripts/vectors_rollback.py               # roll back library, feed and feed_library

**Stop the backend first**: the swap needs the store's writer lock, which a running backend holds. Then
set ``EMBED_MODEL`` (and ``EMBED_DIM``, ``EMBED_POOLING``, the prefixes) in the backend's environment
back to what the printed lines say, and start it. With the old model configured and the new one still
set, the backend would see the rolled-back generation as stale and adopt the kept one again.

Setting the old model again without running this script works too: the backend finds a kept generation
of that model and adopts it instead of rebuilding. The vectors of papers added since are then embedded
by the normal sync.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NAMESPACES = ("library", "feed", "feed_library")


def describe(m) -> str:
    return f"{m.generation}: {m.model}, dim {m.dim}, {m.pooling} pooling, {m.count} vectors, built {m.created_at}"


def env_lines(m) -> list[str]:
    from services.vectorstore.model_config import KNOWN

    known = KNOWN.get(m.model)
    lines = [f"EMBED_MODEL={m.model}"]
    if known is None or known[0] != m.dim:
        lines.append(f"EMBED_DIM={m.dim}")
    if known is None or known[1] != m.pooling:
        lines.append(f"EMBED_POOLING={m.pooling}")
    if known is None or known[2] != m.query_prefix:
        lines.append(f"EMBED_QUERY_PREFIX={m.query_prefix}")
    if known is None or known[3] != m.doc_prefix:
        lines.append(f"EMBED_DOC_PREFIX={m.doc_prefix}")
    return lines


def status(namespaces: list[str], root=None) -> None:
    from services.vectorstore import registry

    for ns in namespaces:
        store = registry._make(root or registry.vector_dir(), ns, True, None)
        try:
            live = store.manifest()
            print(f"[{ns}] live:     {describe(live) if live else 'nothing built'}")
            for m in store.retained():
                print(f"[{ns}] kept:     {describe(m)}")
            for m in store.prepared():
                print(f"[{ns}] prepared: {describe(m)}")
        finally:
            store.close()


def rollback(namespaces: list[str], root=None, log=print) -> dict[str, object]:
    """Roll each namespace back. Returns ``{namespace: manifest now live, or None when nothing was kept}``."""
    from services.vectorstore import StoreLockedError, registry

    out: dict[str, object] = {}
    for ns in namespaces:
        store = registry._make(root or registry.vector_dir(), ns, False, None)
        try:
            try:
                m = store.rollback()
            except StoreLockedError:
                raise SystemExit(f"[{ns}] the vector store is locked by a running process: stop the backend first")
            out[ns] = m
            if m is None:
                log(f"[{ns}] no kept generation: nothing to roll back to")
            else:
                log(f"[{ns}] live again: {describe(m)}")
        finally:
            store.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roll the vector store back to the generation a model switch replaced.")
    ap.add_argument("--namespaces", default=",".join(NAMESPACES))
    ap.add_argument("--status", action="store_true", help="only list live, kept and prepared generations")
    args = ap.parse_args(argv)
    wanted = [n.strip() for n in args.namespaces.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in NAMESPACES]
    if unknown:
        ap.error(f"unknown namespace {unknown}; choose from {', '.join(NAMESPACES)}")
    if args.status:
        status(wanted)
        return 0
    done = rollback(wanted)
    models = {m.model: m for m in done.values() if m is not None}
    if not models:
        return 1
    print("\nNow set the backend's environment back to the model of the restored generations "
          "(restart the backend afterwards):\n")
    for m in models.values():
        for line in env_lines(m):
            print("  " + line)
    if len(models) > 1:
        print("\nWARNING: the namespaces now hold different models; roll back the ones that are missing "
              "or rebuild them by starting the backend with one model set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
