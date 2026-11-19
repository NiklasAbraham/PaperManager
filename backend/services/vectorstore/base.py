"""The vector store interface and what every backend shares.

A *namespace* (``library``, ``feed``, ...) is one directory under the store root::

    <root>/<namespace>/CURRENT            name of the live generation, replaced atomically
    <root>/<namespace>/<generation>/      manifest.json + the backend's own files
    <root>/<namespace>/LOCK               held by the one process that may write

A generation holds vectors of one model. A rebuild for a new model fills a *new* generation next
to the live one and flips ``CURRENT`` in one rename, so readers keep working during the build and
never see two models mixed. :class:`GenerationalStore` implements that once for every backend; a
backend only supplies a *generation* class (``exact.ExactGen``, ``lance_store.LanceGen``).

Vectors are unit length and compared by cosine, which for unit vectors is the dot product.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, NamedTuple

import numpy as np

from services.vectorstore.model_config import ModelSpec, current

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
NAMESPACE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
# Fields a filter may use. ``kind``/``source`` are free strings, ``published`` a date, ``year`` an
# integer, ``added_at`` a UTC timestamp. Anything else in the metadata is stored and returned but
# cannot be filtered on.
FILTER_FIELDS = ("kind", "source", "published", "year", "added_at")
_RANGE_OPS = ("gte", "gt", "lte", "lt")
# A retired generation's files stay this long so a search that started before the swap can finish.
RETIRE_GRACE_SECONDS = 60.0
# Compact a store (rewrite its live rows into a fresh generation) when this many rows are dead
# and they outnumber half of the live ones.
COMPACT_MIN_DEAD = 1000
COMPACT_RATIO = 0.5
# Generations kept for a rollback. When a swap changes the embedding space (another model), the
# generation it replaces keeps its files, marked ``RETAINED``; VECTOR_STORE_KEEP_GENERATIONS counts
# the live one, so the default 2 keeps the live generation and one before it, 1 keeps none (the old
# one goes after RETIRE_GRACE_SECONDS, as it always did). A swap inside one space (compaction,
# backend conversion) never keeps the old files.
KEEP_ENV = "VECTOR_STORE_KEEP_GENERATIONS"
DEFAULT_KEEP = 2
RETAINED = "RETAINED"      # marker file in a kept, no longer live generation
PREPARED = "PREPARED"      # marker file in a finished generation that was never live (``p######``)
STALE_PREPARE_SECONDS = 24 * 3600.0


def keep_generations() -> int:
    """VECTOR_STORE_KEEP_GENERATIONS (default 2, at least 1; an unreadable value counts as unset)."""
    raw = os.environ.get(KEEP_ENV, "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_KEEP
    except ValueError:
        return DEFAULT_KEEP


class VectorStoreError(RuntimeError):
    """Something is wrong with a store (damaged, missing package, bad arguments)."""


class StoreDamagedError(VectorStoreError):
    """A generation's files are missing or inconsistent; the store reads as empty until rebuilt."""


class BackendUnavailableError(VectorStoreError):
    """The backend's package is not installed (the namespace was built with it)."""


class StaleStoreError(VectorStoreError):
    """The store was built with another model than the configured one; it must be rebuilt."""


class StoreLockedError(VectorStoreError):
    """Another process holds the writer lock of this namespace."""


class Hit(NamedTuple):
    id: str
    score: float
    metadata: dict


@dataclass
class Manifest:
    namespace: str
    backend: str
    model: str
    dim: int
    pooling: str
    query_prefix: str
    doc_prefix: str
    text_format: str
    generation: str
    created_at: str
    updated_at: str
    count: int
    schema: int = SCHEMA_VERSION

    def spec(self) -> ModelSpec:
        return ModelSpec(self.model, self.dim, self.pooling, self.query_prefix, self.doc_prefix, self.text_format)

    def to_dict(self) -> dict:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── metadata and filters ─────────────────────────────────────────────────────

def to_date(value: Any) -> str | None:
    """``YYYY-MM-DD`` of a date, datetime or ISO string, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10]).isoformat()
        except ValueError:
            return None
    return None


def to_timestamp(value: Any) -> str | None:
    """``YYYY-MM-DDTHH:MM:SSZ`` (UTC) of a datetime, epoch seconds or ISO string, else None.
    A date or a string without a time means midnight; a naive datetime is taken as UTC."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            dt = datetime.fromtimestamp(float(value), timezone.utc)
        elif isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime(value.year, value.month, value.day)
        elif isinstance(value, str):
            s = value.strip()
            dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s)
        else:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_ordinal(iso_date: str) -> int:
    return date.fromisoformat(iso_date).toordinal()


