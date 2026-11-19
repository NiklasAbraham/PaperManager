"""The exact backend: a memory-mapped float32 matrix plus a SQLite table, searched by numpy.

Per generation directory:

    vectors.f32    row-major float32, ``capacity x dim``, memory-mapped; rows are only ever
                   appended (a replaced vector goes to a new row, the old row is marked dead), so
                   a reader that started before a write never sees a half-written vector
    meta.sqlite    ``items(row, id, live, kind, source, published, year, added_at, extra)``

Writes put the vectors in new rows and flush them *before* the SQLite transaction commits, so a
crash leaves at most unreferenced rows, which the next write overwrites. The filterable columns
are also held as small numpy arrays (about 19 bytes per row) so a filter is a vectorised mask;
ids and the remaining metadata are read from SQLite for the top hits only.

Search scores the matrix in chunks (``CHUNK`` rows) with one matrix-vector product each and keeps
a running top-k, so memory stays flat and 1M x 384 is a few hundred milliseconds from the page
cache.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Iterator

import numpy as np

from services.vectorstore.base import (Gen, Hit, StoreDamagedError, date_ordinal, merge_metadata,
                                       timestamp_epoch)

CHUNK = 32768
_INITIAL_CAP = 1024
_SQL_BATCH = 500   # ids per IN (...) statement, far below SQLite's variable limit

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    row INTEGER PRIMARY KEY,
    id TEXT NOT NULL,
    live INTEGER NOT NULL DEFAULT 1,
    kind TEXT,
    source TEXT,
    published TEXT,
    year INTEGER,
    added_at TEXT,
    extra TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS items_live_id ON items (id) WHERE live = 1;
"""
_COLS = "row, id, kind, source, published, year, added_at, extra"


class _Cols:
    """The filterable columns as numpy arrays, indexed by row. 0 / -1 mean "no value"."""

    __slots__ = ("cap", "live", "kind", "source", "year", "pub", "added")

    def __init__(self, cap: int):
        self.cap = cap
        self.live = np.zeros(cap, dtype=bool)
        self.kind = np.full(cap, -1, dtype=np.int32)
        self.source = np.full(cap, -1, dtype=np.int32)
        self.year = np.zeros(cap, dtype=np.int32)
        self.pub = np.zeros(cap, dtype=np.int32)
        self.added = np.zeros(cap, dtype=np.int64)

    def grown(self, cap: int) -> "_Cols":
        new = _Cols(cap)
        for name in ("live", "kind", "source", "year", "pub", "added"):
            getattr(new, name)[:self.cap] = getattr(self, name)
        return new


def _row_meta(kind, source, published, year, added_at, extra_json) -> dict:
    return merge_metadata({"kind": kind, "source": source, "published": published, "year": year,
                           "added_at": added_at}, json.loads(extra_json) if extra_json else {})


