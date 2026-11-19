"""Where stores live and how callers get one: ``get_store("library")``.

Settings (environment, both optional):

    VECTOR_STORE      ``exact`` (default) or ``lance`` (needs the optional ``lancedb`` package;
                      without it the exact backend is used and a warning is logged)
    VECTOR_STORE_DIR  root directory, default ``/data/vectors``; when that is not writable a
                      temporary directory is used, as for the other data directories
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path

from services.vectorstore.base import GenerationalStore, VectorStore
from services.vectorstore.model_config import ModelSpec

log = logging.getLogger(__name__)

DEFAULT_DIR = "/data/vectors"


class ExactStore(GenerationalStore):
    """Memory-mapped matrix + SQLite, searched with numpy. No dependency beyond numpy."""
    backend = "exact"


class LanceStore(GenerationalStore):
    """LanceDB tables with an ANN index above a size threshold (optional package)."""
    backend = "lance"


_lock = threading.RLock()
_stores: dict[tuple[str, str, bool], GenerationalStore] = {}
_dir: Path | None = None
_warned: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning(message)


def vector_dir() -> Path:
    """The store root: ``VECTOR_STORE_DIR`` or ``/data/vectors``, else a temporary directory."""
    global _dir
    if _dir is not None:
        return _dir
    configured = os.environ.get("VECTOR_STORE_DIR", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates += [Path(DEFAULT_DIR), Path(tempfile.gettempdir()) / "papermanager-vectors"]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.access(path, os.W_OK):
                _dir = path
                return path
        except OSError:
            continue
    raise RuntimeError("No writable directory for the vector store")


def backend_name() -> str:
    """``exact`` or ``lance`` as configured, falling back to exact when LanceDB cannot be imported."""
    want = os.environ.get("VECTOR_STORE", "").strip().lower() or "exact"
    if want == "exact":
        return "exact"
    if want != "lance":
        _warn_once("unknown:" + want, f"VECTOR_STORE={want!r} is not known (exact, lance); using exact")
        return "exact"
    try:
        import lancedb  # noqa: F401
    except ImportError:
        _warn_once("lance-missing", "VECTOR_STORE=lance but the 'lancedb' package is not installed; using exact")
        return "exact"
    return "lance"


def _make(root: Path, namespace: str, follow: bool, spec: ModelSpec | None) -> GenerationalStore:
    cls = LanceStore if backend_name() == "lance" else ExactStore
    return cls(root, namespace, spec=spec, follow=follow)


def get_store(namespace: str, *, create: bool = True, follow: bool = False,
              spec: ModelSpec | None = None) -> VectorStore | None:
    """The shared store of ``namespace``, opened on first use.

    ``create=False`` returns None while the namespace has not been built (nothing is created on
    disk), which is what a request path wants. ``follow=True`` is for a process that only reads
    (the MCP server): it never writes and picks up the writing process's changes. New namespaces
    use the configured backend; existing ones keep theirs until ``convert_backend()``."""
    root = vector_dir()
    key = (str(root), namespace, follow)
    with _lock:
        store = _stores.get(key)
        if store is not None:
            return store
        probe = root / namespace / "CURRENT"
        if not probe.exists() and not create:
            return None
        store = _make(root, namespace, follow, spec)
        if store.manifest() is None and not follow and create:
            store.initialize(spec)
        elif store.manifest() is None and follow:
            store.close()
            return None
        _stores[key] = store
        return store


def reset() -> None:
    """Close every open store and forget the directory (tests; after changing the environment)."""
    global _dir
    with _lock:
        for s in _stores.values():
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
        _stores.clear()
        _dir = None
        _warned.clear()