def timestamp_epoch(iso_ts: str) -> int:
    return int(datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def split_metadata(meta: dict | None) -> tuple[dict, dict]:
    """``(core, extra)``: the filterable fields normalised, and everything else as given.
    ``year`` falls back to the year of ``published``. Unparsable dates are dropped, not errors."""
    meta = dict(meta or {})
    kind, source = meta.pop("kind", None), meta.pop("source", None)
    core: dict[str, Any] = {
        "kind": None if kind is None else str(kind),
        "source": None if source is None else str(source),
        "published": to_date(meta.pop("published", None)),
        "year": None,
        "added_at": to_timestamp(meta.pop("added_at", None)),
    }
    year = meta.pop("year", None)
    if year is not None and not isinstance(year, bool):
        try:
            core["year"] = int(year)
        except (TypeError, ValueError):
            core["year"] = None
    if core["year"] is None and core["published"]:
        core["year"] = int(core["published"][:4])
    try:
        json.dumps(meta)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata must be JSON-serialisable: {exc}") from exc
    return core, meta


def merge_metadata(core: dict, extra: dict) -> dict:
    out = {k: v for k, v in core.items() if v is not None}
    out.update(extra)
    return out


def _as_list(value: Any) -> list:
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def compile_filter(flt: dict | None) -> list[tuple]:
    """Validate a filter and turn it into clauses every backend reads the same way.

    A filter is a dict, all keys ANDed::

        {"kind": "paper"}                       equals
        {"source": ["arxiv", "biorxiv"]}        any of
        {"year": {"gte": 2020, "lt": 2025}}     range (gte, gt, lte, lt); also on published, added_at
        {"year": 2021}                          equals
        {"id": [...]}, {"exclude_id": [...]}    restrict to / leave out ids

    Clauses: ``("in", field, values)``, ``("range", field, op, value)``, ``("id_in", ids)``,
    ``("id_not_in", ids)``. Values are normalised (dates to ``YYYY-MM-DD``, timestamps to UTC
    ISO, years to int). An unknown key raises ValueError."""
    if not flt:
        return []
    out: list[tuple] = []
    for key, value in flt.items():
        if key == "id":
            out.append(("id_in", [str(v) for v in _as_list(value)]))
        elif key == "exclude_id":
            out.append(("id_not_in", [str(v) for v in _as_list(value)]))
        elif key in FILTER_FIELDS:
            if isinstance(value, dict):
                for op, v in value.items():
                    if op not in _RANGE_OPS:
                        raise ValueError(f"unknown range operator {op!r} for {key!r}")
                    out.append(("range", key, op, _norm_value(key, v)))
            else:
                out.append(("in", key, [_norm_value(key, v) for v in _as_list(value)]))
        else:
            raise ValueError(f"cannot filter on {key!r}; filterable fields: {', '.join(FILTER_FIELDS)}, id, exclude_id")
    return out


def _norm_value(field: str, v: Any) -> Any:
    if field == "year":
        if isinstance(v, bool):
            raise ValueError("year must be an integer")
        return int(v)
    if field == "published":
        d = to_date(v)
        if d is None:
            raise ValueError(f"not a date: {v!r}")
        return d
    if field == "added_at":
        t = to_timestamp(v)
        if t is None:
            raise ValueError(f"not a timestamp: {v!r}")
        return t
    return str(v)


def unit_rows(vectors: Any, dim: int) -> np.ndarray:
    """``(m, dim)`` float32, finite, with rows that are not already unit length normalised
    (a norm within 1e-3 of 1 is left alone, so stored vectors stay bit-identical to what the
    embedder produced)."""
    v = np.asarray(vectors, dtype=np.float32)
    if v.ndim == 1:
        v = v[None, :]
    if v.ndim != 2 or v.shape[1] != dim:
        raise ValueError(f"vectors must have shape (n, {dim}), got {tuple(v.shape)}")
    if not np.isfinite(v).all():
        raise ValueError("vectors contain NaN or infinity")
    norms = np.linalg.norm(v, axis=1)
    off = (np.abs(norms - 1.0) > 1e-3) & (norms > 0)
    if off.any():
        v = v.copy()
        v[off] /= norms[off, None]
    return v


def unit_query(q: Any, dim: int) -> np.ndarray:
    v = unit_rows(q, dim)
    if v.shape[0] != 1:
        raise ValueError("search takes one query vector")
    return v[0]


# ── interface ────────────────────────────────────────────────────────────────

class Rebuild(ABC):
    """A new generation being filled next to the live one. ``commit()`` swaps it in atomically;
    ``abort()`` (or leaving a ``with`` block without committing) throws it away."""

    @abstractmethod
    def upsert(self, ids: Iterable[str], vectors: Any, metadata: Iterable[dict] | None = None) -> None: ...

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def abort(self) -> None: ...

    def __enter__(self) -> "Rebuild":
        return self

    def __exit__(self, *exc) -> None:
        self.abort()


class VectorStore(ABC):
    """One namespace of unit vectors with metadata. Safe to call from several threads."""

    namespace: str

    @abstractmethod
    def manifest(self) -> Manifest | None:
        """Model, dimension, text format, times and count of the live generation; None if empty-new."""

    @abstractmethod
    def is_stale(self, spec: ModelSpec | None = None) -> bool:
        """True when the live generation was built with another model/dimension/text format than
        ``spec`` (default: the configured model). A stale store refuses writes and vector reads."""

    @abstractmethod
    def upsert(self, ids: Iterable[str], vectors: Any, metadata: Iterable[dict] | None = None) -> None:
        """Insert or replace by id. ``metadata`` is one dict per id: ``kind``, ``source``,
        ``published`` (date), ``year``, ``added_at`` (timestamp) are filterable, other JSON-able keys ride along."""

    @abstractmethod
    def delete(self, ids: Iterable[str]) -> int: ...

    @abstractmethod
    def get(self, ids: Iterable[str]) -> dict[str, tuple[np.ndarray, dict]]:
        """``{id: (vector, metadata)}`` for the ids that exist."""

    @abstractmethod
    def metadata(self, ids: Iterable[str] | None = None) -> dict[str, dict]:
        """``{id: metadata}`` without reading any vector (all ids when ``ids`` is None)."""

    @abstractmethod
    def search(self, query_vector: Any, k: int = 10, filter: dict | None = None) -> list[Hit]:
        """The ``k`` most similar vectors, best first: ``[(id, cosine, metadata)]``."""

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def ids(self) -> list[str]: ...

    @abstractmethod
    def all_vectors(self, filter: dict | None = None) -> tuple[list[str], np.ndarray]:
        """Every (matching) id with its vector as an ``(n, dim)`` matrix, in insertion order."""

    @abstractmethod
    def begin_rebuild(self, spec: ModelSpec | None = None) -> Rebuild: ...

    @abstractmethod
    def close(self) -> None: ...


# ── generations (backend plug-in) ────────────────────────────────────────────

class Gen(ABC):
    """One generation of one backend. Writers are serialised by the store; reads are concurrent."""

    backend = ""
    path: Path

    @classmethod
    @abstractmethod
    def create(cls, path: Path, dim: int) -> "Gen": ...

    @classmethod
    @abstractmethod
    def open(cls, path: Path, dim: int, read_only: bool) -> "Gen": ...

    @abstractmethod
    def upsert(self, ids: list[str], vectors: np.ndarray, cores: list[dict], extras: list[dict]) -> None: ...

    @abstractmethod
    def delete(self, ids: list[str]) -> int: ...

    @abstractmethod
    def get(self, ids: list[str]) -> dict[str, tuple[np.ndarray, dict]]: ...

    @abstractmethod
    def metadata(self, ids: list[str] | None) -> dict[str, dict]: ...

    @abstractmethod
    def search(self, q: np.ndarray, k: int, clauses: list[tuple]) -> list[Hit]: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def ids(self) -> list[str]: ...

    @abstractmethod
    def all_vectors(self, clauses: list[tuple]) -> tuple[list[str], np.ndarray]: ...

    @abstractmethod
    def iter_batches(self, size: int = 4096) -> Iterator[tuple[list[str], np.ndarray, list[dict]]]:
        """Live rows as ``(ids, vectors, metadata)`` batches, for compaction and conversion."""

    def dead(self) -> int:
        """Rows that are deleted or replaced but still occupy space."""
        return 0

    def flush(self) -> None: ...

    def close(self) -> None: ...


def _gen_class(backend: str) -> type[Gen]:
    if backend == "exact":
        from services.vectorstore.exact import ExactGen
        return ExactGen
    if backend == "lance":
        from services.vectorstore.lance_store import LanceGen
        return LanceGen
    raise VectorStoreError(f"unknown vector store backend {backend!r}")


def _atomic_write(path: Path, text: str, durable: bool = True) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        if durable:
            os.fsync(f.fileno())
    os.replace(tmp, path)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class _Rebuild(Rebuild):
    def __init__(self, store: "GenerationalStore", gen: Gen, spec: ModelSpec, name: str):
        self._store, self._gen, self._spec, self.name = store, gen, spec, name
        self._done = False

    def upsert(self, ids, vectors, metadata=None) -> None:
        if self._done:
            raise VectorStoreError("rebuild already finished")
        ids, vecs, cores, extras = self._store._prepare(ids, vectors, metadata, self._spec.dim)
        if ids:
            self._gen.upsert(ids, vecs, cores, extras)

    def count(self) -> int:
        return self._gen.count()

    def commit(self) -> None:
        if self._done:
            raise VectorStoreError("rebuild already finished")
        self._store._commit_rebuild(self)
        self._done = True

    def abort(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._gen.close()
        finally:
            shutil.rmtree(self._gen.path, ignore_errors=True)


class _Prepared(_Rebuild):
    """A generation filled next to the live one that stays aside (``GenerationalStore.begin_prepare``)."""

    def commit(self) -> None:
        if self._done:
            raise VectorStoreError("rebuild already finished")
        self._store._commit_prepared(self)
        self._done = True


class GenerationalStore(VectorStore):
    """Namespace directory, ``CURRENT`` pointer, manifest, writer lock, rebuild/swap, compaction.

    ``backend`` names the backend used for *new* generations; an existing generation is opened
    with the backend its manifest names. ``spec`` is the model the caller expects (default: the
    configured one); a generation built with another space key makes the store stale.
    ``follow=True`` is for a process that only reads: it never writes and picks up another
    process's writes and swaps."""

    backend = "exact"

    def __init__(self, root: Path | str, namespace: str, *, backend: str | None = None,
                 spec: ModelSpec | None = None, follow: bool = False):
        if not namespace or not set(namespace) <= NAMESPACE_CHARS:
            raise ValueError(f"namespace must be lower-case letters, digits and underscores: {namespace!r}")
        self.root = Path(root)
        self.namespace = namespace
        self.dir = self.root / namespace
        self.backend = backend or self.backend
        self._expected = spec
        self._follow = follow
        self._lock = threading.RLock()      # guards the generation pointer
        self._wlock = threading.RLock()     # one writer at a time
        self._gen: Gen | None = None
        self._manifest: Manifest | None = None
        self._retired: list[tuple[Gen, float]] = []
        self._lock_fd: int | None = None
        self._last_follow = 0.0
        self._follow_stamp: tuple | None = None
        self._closed = False
        self._load_current()

    @property
    def closed(self) -> bool:
        return self._closed

    # ── pointer and manifest ────────────────────────────────────────────────

    def _read_current(self) -> str | None:
        try:
            name = (self.dir / "CURRENT").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return name or None

    def _manifest_path(self, gen_dir: Path) -> Path:
        return gen_dir / "manifest.json"

    def _read_manifest(self, gen_dir: Path) -> Manifest:
        d = json.loads(self._manifest_path(gen_dir).read_text(encoding="utf-8"))
        return Manifest(**{k: d[k] for k in Manifest.__dataclass_fields__ if k in d})

    def _stamp(self, name: str) -> tuple:
        try:
            return (name, self._manifest_path(self.dir / name).stat().st_mtime_ns)
        except OSError:
            return (name, None)

    def _load_current(self) -> None:
        name = self._read_current()
        if name is None:
            with self._lock:
                self._gen, self._manifest, self._follow_stamp = None, None, None
            return
        gen_dir = self.dir / name
        try:
            manifest = self._read_manifest(gen_dir)
            gen = _gen_class(manifest.backend).open(gen_dir, manifest.dim, read_only=self._follow)
        except BackendUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 — a damaged generation reads as "nothing here, rebuild"
            log.warning("Vector store %s: cannot open generation %s (%s); treating it as empty", self.namespace, name, exc)
            with self._lock:
                self._gen, self._manifest, self._follow_stamp = None, None, None
            return
        with self._lock:
            old = self._gen
            self._gen, self._manifest, self._follow_stamp = gen, manifest, self._stamp(name)
        if old is not None:
            self._retire(old)

    def _refresh_follow(self) -> None:
        if not self._follow or self._closed:
            return
        now = time.monotonic()
        if now - self._last_follow < 1.0:
            return
        self._last_follow = now
        name = self._read_current()
        if name is None:
            return
        if self._stamp(name) != self._follow_stamp:
            self._load_current()

    def exists(self) -> bool:
        return self._read_current() is not None

    def manifest(self) -> Manifest | None:
        self._refresh_follow()
        return self._manifest

    def _expected_spec(self) -> ModelSpec:
        return self._expected or current()

    def is_stale(self, spec: ModelSpec | None = None) -> bool:
        m = self.manifest()
        if m is None:
            return False
        return m.spec().space_key() != (spec or self._expected_spec()).space_key()

    def state(self) -> str:
        """``missing`` (nothing built yet), ``stale`` or ``ready``."""
        if self.manifest() is None:
            return "missing"
        return "stale" if self.is_stale() else "ready"

    def backend_mismatch(self, wanted: str | None = None) -> bool:
        m = self.manifest()
        return m is not None and m.backend != (wanted or self.backend)

    # ── writer lock and generations ─────────────────────────────────────────

    def _acquire_writer(self) -> None:
        if self._follow:
            raise VectorStoreError("this store was opened read-only (follow mode)")
        if self._lock_fd is not None:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl
        except ImportError:  # not POSIX: no cross-process lock
            self._lock_fd = -1
            return
        fd = os.open(str(self.dir / "LOCK"), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise StoreLockedError(f"vector store {self.namespace!r} is being written by another process") from exc
        self._lock_fd = fd
        # Another process may have written (or swapped the generation) before we got the lock.
        name = self._read_current()
        if name != (self._manifest.generation if self._manifest else None) or \
                (name is not None and self._stamp(name) != self._follow_stamp):
            self._load_current()
        self._gc()

    def _next_name(self) -> str:
        nums = [int(p.name[1:]) for p in self.dir.glob("g[0-9]*") if p.name[1:].isdigit()]
        return f"g{(max(nums) + 1 if nums else 1):06d}"

    def _gc(self) -> None:
        """Remove generation directories nothing points to (left by a crash or an old swap)."""
        keep = self._read_current()
        for p in self.dir.glob("g[0-9]*"):
            if p.name != keep and p.is_dir() and not (p / RETAINED).exists():
                shutil.rmtree(p, ignore_errors=True)
        self._prune_retained()

    def _retire(self, gen: Gen) -> None:
        with self._lock:
            self._retired.append((gen, time.monotonic()))

    def _reap(self, force: bool = False) -> None:
        with self._lock:
            keep, drop = [], []
            for gen, t in self._retired:
                (drop if force or time.monotonic() - t > RETIRE_GRACE_SECONDS else keep).append((gen, t))
            self._retired = keep
        for gen, _ in drop:
            try:
                gen.close()
            finally:
                if not self._follow and not (gen.path / RETAINED).exists():
                    shutil.rmtree(gen.path, ignore_errors=True)

    def _new_generation(self, spec: ModelSpec, backend: str) -> tuple[Gen, str]:
        name = self._next_name()
        gen = _gen_class(backend).create(self.dir / name, spec.dim)
        return gen, name

    def initialize(self, spec: ModelSpec | None = None) -> None:
        """Create an empty live generation for ``spec`` unless one exists."""
        with self._wlock:
            if self._gen is not None:
                return
            self._acquire_writer()
            spec = spec or self._expected_spec()
            gen, name = self._new_generation(spec, self.backend)
            self._publish(gen, name, spec)

    def _publish(self, gen: Gen, name: str, spec: ModelSpec) -> None:
        gen.flush()
        created = now_iso()
        manifest = Manifest(namespace=self.namespace, backend=gen.backend, model=spec.model, dim=spec.dim,
                            pooling=spec.pooling, query_prefix=spec.query_prefix, doc_prefix=spec.doc_prefix,
                            text_format=spec.text_format, generation=name, created_at=created, updated_at=created,
                            count=gen.count())
        _atomic_write(self._manifest_path(gen.path), json.dumps(manifest.to_dict(), indent=1))
        self._flip(gen, name, manifest)

    def _flip(self, gen: Gen, name: str, manifest: Manifest) -> None:
        """Make ``gen`` (its manifest written) the live generation: keep the old one when the space
        changes, flip ``CURRENT``, swap the in-memory pointer, retire the old generation."""
        old, old_m = self._gen, self._manifest
        if old is not None and old_m is not None and old.path.name != name and keep_generations() > 1 \
                and old_m.spec().space_key() != manifest.spec().space_key():
            self._write_marker(old.path, RETAINED)
        _atomic_write(self.dir / "CURRENT", name + "\n")
        _fsync_dir(self.dir)
        with self._lock:
            old = self._gen
            self._gen, self._manifest = gen, manifest
            self._follow_stamp = self._stamp(name)
        if old is not None:
            self._retire(old)
        self._reap()
        self._prune_retained()

    # ── kept, prepared and adopted generations ──────────────────────────────

    @staticmethod
    def _write_marker(gen_dir: Path, name: str) -> None:
        try:
            _atomic_write(gen_dir / name, json.dumps({"at": now_iso(), "epoch": time.time()}), durable=False)
        except OSError as exc:
            log.warning("Vector store: cannot mark %s as %s: %s", gen_dir, name, exc)

    @staticmethod
    def _marker_epoch(gen_dir: Path, name: str) -> float:
        try:
            return float(json.loads((gen_dir / name).read_text(encoding="utf-8")).get("epoch", 0.0))
        except (OSError, ValueError):
            return 0.0

    def _marked(self, marker: str) -> list[Path]:
        """Generation directories carrying ``marker``, newest first (RETAINED: ``g``, PREPARED: ``p``)."""
        pattern = "p[0-9]*" if marker == PREPARED else "g[0-9]*"
        found = [p for p in self.dir.glob(pattern) if p.is_dir() and (p / marker).exists()]
        return sorted(found, key=lambda p: (self._marker_epoch(p, marker), p.name), reverse=True)

    def _prune_retained(self) -> None:
        """Drop the oldest kept generations beyond ``keep_generations() - 1`` (the live one counts)."""
        if self._follow:
            return
        current = self._read_current()
        kept = [p for p in self._marked(RETAINED) if p.name != current]
        with self._lock:
            open_paths = {g.path for g, _ in self._retired}
        for p in kept[max(0, keep_generations() - 1):]:
            if p in open_paths:                  # still open for readers: _reap removes it without the marker
                (p / RETAINED).unlink(missing_ok=True)
            else:
                shutil.rmtree(p, ignore_errors=True)

    def retained(self) -> list[Manifest]:
        """Manifests of the kept (rollback) generations, newest first."""
        return self._manifests(self._marked(RETAINED))

    def prepared(self) -> list[Manifest]:
        """Manifests of the generations prepared with ``begin_prepare``, newest first."""
        return self._manifests(self._marked(PREPARED))

    def _manifests(self, dirs: list[Path]) -> list[Manifest]:
        out = []
        for d in dirs:
            try:
                out.append(self._read_manifest(d))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return out

    def begin_prepare(self, spec: ModelSpec | None = None, backend: str | None = None) -> Rebuild:
        """Fill a generation for ``spec`` that is *not* made live: ``commit()`` only stores it (named
        ``p######``, marked ``PREPARED``). The live generation, its writer and its readers are not
        touched, and no writer lock is needed, so this works in a process next to the running backend
        (also with ``follow=True``). A later start of the backend with this ``spec`` configured adopts
        it (``adopt_matching``) instead of re-embedding. One prepared generation is kept per namespace:
        committing another replaces it."""
        spec = spec or self._expected_spec()
        self.dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for p in self.dir.glob("p[0-9]*"):      # a crashed preparation, long dead
            if p.is_dir() and not (p / PREPARED).exists() and now - p.stat().st_mtime > STALE_PREPARE_SECONDS:
                shutil.rmtree(p, ignore_errors=True)
        cls = _gen_class(backend or self.backend)
        n = max([int(p.name[1:]) for p in self.dir.glob("p[0-9]*") if p.name[1:].isdigit()] + [0]) + 1
        while True:
            name = f"p{n:06d}"
            try:
                gen = cls.create(self.dir / name, spec.dim)
                break
            except FileExistsError:
                n += 1
        return _Prepared(self, gen, spec, name)

    def _commit_prepared(self, pr: "_Prepared") -> None:
        gen = pr._gen
        gen.flush()
        created = now_iso()
        spec = pr._spec
        manifest = Manifest(namespace=self.namespace, backend=gen.backend, model=spec.model, dim=spec.dim,
                            pooling=spec.pooling, query_prefix=spec.query_prefix, doc_prefix=spec.doc_prefix,
                            text_format=spec.text_format, generation=pr.name, created_at=created,
                            updated_at=created, count=gen.count())
        _atomic_write(self._manifest_path(gen.path), json.dumps(manifest.to_dict(), indent=1))
        gen.close()
        self._write_marker(gen.path, PREPARED)
        for other in self._marked(PREPARED):
            if other != gen.path:
                shutil.rmtree(other, ignore_errors=True)

    def discard_prepared(self) -> int:
        """Delete every prepared generation (an import that should not be used). Returns how many."""
        dirs = self._marked(PREPARED)
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)
        return len(dirs)

    def adopt_matching(self, spec: ModelSpec | None = None) -> str | None:
        """Make a finished generation of the configured space (``spec``) live instead of rebuilding:
        a prepared one first, else a kept one (a rollback by setting the old model again). Done only
        when the live generation is missing, stale or empty; never in follow mode. The generation
        it replaces is kept as the rollback target when the space differs. Returns ``"prepared"``,
        ``"retained"`` or None (nothing adopted)."""
        if self._follow or self._closed:
            return None
        spec = spec or self._expected_spec()
        key = spec.space_key()
        with self._wlock:
            m = self.manifest()
            if m is not None and m.spec().space_key() == key and self.count() > 0:
                return None
            if not self._adoptable(key):
                return None
            try:
                self._acquire_writer()          # may drop kept generations beyond the limit: list afterwards
            except StoreLockedError as exc:
                log.warning("Vector store %s: not adopting a finished generation: %s", self.namespace, exc)
                return None
            for kind, d in self._adoptable(key):
                name = self._activate(d, kind == "prepared")
                log.info("Vector store %s: adopted the %s generation for %s (%d vectors, now %s)",
                         self.namespace, kind, spec.model, self.count(), name)
                return kind
        return None

    def _adoptable(self, key: tuple) -> list[tuple[str, Path]]:
        """Finished generations of the space ``key`` that are not live: prepared ones, then kept ones."""
        current = self._read_current()
        out = []
        for kind, marker in (("prepared", PREPARED), ("retained", RETAINED)):
            for d in self._marked(marker):
                if d.name == current:
                    continue
                try:
                    if self._read_manifest(d).spec().space_key() == key:
                        out.append((kind, d))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return out

    def rollback(self) -> Manifest | None:
        """Make the newest kept generation live again (the one a model switch replaced) and keep
        the current one in its place, so a rollback can be undone by another. Returns the manifest
        of the generation now live, or None when nothing is kept. The writer lock is needed: stop
        the backend first."""
        with self._wlock:
            self._acquire_writer()
            current = self._read_current()
            for d in self._marked(RETAINED):
                if d.name == current:
                    continue
                try:
                    self._read_manifest(d)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                self._activate(d, False)
                return self.manifest()
        return None

    def _activate(self, gen_dir: Path, rename: bool) -> str:
        """Make the finished generation in ``gen_dir`` live. A prepared one (``rename``) first gets a
        regular name (``g######``) and its manifest is rewritten with it. Writer lock held."""
        if rename:
            new_dir = self.dir / self._next_name()
            os.rename(gen_dir, new_dir)
            m = self._read_manifest(new_dir)
            m = Manifest(**{**m.to_dict(), "generation": new_dir.name, "updated_at": now_iso()})
            _atomic_write(self._manifest_path(new_dir), json.dumps(m.to_dict(), indent=1))
            gen_dir = new_dir
        manifest = self._read_manifest(gen_dir)
        gen = _gen_class(manifest.backend).open(gen_dir, manifest.dim, read_only=False)
        (gen_dir / PREPARED).unlink(missing_ok=True)
        (gen_dir / RETAINED).unlink(missing_ok=True)
        self._flip(gen, gen_dir.name, manifest)
        return gen_dir.name

    def _touch_manifest(self, gen: Gen) -> None:
        m = self._manifest
        if m is None:
            return
        m = Manifest(**{**m.to_dict(), "updated_at": now_iso(), "count": gen.count()})
        try:
            _atomic_write(self._manifest_path(gen.path), json.dumps(m.to_dict(), indent=1), durable=False)
        except OSError as exc:  # the manifest is advisory; the data is committed already
            log.warning("Vector store %s: manifest not updated: %s", self.namespace, exc)
            return
        with self._lock:
            self._manifest = m
            self._follow_stamp = self._stamp(m.generation)

    # ── helpers for the operations ──────────────────────────────────────────

    def _prepare(self, ids, vectors, metadata, dim: int):
        ids = [str(i) for i in ids]
        vecs = unit_rows(vectors, dim) if len(ids) else np.zeros((0, dim), dtype=np.float32)
        metas = list(metadata) if metadata is not None else [None] * len(ids)
        if vecs.shape[0] != len(ids) or len(metas) != len(ids):
            raise ValueError("ids, vectors and metadata must have the same length")
        # The last occurrence of an id in one batch wins.
        last = {i: n for n, i in enumerate(ids)}
        if len(last) != len(ids):
            keep = sorted(last.values())
            ids, vecs, metas = [ids[n] for n in keep], vecs[keep], [metas[n] for n in keep]
        pairs = [split_metadata(m) for m in metas]
        return ids, vecs, [c for c, _ in pairs], [e for _, e in pairs]

    def _snapshot(self) -> tuple[Gen | None, Manifest | None]:
        self._refresh_follow()
        with self._lock:
            return self._gen, self._manifest

    def _read_gen(self) -> Gen | None:
        return self._snapshot()[0]

    def _vector_snapshot(self) -> tuple[Gen | None, Manifest | None]:
        gen, m = self._snapshot()
        if m is not None and m.spec().space_key() != self._expected_spec().space_key():
            raise StaleStoreError(
                f"vector store {self.namespace!r} holds vectors of {m.model!r} (dim {m.dim}); "
                "the configured model differs")
        return gen, m

    def _write_gen(self) -> Gen:
        self._acquire_writer()
        if self._gen is None:
            self.initialize()
        if self.is_stale():
            raise StaleStoreError(
                f"vector store {self.namespace!r} was built with another model; rebuild it (begin_rebuild) first")
        assert self._gen is not None
        return self._gen

    # ── operations ──────────────────────────────────────────────────────────

    def upsert(self, ids, vectors, metadata=None) -> None:
        with self._wlock:
            gen = self._write_gen()
            self._reap()
            ids, vecs, cores, extras = self._prepare(ids, vectors, metadata, self._manifest.dim)
            if not ids:
                return
            gen.upsert(ids, vecs, cores, extras)
            self._touch_manifest(gen)
            self._maybe_compact()

    def delete(self, ids) -> int:
        with self._wlock:
            gen = self._write_gen()
            n = gen.delete([str(i) for i in ids])
            if n:
                self._touch_manifest(gen)
                self._maybe_compact()
            return n

    def get(self, ids):
        gen, _ = self._vector_snapshot()
        return gen.get([str(i) for i in ids]) if gen else {}

    def metadata(self, ids=None):
        gen = self._read_gen()
        if gen is None:
            return {}
        return gen.metadata(None if ids is None else [str(i) for i in ids])

    def search(self, query_vector, k: int = 10, filter: dict | None = None) -> list[Hit]:
        clauses = compile_filter(filter)
        gen, m = self._vector_snapshot()
        if gen is None or m is None or k <= 0:
            return []
        return gen.search(unit_query(query_vector, m.dim), int(k), clauses)

    def count(self) -> int:
        gen = self._read_gen()
        return gen.count() if gen else 0

    def ids(self) -> list[str]:
        gen = self._read_gen()
        return gen.ids() if gen else []

    def all_vectors(self, filter: dict | None = None):
        clauses = compile_filter(filter)
        gen, _ = self._vector_snapshot()
        if gen is None:
            return [], np.zeros((0, self._expected_spec().dim), dtype=np.float32)
        return gen.all_vectors(clauses)

    # ── rebuild, compaction, conversion ─────────────────────────────────────

    def begin_rebuild(self, spec: ModelSpec | None = None, backend: str | None = None) -> Rebuild:
        """Start filling a new generation for ``spec`` (default: the configured model). The live
        generation stays readable until ``commit()`` swaps the new one in. Writes to the live
        generation during the build are not carried over, so the caller serialises (a stale
        store refuses writes anyway)."""
        self._acquire_writer()
        spec = spec or self._expected_spec()
        with self._wlock:
            gen, name = self._new_generation(spec, backend or self.backend)
        return _Rebuild(self, gen, spec, name)

    def _commit_rebuild(self, rb: _Rebuild) -> None:
        with self._wlock:
            self._publish(rb._gen, rb.name, rb._spec)

    def _maybe_compact(self) -> None:
        gen = self._gen
        if gen is None:
            return
        dead = gen.dead()
        if dead >= COMPACT_MIN_DEAD and dead > COMPACT_RATIO * gen.count():
            self.compact()

    def compact(self) -> None:
        """Rewrite the live rows into a fresh generation (no re-embedding) and swap it in."""
        with self._wlock:
            gen = self._write_gen()
            m = self._manifest
            rb = self.begin_rebuild(m.spec(), backend=gen.backend)
            try:
                for ids, vecs, metas in gen.iter_batches():
                    rb.upsert(ids, vecs, metas)
                rb.commit()
            except BaseException:
                rb.abort()
                raise

    def convert_backend(self, backend: str | None = None) -> bool:
        """Copy the live generation into a generation of ``backend`` (default: this store's) when
        its manifest names another one. No re-embedding. Returns True if it converted."""
        backend = backend or self.backend
        with self._wlock:
            gen = self._write_gen()
            if gen.backend == backend:
                return False
            rb = self.begin_rebuild(self._manifest.spec(), backend=backend)
            try:
                for ids, vecs, metas in gen.iter_batches():
                    rb.upsert(ids, vecs, metas)
                rb.commit()
            except BaseException:
                rb.abort()
                raise
            return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            gens = [g for g, _ in self._retired] + ([self._gen] if self._gen else [])
            self._retired, self._gen = [], None
        for g in gens:
            try:
                g.close()
            except Exception:  # noqa: BLE001
                pass
        if self._lock_fd is not None and self._lock_fd >= 0:
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
        self._lock_fd = None
