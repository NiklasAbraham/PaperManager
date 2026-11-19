"""SQLite sidecar of the feed: ``<feed dir>/feed.sqlite``.

Candidates are numerous and short-lived, so they do not belong in the graph database.
One connection is shared by all threads and every statement runs under a lock. Only
parameterised statements are used.

The candidates' embedding vectors (and the cache of library vectors) live in the vector store
(``services.vectorstore``, namespaces ``feed`` and ``feed_library``), not in this database. The
``emb`` and ``library_emb`` columns of older databases are read once to fill the store and are
left as they are; nothing writes them any more.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from services import vectorstore
from services.feed import config
from services.vectorstore import migrate, model_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    ext_id TEXT NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    abstract TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    doi TEXT,
    categories TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL,
    emb BLOB,
    UNIQUE (source, ext_id)
);
CREATE INDEX IF NOT EXISTS candidate_published ON candidate (published);
CREATE TABLE IF NOT EXISTS label (
    user TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    value INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user, candidate_id)
);
CREATE TABLE IF NOT EXISTS config (user TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source TEXT NOT NULL DEFAULT '',
    fetched INTEGER NOT NULL DEFAULT 0,
    new INTEGER NOT NULL DEFAULT 0,
    embedded INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS fetch_state (key TEXT PRIMARY KEY, since TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS library_emb (
    paper_id TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    emb BLOB NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Candidate:
    id: str
    source: str
    ext_id: str
    title: str
    published: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    url: str = ""
    doi: str | None = None
    categories: list[str] = field(default_factory=list)
    fetched_at: str = ""
    emb: np.ndarray | None = None

    def to_public(self) -> dict:
        return {"id": self.id, "source": self.source, "title": self.title, "authors": self.authors,
                "abstract": self.abstract, "published": self.published, "url": self.url,
                "doi": self.doi, "categories": self.categories}


def _row_to_candidate(r: sqlite3.Row) -> Candidate:
    return Candidate(
        id=r["id"], source=r["source"], ext_id=r["ext_id"], title=r["title"],
        published=r["published"], authors=json.loads(r["authors"]), abstract=r["abstract"],
        url=r["url"], doi=r["doi"], categories=json.loads(r["categories"]),
        fetched_at=r["fetched_at"],
    )


def candidates_by_ids(run, ids: list[str]) -> dict[str, Candidate]:
    """Candidates (without vectors) by id. ``run(sql, args)`` returns ``sqlite3.Row`` rows; the
    ids are bound as parameters, 500 at a time."""
    out: dict[str, Candidate] = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for r in run(f"SELECT * FROM candidate WHERE id IN ({marks})", tuple(chunk)):
            out[r["id"]] = _row_to_candidate(r)
    return out


def _vector_meta(source: str, published: str, fetched_at: str) -> dict:
    return {"kind": "candidate", "source": source, "published": published, "added_at": fetched_at}


class FeedStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._vlock = threading.Lock()
        self._feed_vectors = None
        self._library_vectors = None
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _run(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._db.execute(sql, args)
            rows = cur.fetchall()
            self._db.commit()
            return rows

    # ── candidates ───────────────────────────────────────────────────────────

    def upsert_candidates(self, cands: list[Candidate]) -> int:
        """Insert candidates not seen before (same id or same source and external id);
        known ones are left as they are. Returns how many were new."""
        new = 0
        stamp = now_iso()
        with self._lock:
            for c in cands:
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO candidate (id, source, ext_id, title, authors, abstract, published, "
                    "url, doi, categories, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (c.id, c.source, c.ext_id, c.title, json.dumps(c.authors), c.abstract, c.published,
                     c.url, c.doi, json.dumps(c.categories), c.fetched_at or stamp))
                new += cur.rowcount
            self._db.commit()
        return new

    def known_ids(self, ids: list[str]) -> set[str]:
        out: set[str] = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            out.update(r["id"] for r in self._run(f"SELECT id FROM candidate WHERE id IN ({marks})", tuple(chunk)))
        return out

    # ── vectors (vector store namespaces ``feed`` and ``feed_library``) ──────

    def vectors(self):
        """The ``feed`` namespace, filled once from the old ``candidate.emb`` blobs."""
        with self._vlock:
            if self._feed_vectors is None:
                migrate.migrate_feed_candidates(self._db, self._lock)
                self._feed_vectors = vectorstore.get_store("feed")
                if self._feed_vectors.backend_mismatch() and not self._feed_vectors.is_stale():
                    self._feed_vectors.convert_backend()
            return self._feed_vectors

    def library_vectors(self):
        """The ``feed_library`` namespace, filled once from the old ``library_emb`` blobs."""
        with self._vlock:
            if self._library_vectors is None:
                migrate.migrate_feed_library(self._db, self._lock)
                self._library_vectors = vectorstore.get_store("feed_library")
            return self._library_vectors

    def vectors_stale(self) -> bool:
        return self.vectors().is_stale()

    def library_vectors_stale(self) -> bool:
        return self.library_vectors().is_stale()

    def without_embedding(self, limit: int = 100000) -> list[Candidate]:
        """Candidates with no usable vector (all of them while the store is stale), newest first."""
        vs = self.vectors()
        have = set() if vs.is_stale() else set(vs.ids())
        rows = self._run("SELECT * FROM candidate ORDER BY published DESC")
        return [_row_to_candidate(r) for r in rows if r["id"] not in have][:limit]

    def set_embeddings(self, vectors: dict[str, np.ndarray]) -> None:
        """Store vectors of known candidates (ids that are not candidates are ignored)."""
        ids = list(vectors)
        found: dict[str, tuple] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self._run(f"SELECT id, source, published, fetched_at FROM candidate WHERE id IN ({marks})",
                               tuple(chunk)):
                found[r["id"]] = (r["source"], r["published"], r["fetched_at"])
        keep = [i for i in ids if i in found]
        if keep:
            self.vectors().upsert(keep, np.vstack([np.asarray(vectors[i], dtype=np.float32) for i in keep]),
                                  [_vector_meta(*found[i]) for i in keep])

    def rebuild_embeddings(self, embed, text_of, chunk: int = 64) -> int:
        """Embed every candidate again into a new generation of the ``feed`` namespace and swap it
        in when done (used when the configured embedding model changed). Returns how many."""
        vs = self.vectors()
        rows = self._run("SELECT * FROM candidate ORDER BY published DESC")
        rb = vs.begin_rebuild(model_config.current())
        try:
            for i in range(0, len(rows), chunk):
                cands = [_row_to_candidate(r) for r in rows[i:i + chunk]]
                rb.upsert([c.id for c in cands], embed([text_of(c) for c in cands]),
                          [_vector_meta(c.source, c.published, c.fetched_at) for c in cands])
            rb.commit()
        except BaseException:
            rb.abort()
            raise
        return len(rows)

    def get(self, cid: str) -> Candidate | None:
        rows = self._run("SELECT * FROM candidate WHERE id = ?", (cid,))
        if not rows:
            return None
        c = _row_to_candidate(rows[0])
        vs = self.vectors()
        if not vs.is_stale():
            got = vs.get([cid])
            c.emb = got[cid][0] if cid in got else None
        return c

    def by_ids(self, ids: list[str]) -> dict[str, Candidate]:
        """Candidates by id, without their vectors."""
        return candidates_by_ids(self._run, ids)

    def get_embeddings(self, ids: list[str]) -> dict[str, np.ndarray]:
        vs = self.vectors()
        if vs.is_stale() or not ids:
            return {}
        return {i: v for i, (v, _) in vs.get(ids).items()}

    def embedded_since(self, published_from: str) -> list[Candidate]:
        """Embedded candidates published on or after the ISO date, newest first."""
        vs = self.vectors()
        if vs.is_stale():
            return []
        rows = self._run("SELECT * FROM candidate WHERE published >= ? ORDER BY published DESC", (published_from,))
        got = vs.get([r["id"] for r in rows])
        out = []
        for r in rows:
            if r["id"] in got:
                c = _row_to_candidate(r)
                c.emb = got[r["id"]][0]
                out.append(c)
        return out

    def sample_embeddings(self, exclude: set[str], n: int, seed: int = 0) -> np.ndarray:
        """A reproducible random sample (at most ``n``) of embedded candidates not in ``exclude``,
        as an (m, dim) matrix."""
        vs = self.vectors()
        dim = model_config.dim()
        if vs.is_stale():
            return np.zeros((0, dim), dtype=np.float32)
        have = set(vs.ids())
        ids = [r["id"] for r in self._run("SELECT id FROM candidate ORDER BY id")
               if r["id"] in have and r["id"] not in exclude]
        if not ids:
            return np.zeros((0, dim), dtype=np.float32)
        if len(ids) > n:
            idx = np.random.default_rng(seed).choice(len(ids), size=n, replace=False)
            ids = [ids[i] for i in sorted(idx)]
        got = vs.get(ids)
        return np.vstack([got[i][0] for i in ids if i in got]).astype(np.float32)

    def counts(self) -> dict:
        ids = [r["id"] for r in self._run("SELECT id FROM candidate")]
        vs = self.vectors()
        embedded = 0 if vs.is_stale() or not ids else len(set(ids) & set(vs.ids()))
        return {"candidates": len(ids), "embedded": embedded}

    def purge(self, retention_days: int) -> int:
        """Delete candidates fetched before the retention window unless somebody rated them."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self._lock:
            gone = [r["id"] for r in self._db.execute(
                "SELECT id FROM candidate WHERE fetched_at < ? AND id NOT IN (SELECT candidate_id FROM label)",
                (cutoff,)).fetchall()]
            cur = self._db.execute(
                "DELETE FROM candidate WHERE fetched_at < ? AND id NOT IN (SELECT candidate_id FROM label)",
                (cutoff,))
            self._db.commit()
        vs = self.vectors()
        if gone and not vs.is_stale():
            vs.delete(gone)
        return cur.rowcount

    # ── labels ───────────────────────────────────────────────────────────────

    def set_label(self, user: str, cid: str, value: int) -> None:
        if value not in (1, -1, 0):
            raise ValueError("label value must be 1, -1 or 0")
        self._run("INSERT INTO label (user, candidate_id, value, created_at) VALUES (?,?,?,?) "
                  "ON CONFLICT(user, candidate_id) DO UPDATE SET value = excluded.value, created_at = excluded.created_at",
                  (user, cid, value, now_iso()))

    def clear_label(self, user: str, cid: str) -> None:
        self._run("DELETE FROM label WHERE user = ? AND candidate_id = ?", (user, cid))

    def labels(self, user: str) -> dict[str, tuple[int, str]]:
        """candidate id -> (value, created_at) of one user."""
        return {r["candidate_id"]: (r["value"], r["created_at"])
                for r in self._run("SELECT candidate_id, value, created_at FROM label WHERE user = ?", (user,))}

    # ── per-user config ──────────────────────────────────────────────────────

    def get_config(self, user: str) -> config.FeedConfig | None:
        rows = self._run("SELECT json FROM config WHERE user = ?", (user,))
        return config.FeedConfig.from_dict(json.loads(rows[0]["json"])) if rows else None

    def set_config(self, user: str, cfg: config.FeedConfig) -> None:
        self._run("INSERT INTO config (user, json) VALUES (?, ?) "
                  "ON CONFLICT(user) DO UPDATE SET json = excluded.json", (user, json.dumps(cfg.to_dict())))

    def all_configs(self) -> dict[str, config.FeedConfig]:
        return {r["user"]: config.FeedConfig.from_dict(json.loads(r["json"]))
                for r in self._run("SELECT user, json FROM config")}

    # ── runs and fetch state ─────────────────────────────────────────────────

    def start_run(self) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO run (started_at) VALUES (?)", (now_iso(),))
            self._db.commit()
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, source: str, fetched: int, new: int, embedded: int,
                   error: str | None) -> None:
        self._run("UPDATE run SET finished_at = ?, source = ?, fetched = ?, new = ?, embedded = ?, error = ? "
                  "WHERE id = ?", (now_iso(), source, fetched, new, embedded, error, run_id))

    def last_run(self) -> dict | None:
        rows = self._run("SELECT * FROM run WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    def get_since(self, key: str) -> str | None:
        rows = self._run("SELECT since FROM fetch_state WHERE key = ?", (key,))
        return rows[0]["since"] if rows else None

    def set_since(self, key: str, since: str) -> None:
        self._run("INSERT INTO fetch_state (key, since) VALUES (?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET since = excluded.since", (key, since))

    # ── library embeddings (only for papers the semantic search index lacks) ──

    def library_hashes(self) -> dict[str, str]:
        vs = self.library_vectors()
        return {pid: m.get("hash", "") for pid, m in vs.metadata().items()}

    def set_library_embeddings(self, rows: dict[str, tuple[str, np.ndarray]]) -> None:
        if rows:
            ids = list(rows)
            self.library_vectors().upsert(
                ids, np.vstack([np.asarray(rows[i][1], dtype=np.float32) for i in ids]),
                [{"kind": "library", "source": "feed_cache", "hash": rows[i][0]} for i in ids])

    def delete_library_embeddings(self, ids: list[str]) -> None:
        if ids:
            self.library_vectors().delete(ids)

    def rebuild_library_embeddings(self, embed, rows: dict[str, tuple[str, str]], chunk: int = 128) -> int:
        """Replace the whole cache by embeddings of ``rows`` (``{paper_id: (hash, text)}``) made with
        the configured model, swapped in when done."""
        rb = self.library_vectors().begin_rebuild(model_config.current())
        ids = list(rows)
        try:
            for i in range(0, len(ids), chunk):
                part = ids[i:i + chunk]
                rb.upsert(part, embed([rows[p][1] for p in part]),
                          [{"kind": "library", "source": "feed_cache", "hash": rows[p][0]} for p in part])
            rb.commit()
        except BaseException:
            rb.abort()
            raise
        return len(ids)

    def library_embeddings(self) -> tuple[list[str], np.ndarray]:
        vs = self.library_vectors()
        if vs.is_stale():
            return [], np.zeros((0, model_config.dim()), dtype=np.float32)
        ids, mat = vs.all_vectors()
        order = sorted(range(len(ids)), key=lambda i: ids[i])
        return [ids[i] for i in order], (mat[order] if order else mat)


# ── the shared instance ───────────────────────────────────────────────────────

_instance: FeedStore | None = None
_instance_lock = threading.Lock()


def get_store() -> FeedStore:
    """The store in the current feed directory (opened on first use). Call only when the
    feed is enabled: it creates the directory and the file."""
    global _instance
    path = config.feed_dir() / "feed.sqlite"
    with _instance_lock:
        if _instance is None or _instance.path != path:
            if _instance is not None:
                _instance.close()
            _instance = FeedStore(path)
        return _instance


def reset() -> None:
    """Close and forget the shared store (tests)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.close()
        _instance = None