class ExactGen(Gen):
    backend = "exact"

    def __init__(self, path: Path, dim: int, read_only: bool):
        self.path, self.dim, self.read_only = Path(path), int(dim), read_only
        self._row_bytes = self.dim * 4
        self._vec_path = self.path / "vectors.f32"
        self._mlock = threading.Lock()      # guards the arrays and the mapping (swapped on growth)
        self._dblock = threading.RLock()    # serialises use of the SQLite connection
        self._codes: dict[str, dict[str, int]] = {"kind": {}, "source": {}}
        self._n = 0
        self._dead = 0
        self._cols = _Cols(0)
        self._mm: np.memmap | None = None
        self._cap = 0
        self._db = sqlite3.connect(str(self.path / "meta.sqlite"), check_same_thread=False, isolation_level=None)
        if read_only:
            self._db.execute("PRAGMA query_only=1")
        else:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")

    # ── construction ────────────────────────────────────────────────────────

    @classmethod
    def create(cls, path: Path, dim: int) -> "ExactGen":
        path = Path(path)
        path.mkdir(parents=True, exist_ok=False)
        with open(path / "vectors.f32", "wb") as f:
            f.truncate(_INITIAL_CAP * dim * 4)
        gen = cls(path, dim, read_only=False)
        gen._db.executescript(_SCHEMA)
        gen._load_state()
        return gen

    @classmethod
    def open(cls, path: Path, dim: int, read_only: bool) -> "ExactGen":
        path = Path(path)
        if not (path / "vectors.f32").exists() or not (path / "meta.sqlite").exists():
            raise StoreDamagedError(f"{path} lacks its data files")
        gen = cls(path, dim, read_only)
        try:
            gen._load_state()
        except Exception:
            gen.close()
            raise
        return gen

    def _map(self, cap: int) -> np.memmap:
        return np.memmap(self._vec_path, dtype=np.float32, mode="r" if self.read_only else "r+",
                         shape=(cap, self.dim))

    def _load_state(self) -> None:
        with self._dblock:
            n = self._db.execute("SELECT COALESCE(MAX(row) + 1, 0) FROM items").fetchone()[0]
            size = os.path.getsize(self._vec_path)
            if size < n * self._row_bytes or size == 0:
                raise StoreDamagedError(f"{self._vec_path} holds {size} bytes but {n} rows are recorded")
            cap = max(size // self._row_bytes, 1)
            cols = _Cols(max(cap, 1))
            kind_codes, source_codes = self._codes["kind"], self._codes["source"]
            dead = 0
            cur = self._db.execute("SELECT row, live, kind, source, published, year, added_at FROM items ORDER BY row")
            while True:
                page = cur.fetchmany(65536)
                if not page:
                    break
                for row, live, kind, source, published, year, added_at in page:
                    if not live:
                        dead += 1
                        continue
                    cols.live[row] = True
                    if kind is not None:
                        cols.kind[row] = kind_codes.setdefault(kind, len(kind_codes))
                    if source is not None:
                        cols.source[row] = source_codes.setdefault(source, len(source_codes))
                    if year is not None:
                        cols.year[row] = year
                    if published:
                        cols.pub[row] = date_ordinal(published)
                    if added_at:
                        cols.added[row] = timestamp_epoch(added_at)
        with self._mlock:
            self._cap, self._cols, self._n, self._dead = cap, cols, n, dead
            self._mm = self._map(cap)

    # ── growth and encoding ─────────────────────────────────────────────────

    def _ensure_capacity(self, rows: int) -> None:
        if rows <= self._cap:
            return
        cap = max(rows, int(self._cap * 1.5), _INITIAL_CAP)
        if self._mm is not None:
            self._mm.flush()
        with open(self._vec_path, "r+b") as f:
            f.truncate(cap * self._row_bytes)
        mm, cols = self._map(cap), self._cols.grown(cap)
        with self._mlock:
            self._mm, self._cols, self._cap = mm, cols, cap

    def _code(self, field: str, value: str | None) -> int:
        if value is None:
            return -1
        codes = self._codes[field]
        return codes.setdefault(value, len(codes))

    # ── SQLite helpers (call with _dblock held) ─────────────────────────────

    def _live_rows(self, ids: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in range(0, len(ids), _SQL_BATCH):
            chunk = ids[i:i + _SQL_BATCH]
            marks = ",".join("?" * len(chunk))
            out.update(self._db.execute(f"SELECT id, row FROM items WHERE live = 1 AND id IN ({marks})", chunk).fetchall())
        return out

    def _rows_meta(self, rows: list[int]) -> dict[int, tuple[str, dict]]:
        out: dict[int, tuple[str, dict]] = {}
        with self._dblock:
            for i in range(0, len(rows), _SQL_BATCH):
                chunk = rows[i:i + _SQL_BATCH]
                marks = ",".join("?" * len(chunk))
                for row, id_, kind, source, published, year, added_at, extra in self._db.execute(
                        f"SELECT {_COLS} FROM items WHERE row IN ({marks})", chunk):
                    out[row] = (id_, _row_meta(kind, source, published, year, added_at, extra))
        return out

    # ── writes ──────────────────────────────────────────────────────────────

    def upsert(self, ids, vectors, cores, extras) -> None:
        m = len(ids)
        with self._dblock:
            n0 = self._n
            self._ensure_capacity(n0 + m)
            self._mm[n0:n0 + m] = vectors
            self._mm.flush()                    # vectors are on disk before a row refers to them
            db = self._db
            db.execute("BEGIN IMMEDIATE")
            try:
                old = self._live_rows(ids)
                if old:
                    db.executemany("UPDATE items SET live = 0 WHERE row = ?", [(r,) for r in old.values()])
                db.executemany(
                    "INSERT INTO items (row, id, live, kind, source, published, year, added_at, extra) "
                    "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)",
                    [(n0 + i, ids[i], c["kind"], c["source"], c["published"], c["year"], c["added_at"],
                      json.dumps(e, separators=(",", ":"), ensure_ascii=False))
                     for i, (c, e) in enumerate(zip(cores, extras))])
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            kinds = np.array([self._code("kind", c["kind"]) for c in cores], dtype=np.int32)
            sources = np.array([self._code("source", c["source"]) for c in cores], dtype=np.int32)
            years = np.array([c["year"] or 0 for c in cores], dtype=np.int32)
            pubs = np.array([date_ordinal(c["published"]) if c["published"] else 0 for c in cores], dtype=np.int32)
            added = np.array([timestamp_epoch(c["added_at"]) if c["added_at"] else 0 for c in cores], dtype=np.int64)
            with self._mlock:
                cols = self._cols
                sl = slice(n0, n0 + m)
                cols.kind[sl], cols.source[sl], cols.year[sl], cols.pub[sl], cols.added[sl] = kinds, sources, years, pubs, added
                cols.live[sl] = True
                for r in old.values():
                    cols.live[r] = False
                self._dead += len(old)
                self._n = n0 + m

    def delete(self, ids) -> int:
        with self._dblock:
            old = self._live_rows(ids)
            if not old:
                return 0
            db = self._db
            db.execute("BEGIN IMMEDIATE")
            try:
                db.executemany("UPDATE items SET live = 0 WHERE row = ?", [(r,) for r in old.values()])
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            with self._mlock:
                for r in old.values():
                    self._cols.live[r] = False
                self._dead += len(old)
            return len(old)

    def flush(self) -> None:
        if self._mm is not None and not self.read_only:
            self._mm.flush()

    # ── reads ───────────────────────────────────────────────────────────────

    def count(self) -> int:
        with self._mlock:
            return self._n - self._dead

    def dead(self) -> int:
        return self._dead

    def ids(self) -> list[str]:
        with self._dblock:
            return [r[0] for r in self._db.execute("SELECT id FROM items WHERE live = 1 ORDER BY row")]

    def get(self, ids):
        with self._dblock:
            found: dict[str, tuple[int, dict]] = {}
            for i in range(0, len(ids), _SQL_BATCH):
                chunk = ids[i:i + _SQL_BATCH]
                marks = ",".join("?" * len(chunk))
                for row, id_, kind, source, published, year, added_at, extra in self._db.execute(
                        f"SELECT {_COLS} FROM items WHERE live = 1 AND id IN ({marks})", chunk):
                    found[id_] = (row, _row_meta(kind, source, published, year, added_at, extra))
        if not found:
            return {}
        with self._mlock:
            mm = self._mm
        order = list(found)
        vecs = np.asarray(mm[[found[i][0] for i in order]])
        return {i: (vecs[n].copy(), found[i][1]) for n, i in enumerate(order)}

    def metadata(self, ids):
        out: dict[str, dict] = {}
        with self._dblock:
            if ids is None:
                for row, id_, kind, source, published, year, added_at, extra in self._db.execute(
                        f"SELECT {_COLS} FROM items WHERE live = 1 ORDER BY row"):
                    out[id_] = _row_meta(kind, source, published, year, added_at, extra)
                return out
            for i in range(0, len(ids), _SQL_BATCH):
                chunk = ids[i:i + _SQL_BATCH]
                marks = ",".join("?" * len(chunk))
                for row, id_, kind, source, published, year, added_at, extra in self._db.execute(
                        f"SELECT {_COLS} FROM items WHERE live = 1 AND id IN ({marks})", chunk):
                    out[id_] = _row_meta(kind, source, published, year, added_at, extra)
        return out

    def _snapshot(self):
        with self._mlock:
            return self._n, self._mm, self._cols

    def _mask(self, clauses: list[tuple], n: int, cols: _Cols) -> np.ndarray:
        mask = cols.live[:n].copy()
        for clause in clauses:
            kind = clause[0]
            if kind in ("id_in", "id_not_in"):
                with self._dblock:
                    rows = [r for r in self._live_rows(clause[1]).values() if r < n]
                if kind == "id_in":
                    keep = np.zeros(n, dtype=bool)
                    keep[rows] = True
                    mask &= keep
                else:
                    mask[rows] = False
                continue
            field = clause[1]
            if field in ("kind", "source"):
                arr = getattr(cols, field)[:n]
                if kind == "in":
                    codes = [self._codes[field][v] for v in clause[2] if v in self._codes[field]]
                    mask &= np.isin(arr, codes) if codes else False
                else:
                    raise ValueError(f"{field} supports equality filters only")
                continue
            arr, conv = {"year": (cols.year, int), "published": (cols.pub, date_ordinal),
                         "added_at": (cols.added, timestamp_epoch)}[field]
            arr = arr[:n]
            if kind == "in":
                mask &= np.isin(arr, [conv(v) for v in clause[2]])
            else:
                _, _, op, v = clause
                v = conv(v)
                mask &= (arr != 0) & {"gte": arr >= v, "gt": arr > v, "lte": arr <= v, "lt": arr < v}[op]
        return mask

    def search(self, q, k, clauses):
        n, mm, cols = self._snapshot()
        if n == 0:
            return []
        mask = self._mask(clauses, n, cols)
        total = int(mask.sum())
        if total == 0:
            return []
        k = min(k, total)
        scores: list[np.ndarray] = []
        rows: list[np.ndarray] = []

        def keep(sims: np.ndarray, base: np.ndarray | int) -> None:
            if len(sims) > k:
                idx = np.argpartition(sims, len(sims) - k)[len(sims) - k:]
            else:
                idx = np.arange(len(sims))
            scores.append(sims[idx])
            rows.append(idx + base if isinstance(base, int) else base[idx])

        if total * 2 >= n:                       # dense: stream contiguous slices, mask out the rest
            full = total == n
            for s in range(0, n, CHUNK):
                e = min(n, s + CHUNK)
                sims = np.asarray(mm[s:e]) @ q
                if not full:
                    sims = np.where(mask[s:e], sims, -np.inf)
                keep(sims, s)
        else:                                    # sparse: gather only the matching rows
            sel = np.flatnonzero(mask)
            for s in range(0, len(sel), CHUNK):
                part = sel[s:s + CHUNK]
                keep(mm[part] @ q, part)
        sc, rw = np.concatenate(scores), np.concatenate(rows)
        order = np.lexsort((rw, -sc))[:k]       # best first, ties by insertion order
        sc, rw = sc[order], rw[order]
        ok = np.isfinite(sc)
        sc, rw = sc[ok], rw[ok]
        meta = self._rows_meta([int(r) for r in rw])
        return [Hit(meta[int(r)][0], float(s), meta[int(r)][1]) for r, s in zip(rw, sc) if int(r) in meta]

    def all_vectors(self, clauses):
        n, mm, cols = self._snapshot()
        dim = self.dim
        if n == 0:
            return [], np.zeros((0, dim), dtype=np.float32)
        rows = np.flatnonzero(self._mask(clauses, n, cols))
        if len(rows) == 0:
            return [], np.zeros((0, dim), dtype=np.float32)
        mat = np.asarray(mm[rows]).astype(np.float32, copy=True)
        if len(rows) > 5000:
            with self._dblock:
                by_row = dict(self._db.execute("SELECT row, id FROM items WHERE live = 1 ORDER BY row").fetchall())
            ids = [by_row[int(r)] for r in rows]
        else:
            meta = self._rows_meta([int(r) for r in rows])
            ids = [meta[int(r)][0] for r in rows]
        return ids, mat

    def iter_batches(self, size: int = 4096) -> Iterator[tuple[list[str], np.ndarray, list[dict]]]:
        last = -1
        while True:
            with self._dblock:
                page = self._db.execute(
                    f"SELECT {_COLS} FROM items WHERE live = 1 AND row > ? ORDER BY row LIMIT ?", (last, size)).fetchall()
            if not page:
                return
            last = page[-1][0]
            with self._mlock:
                mm = self._mm
            vecs = np.asarray(mm[[r[0] for r in page]]).astype(np.float32, copy=True)
            yield ([r[1] for r in page], vecs, [_row_meta(*r[2:]) for r in page])

    def close(self) -> None:
        with self._dblock:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
        with self._mlock:
            self._mm = None
