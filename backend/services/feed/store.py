"""SQLite sidecar of the feed: ``<feed dir>/feed.sqlite``.

Candidates are numerous and short-lived, so they do not belong in the graph database.
One connection is shared by all threads and every statement runs under a lock. Only
parameterised statements are used.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from services.feed import config

DIM = 384

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


def _vec(blob: bytes | None) -> np.ndarray | None:
    if blob is None:
        return None
    v = np.frombuffer(blob, dtype=np.float32)
    return v if v.shape == (DIM,) else None


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
        fetched_at=r["fetched_at"], emb=_vec(r["emb"]),
    )


class FeedStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
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

    def without_embedding(self, limit: int = 100000) -> list[Candidate]:
        rows = self._run("SELECT * FROM candidate WHERE emb IS NULL ORDER BY published DESC LIMIT ?", (limit,))
        return [_row_to_candidate(r) for r in rows]

    def set_embeddings(self, vectors: dict[str, np.ndarray]) -> None:
        with self._lock:
            for cid, v in vectors.items():
                self._db.execute("UPDATE candidate SET emb = ? WHERE id = ?",
                                 (np.asarray(v, dtype=np.float32).tobytes(), cid))
            self._db.commit()

    def get(self, cid: str) -> Candidate | None:
        rows = self._run("SELECT * FROM candidate WHERE id = ?", (cid,))
        return _row_to_candidate(rows[0]) if rows else None

    def get_embeddings(self, ids: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self._run(f"SELECT id, emb FROM candidate WHERE emb IS NOT NULL AND id IN ({marks})",
                               tuple(chunk)):
                v = _vec(r["emb"])
                if v is not None:
                    out[r["id"]] = v
        return out

    def embedded_since(self, published_from: str) -> list[Candidate]:
        """Embedded candidates published on or after the ISO date, newest first."""
        rows = self._run("SELECT * FROM candidate WHERE emb IS NOT NULL AND published >= ? "
                         "ORDER BY published DESC", (published_from,))
        return [_row_to_candidate(r) for r in rows]

    def sample_embeddings(self, exclude: set[str], n: int, seed: int = 0) -> np.ndarray:
        """A reproducible random sample (at most ``n``) of embedded candidates not in ``exclude``,
        as an (m, 384) matrix."""
        rows = self._run("SELECT id, emb FROM candidate WHERE emb IS NOT NULL ORDER BY id")
        vecs = [v for r in rows if r["id"] not in exclude and (v := _vec(r["emb"])) is not None]
        if not vecs:
            return np.zeros((0, DIM), dtype=np.float32)
        if len(vecs) > n:
            idx = np.random.default_rng(seed).choice(len(vecs), size=n, replace=False)
            vecs = [vecs[i] for i in sorted(idx)]
        return np.vstack(vecs).astype(np.float32)

    def counts(self) -> dict:
        r = self._run("SELECT COUNT(*) AS n, COUNT(emb) AS e FROM candidate")[0]
        return {"candidates": r["n"], "embedded": r["e"]}

    def purge(self, retention_days: int) -> int:
        """Delete candidates fetched before the retention window unless somebody rated them."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM candidate WHERE fetched_at < ? AND id NOT IN (SELECT candidate_id FROM label)",
                (cutoff,))
            self._db.commit()
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
        return {r["paper_id"]: r["hash"] for r in self._run("SELECT paper_id, hash FROM library_emb")}

    def set_library_embeddings(self, rows: dict[str, tuple[str, np.ndarray]]) -> None:
        with self._lock:
            for pid, (h, v) in rows.items():
                self._db.execute(
                    "INSERT INTO library_emb (paper_id, hash, emb) VALUES (?,?,?) "
                    "ON CONFLICT(paper_id) DO UPDATE SET hash = excluded.hash, emb = excluded.emb",
                    (pid, h, np.asarray(v, dtype=np.float32).tobytes()))
            self._db.commit()

    def delete_library_embeddings(self, ids: list[str]) -> None:
        with self._lock:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                self._db.execute(f"DELETE FROM library_emb WHERE paper_id IN ({','.join('?' * len(chunk))})",
                                 tuple(chunk))
            self._db.commit()

    def library_embeddings(self) -> tuple[list[str], np.ndarray]:
        ids, vecs = [], []
        for r in self._run("SELECT paper_id, emb FROM library_emb ORDER BY paper_id"):
            v = _vec(r["emb"])
            if v is not None:
                ids.append(r["paper_id"])
                vecs.append(v)
        return ids, (np.vstack(vecs) if vecs else np.zeros((0, DIM), dtype=np.float32))


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
