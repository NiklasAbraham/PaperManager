"""The optional LanceDB backend (``VECTOR_STORE=lance``), same interface as the exact one.

LanceDB is not in requirements.txt. It is imported lazily and only here; when the package is
missing ``registry.backend_name()`` falls back to the exact backend with a warning.

Per generation directory: ``lance/`` (a LanceDB database holding one table, ``vectors``).
Filters are pushed down as a SQL ``where`` with ``prefilter=True``. LanceDB's ``where`` takes a
string, not bind parameters, so every value that goes into it is validated first: integers are
cast with ``int()``, dates and timestamps come out of ``compile_filter`` already normalised,
and strings have their quotes doubled. Above ``INDEX_MIN_ROWS`` rows an IVF_HNSW_SQ index (cosine;
chosen over IVF_PQ for its recall on unstructured data) is created, and rebuilt when the table has
doubled since. Below the threshold LanceDB scans the table, which is exact.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterator

import numpy as np

from services.vectorstore.base import BackendUnavailableError, Gen, Hit, StoreDamagedError, merge_metadata

log = logging.getLogger(__name__)

TABLE = "vectors"
INDEX_MIN_ROWS = int(os.environ.get("VECTOR_STORE_LANCE_INDEX_MIN", "50000") or 50000)
_META_COLS = ["id", "kind", "source", "published", "year", "added_at", "extra"]


def _lancedb():
    try:
        import lancedb
        import pyarrow as pa
    except ImportError as exc:
        raise BackendUnavailableError(
            "VECTOR_STORE=lance needs the optional 'lancedb' package (pip install lancedb)") from exc
    return lancedb, pa


def _q(value: str) -> str:
    """A SQL string literal."""
    if "\x00" in value:
        raise ValueError("NUL in a filter value")
    return "'" + value.replace("'", "''") + "'"


def where_sql(clauses: list[tuple]) -> str | None:
    parts = []
    for clause in clauses:
        if clause[0] in ("id_in", "id_not_in"):
            vals = clause[1]
            if not vals:
                parts.append("1 = 0" if clause[0] == "id_in" else "1 = 1")
            else:
                neg = "NOT " if clause[0] == "id_not_in" else ""
                parts.append(f"{neg}id IN ({', '.join(_q(v) for v in vals)})")
        elif clause[0] == "in":
            _, field, vals = clause
            lit = [str(int(v)) if field == "year" else _q(v) for v in vals]
            parts.append(f"{field} IN ({', '.join(lit)})")
        else:
            _, field, op, v = clause
            sym = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<"}[op]
            parts.append(f"{field} {sym} {str(int(v)) if field == 'year' else _q(v)}")
    return " AND ".join(parts) if parts else None


def _matrix(tbl, dim: int) -> np.ndarray:
    if tbl.num_rows == 0:
        return np.zeros((0, dim), dtype=np.float32)
    col = tbl.column("vector").combine_chunks()
    return col.values.to_numpy(zero_copy_only=False).reshape(-1, dim).astype(np.float32, copy=True)


def _meta(row: dict) -> dict:
    return merge_metadata({k: row.get(k) for k in ("kind", "source", "published", "year", "added_at")},
                          json.loads(row.get("extra") or "{}"))


class LanceGen(Gen):
    backend = "lance"

    def __init__(self, path: Path, dim: int, table, pa):
        self.path, self.dim, self._t, self._pa = Path(path), int(dim), table, pa
        self._indexed_at = 0
        try:
            for idx in table.list_indices():
                self._indexed_at = max(self._indexed_at, int(getattr(idx, "num_indexed_rows", 0) or 0))
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def create(cls, path: Path, dim: int) -> "LanceGen":
        lancedb, pa = _lancedb()
        path = Path(path)
        path.mkdir(parents=True, exist_ok=False)
        schema = pa.schema([
            pa.field("id", pa.string()), pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("kind", pa.string()), pa.field("source", pa.string()), pa.field("published", pa.string()),
            pa.field("year", pa.int32()), pa.field("added_at", pa.string()), pa.field("extra", pa.string())])
        table = lancedb.connect(str(path / "lance")).create_table(TABLE, schema=schema)
        return cls(path, dim, table, pa)

    @classmethod
    def open(cls, path: Path, dim: int, read_only: bool) -> "LanceGen":
        lancedb, pa = _lancedb()
        path = Path(path)
        if not (path / "lance").exists():
            raise StoreDamagedError(f"{path} lacks its data files")
        return cls(path, dim, lancedb.connect(str(path / "lance")).open_table(TABLE), pa)

    # ── writes ──────────────────────────────────────────────────────────────

    def upsert(self, ids, vectors, cores, extras) -> None:
        pa = self._pa
        flat = pa.array(np.ascontiguousarray(vectors, dtype=np.float32).ravel(), pa.float32())
        data = pa.table({
            "id": pa.array(ids, pa.string()),
            "vector": pa.FixedSizeListArray.from_arrays(flat, self.dim),
            "kind": pa.array([c["kind"] for c in cores], pa.string()),
            "source": pa.array([c["source"] for c in cores], pa.string()),
            "published": pa.array([c["published"] for c in cores], pa.string()),
            "year": pa.array([c["year"] for c in cores], pa.int32()),
            "added_at": pa.array([c["added_at"] for c in cores], pa.string()),
            "extra": pa.array([json.dumps(e, separators=(",", ":"), ensure_ascii=False) for e in extras], pa.string()),
        }, schema=self._t.schema)
        self._t.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(data)
        self._maybe_index()

    def _maybe_index(self) -> None:
        n = self._t.count_rows()
        if n < INDEX_MIN_ROWS or n < 2 * self._indexed_at:
            return
        try:
            try:
                from lancedb.index import IvfHnswSq
                self._t.create_index("vector", config=IvfHnswSq(distance_type="cosine"), replace=True)
            except ImportError:  # older lancedb: its default IVF_PQ
                self._t.create_index(metric="cosine", vector_column_name="vector", replace=True)
            self._indexed_at = n
        except Exception as exc:  # noqa: BLE001 — without an index search stays exact, only slower
            log.warning("LanceDB index not created (%s); searching without it", exc)

    def delete(self, ids) -> int:
        have = self._t.count_rows()
        for i in range(0, len(ids), 500):
            self._t.delete(f"id IN ({', '.join(_q(v) for v in ids[i:i + 500])})")
        return have - self._t.count_rows()

    # ── reads ───────────────────────────────────────────────────────────────

    def count(self) -> int:
        return int(self._t.count_rows())

    def ids(self) -> list[str]:
        return self._t.search().select(["id"]).limit(max(self.count(), 1)).to_arrow().column("id").to_pylist()

    def get(self, ids):
        out: dict[str, tuple[np.ndarray, dict]] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            tbl = (self._t.search().where(f"id IN ({', '.join(_q(v) for v in chunk)})")
                   .limit(len(chunk)).to_arrow())
            mat = _matrix(tbl, self.dim)
            for n, row in enumerate(tbl.select(_META_COLS).to_pylist()):
                out[row["id"]] = (mat[n], _meta(row))
        return out

    def metadata(self, ids):
        out: dict[str, dict] = {}
        if ids is None:
            tbl = self._t.search().select(_META_COLS).limit(max(self.count(), 1)).to_arrow()
            return {r["id"]: _meta(r) for r in tbl.to_pylist()}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            tbl = (self._t.search().where(f"id IN ({', '.join(_q(v) for v in chunk)})")
                   .select(_META_COLS).limit(len(chunk)).to_arrow())
            out.update({r["id"]: _meta(r) for r in tbl.to_pylist()})
        return out

    def search(self, q, k, clauses):
        if self.count() == 0:
            return []
        query = self._t.search(q).metric("cosine").limit(k)
        where = where_sql(clauses)
        if where:
            query = query.where(where, prefilter=True)
        try:
            query = query.refine_factor(5)
        except Exception:  # noqa: BLE001
            pass
        tbl = query.to_arrow()
        rows = tbl.select(_META_COLS + ["_distance"]).to_pylist()
        return [Hit(r["id"], 1.0 - float(r["_distance"]), _meta(r)) for r in rows]

    def all_vectors(self, clauses):
        query = self._t.search().limit(max(self.count(), 1))
        where = where_sql(clauses)
        if where:
            query = query.where(where)
        tbl = query.to_arrow()
        return tbl.column("id").to_pylist(), _matrix(tbl, self.dim)

    def iter_batches(self, size: int = 4096) -> Iterator[tuple[list[str], np.ndarray, list[dict]]]:
        ids = self.ids()
        for i in range(0, len(ids), size):
            got = self.get(ids[i:i + size])
            keep = [x for x in ids[i:i + size] if x in got]
            yield keep, np.vstack([got[x][0] for x in keep]), [got[x][1] for x in keep]

    def close(self) -> None:
        self._t = None
