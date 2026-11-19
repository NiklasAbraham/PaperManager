"""One-time migration of the vectors that existed before the vector store, without re-embedding.

* ``library``       from ``<library search dir>/emb.npy`` + ``meta.json`` (semantic.py's old files)
* ``feed``          from the ``candidate.emb`` blobs of the feed database
* ``feed_library``  from the feed database's ``library_emb`` blobs

Each runs once per namespace: when neither ``<root>/<namespace>/CURRENT`` nor the marker
``<root>/<namespace>/MIGRATED.json`` exists. The old files and columns are only read, never
changed or deleted. Vectors are accepted only when they were made by the configured model (the
library files name theirs; the feed blobs are taken to be the legacy default's, so a different
EMBED_MODEL skips them and the feed re-embeds from the stored texts).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from services.vectorstore import registry
from services.vectorstore.base import StoreLockedError, now_iso
from services.vectorstore.model_config import ModelSpec, current, legacy_model

log = logging.getLogger(__name__)

MARKER = "MIGRATED.json"
_BATCH = 4096
Batches = Iterator[tuple[list[str], np.ndarray, list[dict]]]


def marker_path(namespace: str, root: Path | None = None) -> Path:
    return (root or registry.vector_dir()) / namespace / MARKER


def is_migrated(namespace: str, root: Path | None = None) -> bool:
    root = root or registry.vector_dir()
    return marker_path(namespace, root).exists() or (root / namespace / "CURRENT").exists()


def migrate_namespace(namespace: str, batches: Iterable, source: str, spec: ModelSpec | None = None,
                      wait: float = 120.0) -> int | None:
    """Fill ``namespace`` from ``batches`` (``(ids, vectors, metadata)`` tuples) unless it exists
    or was migrated before. Returns the number of vectors written, or None if nothing was done.
    Another process or thread migrating at the same moment is waited for (up to ``wait`` s)."""
    root = registry.vector_dir()
    spec = spec or current()
    if is_migrated(namespace, root):
        return None
    store = registry._make(root, namespace, False, spec)
    deadline = time.monotonic() + wait
    try:
        while True:
            try:
                rb = store.begin_rebuild(spec)
                break
            except StoreLockedError:
                if time.monotonic() > deadline:
                    log.warning("Vector store %s: another process holds the lock; migration skipped", namespace)
                    return None
                time.sleep(0.25)
        if is_migrated(namespace, root):      # finished by whoever held the lock before us
            rb.abort()
            return None
        n = 0
        try:
            for ids, vecs, metas in batches:
                rb.upsert(ids, vecs, metas)
                n += len(ids)
            if n == 0:
                rb.abort()
                return None
            rb.commit()
        except BaseException:
            rb.abort()
            raise
        marker_path(namespace, root).write_text(json.dumps(
            {"namespace": namespace, "source": source, "count": n, "model": spec.model, "dim": spec.dim,
             "migrated_at": now_iso()}, indent=1), encoding="utf-8")
        log.info("Vector store %s: migrated %d vectors from %s (no re-embedding)", namespace, n, source)
        return n
    finally:
        store.close()


# ── library ──────────────────────────────────────────────────────────────────

def library_batches(legacy_dir: Path, spec: ModelSpec) -> Batches | None:
    """The old index as batches, or None when the files are absent, damaged or for another model."""
    meta_p, emb_p = Path(legacy_dir) / "meta.json", Path(legacy_dir) / "emb.npy"
    if not meta_p.exists() or not emb_p.exists():
        return None
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        emb = np.load(emb_p, mmap_mode="r")
        ids, hashes = list(meta["ids"]), list(meta.get("hashes") or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Legacy library embeddings unreadable (%s); not migrated", exc)
        return None
    if meta.get("model") != spec.model or emb.ndim != 2 or emb.shape != (len(ids), spec.dim) \
            or len(hashes) != len(ids):
        log.info("Legacy library embeddings are for another model or damaged; not migrated")
        return None

    def gen() -> Batches:
        for s in range(0, len(ids), _BATCH):
            sl = slice(s, s + _BATCH)
            yield (ids[sl], np.asarray(emb[sl], dtype=np.float32),
                   [{"kind": "paper", "source": "library", "hash": h} for h in hashes[sl]])
    return gen()


def migrate_library(legacy_dir: Path, spec: ModelSpec | None = None) -> int | None:
    spec = spec or current()
    if is_migrated("library"):
        return None
    batches = library_batches(legacy_dir, spec)
    if batches is None:
        return None
    return migrate_namespace("library", batches, "emb.npy + meta.json", spec)


# ── feed ─────────────────────────────────────────────────────────────────────

def _blob_ok(spec: ModelSpec) -> bool:
    if spec.model != legacy_model():
        log.info("Feed vectors predate EMBED_MODEL=%s; they are re-embedded instead of migrated", spec.model)
        return False
    return True


def _rows(db: sqlite3.Connection, sql: str) -> Iterator[tuple]:
    cur = db.cursor()
    cur.execute(sql)
    while True:
        page = cur.fetchmany(_BATCH)
        if not page:
            return
        yield from page


def _batched(rows: Iterator[tuple], spec: ModelSpec, build) -> Batches:
    ids: list[str] = []
    vecs: list[np.ndarray] = []
    metas: list[dict] = []
    for row in rows:
        blob = row[-1]
        if blob is None or len(blob) != spec.dim * 4:
            continue
        ids.append(row[0])
        vecs.append(np.frombuffer(blob, dtype=np.float32))
        metas.append(build(row))
        if len(ids) >= _BATCH:
            yield ids, np.vstack(vecs), metas
            ids, vecs, metas = [], [], []
    if ids:
        yield ids, np.vstack(vecs), metas


def migrate_feed_candidates(db: sqlite3.Connection, lock, spec: ModelSpec | None = None) -> int | None:
    """``lock`` is the feed store's lock around its (shared) connection."""
    spec = spec or current()
    if is_migrated("feed") or not _blob_ok(spec):
        return None
    with lock:
        rows = list(_rows(db, "SELECT id, source, published, fetched_at, emb FROM candidate WHERE emb IS NOT NULL"))
    return migrate_namespace("feed", _batched(iter(rows), spec, lambda r: {
        "kind": "candidate", "source": r[1], "published": r[2], "added_at": r[3]}), "candidate.emb", spec)


def migrate_feed_library(db: sqlite3.Connection, lock, spec: ModelSpec | None = None) -> int | None:
    spec = spec or current()
    if is_migrated("feed_library") or not _blob_ok(spec):
        return None
    with lock:
        rows = list(_rows(db, "SELECT paper_id, hash, emb FROM library_emb"))
    return migrate_namespace("feed_library", _batched(iter(rows), spec, lambda r: {
        "kind": "library", "source": "feed_cache", "hash": r[1]}), "library_emb", spec)
