"""Embedding index of the library for semantic and hybrid search.

Every Paper's title plus abstract (or, failing that, its AI summary) is embedded with the
configured embedding model (services.vectorstore.model_config, services.conferences.embedder;
by default BAAI/bge-small-en-v1.5, 384-dim unit vectors, CPU) into the ``library`` namespace of
the vector store (services.vectorstore), each vector with a hash of its text. Index files from
before the vector store (``<dir>/emb.npy`` + ``meta.json``, ``<dir>`` = ``LIBRARY_SEARCH_DIR`` or
``/data/library_search``) are migrated once without re-embedding, and are still rewritten after
each sync that changed something (``VECTOR_STORE_LEGACY_EXPORT=0`` stops that) because the topic
map reads them. A store built with another model than the configured one is *stale*: it is
rebuilt in the background and search answers lexically until it is done.

A daemon thread started at backend startup opens the store, then syncs every
``LIBRARY_SEMANTIC_INTERVAL`` seconds (default 600): papers that are new or whose text
changed are embedded, deleted papers are dropped; every batch is committed atomically. Nothing
here runs in a request except ``query()``, which never loads the model: until the builder
thread has loaded it, semantic search reports ``state`` and returns no hits, and the search
falls back to lexical.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from services import vectorstore
from services.vectorstore import migrate, model_config
from services.vectorstore.base import now_iso

log = logging.getLogger(__name__)

_TEXT_MAX = 1500
_CHUNK = 256
# A semantic hit must reach MIN_SIM and lie within REL_SIM of the best hit; at most MAX_HITS.
MIN_SIM = float(os.environ.get("LIBRARY_SEMANTIC_MIN_SIM", "0.62"))
REL_SIM = float(os.environ.get("LIBRARY_SEMANTIC_REL_SIM", "0.12"))
MAX_HITS = 100

_lock = threading.RLock()       # guards _state
_sync_lock = threading.Lock()   # one sync at a time
_state: dict = {"state": "idle", "done": 0, "todo": 0, "papers": 0, "error": None,
                "last_sync": None, "last_build_seconds": None}
_thread: threading.Thread | None = None
_dir: Path | None = None
_follow_store = None            # set in a process without the sync thread (MCP): reads what the backend writes
_warned_open = False
_adopted = False                # a finished generation was made live: emb.npy + meta.json are for the old model


def enabled() -> bool:
    return os.environ.get("LIBRARY_SEMANTIC", "true").strip().lower() not in ("0", "false", "no", "off")


def data_dir() -> Path:
    global _dir
    if _dir is not None:
        return _dir
    configured = os.environ.get("LIBRARY_SEARCH_DIR")
    candidates = [Path(configured)] if configured else []
    candidates += [Path("/data/library_search"), Path(tempfile.gettempdir()) / "papermanager-library-search"]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.access(path, os.W_OK):
                _dir = path
                return path
        except OSError:
            continue
    raise RuntimeError("No writable directory for the library search index")


def paper_text(title: str | None, abstract: str | None, summary: str | None) -> str:
    """The text a paper is embedded by: its title, then the abstract or the summary."""
    from services.library_search.query import clean

    body = (abstract or "").strip() or clean(summary or "")
    return ((title or "").strip() + "\n" + body[:_TEXT_MAX]).strip()


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def status() -> dict:
    with _lock:
        out = dict(_state)
    st = _peek() if enabled() else None
    out["indexed"] = st.count() if st is not None and not st.is_stale() else 0
    out["enabled"] = enabled()
    try:
        from services.conferences.embedder import ready
        out["model_loaded"] = ready()
    except Exception:  # noqa: BLE001
        out["model_loaded"] = False
    return out


# ── the vector store ──────────────────────────────────────────────────────────

def _peek():
    """The library namespace if it has been built, else None. Never creates anything and never
    raises: a request must not fail because the store is unavailable."""
    global _warned_open
    fs = _follow_store
    if fs is not None and not fs.closed:
        return fs
    try:
        return vectorstore.get_store("library", create=False)
    except Exception as exc:  # noqa: BLE001
        if not _warned_open:
            _warned_open = True
            log.warning("Library vector store unavailable: %s", exc)
        return None


def peek():
    """The library namespace as this process reads it (the follower in the MCP server), or None."""
    return _peek()


def snapshot() -> tuple[list[str], np.ndarray]:
    """Every indexed paper id with its vector (a copy); empty while the store is missing or stale.
    For the paper feed, which compares candidates with the whole library."""
    st = _peek()
    if st is None or st.is_stale():
        return [], np.zeros((0, model_config.dim()), dtype=np.float32)
    return st.all_vectors()


def _adopt(st) -> bool:
    """Use a generation made elsewhere for the configured model (``scripts/vectors_import.py``, or a
    kept one after setting the old model again) instead of a CPU rebuild. See ``adopt_matching``."""
    global _adopted
    try:
        kind = st.adopt_matching(model_config.current())
    except Exception as exc:  # noqa: BLE001 — never stop the sync: it rebuilds as before
        log.warning("Library vectors: could not adopt a finished generation (%s)", exc)
        return False
    if kind:
        log.info("Library embeddings: adopted a %s generation (%d papers); only changed papers are embedded now",
                 kind, st.count())
        _adopted = True
    return bool(kind)


def _load() -> None:
    """Open the library namespace, building it from the old emb.npy/meta.json the first time
    (no re-embedding). Runs in the sync thread."""
    try:
        migrate.migrate_library(data_dir(), model_config.current())
        st = vectorstore.get_store("library")
        _adopt(st)
        if st.is_stale():
            log.info("Library vectors were built with another embedding model; rebuilding")
        else:
            log.info("Library embeddings loaded: %d papers", st.count())
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not open the library vector store (%s)", exc)


def _export_legacy(st, spec) -> None:
    """Rewrite emb.npy + meta.json from the store (atomic), for readers of the old files such as
    the topic map. ``VECTOR_STORE_LEGACY_EXPORT=0`` turns it off."""
    if os.environ.get("VECTOR_STORE_LEGACY_EXPORT", "1").strip().lower() in ("0", "false", "no", "off"):
        return
    d = data_dir()
    ids, emb = st.all_vectors()
    meta = st.metadata(ids)
    tmp_emb, tmp_meta = d / "emb.tmp.npy", d / "meta.tmp.json"
    np.save(tmp_emb, emb)
    tmp_meta.write_text(json.dumps({"model": spec.model, "dim": spec.dim, "ids": ids,
                                    "hashes": [meta.get(i, {}).get("hash", "") for i in ids],
                                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    os.replace(tmp_emb, d / "emb.npy")
    os.replace(tmp_meta, d / "meta.json")


# ── build ─────────────────────────────────────────────────────────────────────

def _fetch_texts(driver) -> dict[str, str]:
    with driver.session() as s:
        return {r["id"]: paper_text(r["title"], r["abstract"], r["summary"]) for r in s.run(
            "MATCH (p:Paper) RETURN p.id AS id, p.title AS title, p.abstract AS abstract, "
            "p.summary AS summary")}


def _embed_into(target, todo: list[str], texts: dict[str, str], want: dict[str, str], embed) -> None:
    """Embed ``todo`` in chunks and upsert each chunk (a store or a rebuild) as it is done."""
    stamp = now_iso()
    for s in range(0, len(todo), _CHUNK):
        chunk = todo[s:s + _CHUNK]
        vecs = embed([texts[pid] for pid in chunk])
        target.upsert(chunk, vecs, [{"kind": "paper", "source": "library", "hash": want[pid], "added_at": stamp}
                                    for pid in chunk])
        with _lock:
            _state["done"] = s + len(chunk)


def sync(driver=None) -> dict:
    """Bring the index in line with the library: embed new and changed papers, drop
    deleted ones. Returns counts. Safe to call from any thread; concurrent calls skip."""
    if not _sync_lock.acquire(blocking=False):
        return {"skipped": True}
    try:
        from services.conferences.embedder import embed

        if driver is None:
            from db.connection import get_driver
            driver = get_driver()
        t0 = time.perf_counter()
        spec = model_config.current()
        st = vectorstore.get_store("library")
        _adopt(st)
        if not st.is_stale(spec) and st.backend_mismatch():
            st.convert_backend()          # VECTOR_STORE changed: copy into the configured backend
        texts = _fetch_texts(driver)
        want = {pid: text_hash(t) for pid, t in texts.items()}
        if st.is_stale(spec):
            # Another embedding model than the one the store was built with: fill a new
            # generation next to the old one and swap it in when complete (no mixed spaces).
            log.info("Library embeddings: rebuilding for %s (%d dims)", spec.model, spec.dim)
            todo, removed = list(texts), 0
            with _lock:
                _state.update(state="building" if todo else "ready", done=0, todo=len(todo),
                              papers=len(texts), error=None)
            rb = st.begin_rebuild(spec)
            try:
                _embed_into(rb, todo, texts, want, embed)
                rb.commit()
            except BaseException:
                rb.abort()
                raise
        else:
            have = st.metadata()
            gone = [pid for pid in have if pid not in want]
            changed = {pid for pid, m in have.items() if pid in want and m.get("hash") != want[pid]}
            removed = len(gone) + len(changed)
            if gone:
                st.delete(gone)
            todo = [pid for pid in texts if pid not in have or pid in changed]
            with _lock:
                _state.update(state="building" if todo else "ready", done=0, todo=len(todo),
                              papers=len(texts), error=None)
            _embed_into(st, todo, texts, want, embed)
        global _adopted
        if todo or removed or _adopted or not (data_dir() / "emb.npy").exists():
            _export_legacy(st, spec)
            _adopted = False
        took = round(time.perf_counter() - t0, 1)
        with _lock:
            _state.update(state="ready", last_sync=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            if todo:
                _state["last_build_seconds"] = took
        if todo or removed:
            log.info("Library embeddings synced: %d embedded, %d removed, %.1fs", len(todo), removed, took)
        return {"embedded": len(todo), "removed": removed, "seconds": took}
    except Exception as exc:
        with _lock:
            _state.update(state="error", error=str(exc)[:300])
        log.warning("Library embedding sync failed: %s", exc)
        raise
    finally:
        _sync_lock.release()


def _loop(interval: float) -> None:
    with _lock:
        _state["state"] = "loading"
    _load()
    try:  # load the model here, never in a request
        from services.conferences.embedder import embed
        embed(["warm up"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Embedding model could not be loaded: %s", exc)
    while True:
        try:
            sync()
        except Exception:  # noqa: BLE001 — logged in sync; retry next round
            pass
        time.sleep(interval)


def ensure_loaded() -> bool:
    """For processes without the sync thread (the MCP server): open the index the backend
    writes (read-only, following its changes) and, unless PM_EMBED_URL lets the backend embed
    the queries, load the model. Blocks for a few seconds once in that case; never call it in a
    web request."""
    global _follow_store
    if not enabled():
        return False
    st = _follow_store if _follow_store is not None and not _follow_store.closed else None
    if st is None:
        try:
            st = vectorstore.get_store("library", create=False, follow=True)
            if st is None:  # the backend has not migrated the old files yet: do it here, once
                migrate.migrate_library(data_dir(), model_config.current())
                st = vectorstore.get_store("library", create=False, follow=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("Library index not opened: %s", exc)
        _follow_store = st
    from services.conferences.embedder import embed, ready, remote_url
    # With PM_EMBED_URL the backend embeds the queries (query() falls back to a local
    # load if it cannot), so the model is not loaded here up front.
    if not ready() and not remote_url():
        embed(["warm up"])
    return bool(st is not None and not st.is_stale() and st.count())


def start_background() -> None:
    """Start the loader/sync thread once (no-op when LIBRARY_SEMANTIC=false)."""
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return
    interval = float(os.environ.get("LIBRARY_SEMANTIC_INTERVAL", "600"))
    _thread = threading.Thread(target=_loop, args=(interval,), name="library-embeddings", daemon=True)
    _thread.start()


# ── query ─────────────────────────────────────────────────────────────────────

def query(q: str, k: int = 200) -> list[tuple[str, float]]:
    """``[(paper_id, cosine)]`` of the ``k`` nearest papers, best first; empty while the
    model is not loaded or nothing is indexed yet (this never loads the model)."""
    from services.conferences.embedder import embed_query, ready, remote_url

    # The backend never loads the model in a request; a process with PM_EMBED_URL (the MCP
    # server) may: embed_query asks the backend first and loads the model only if that fails.
    if not enabled() or not (ready() or remote_url()):
        return []
    st = _peek()
    if st is None or st.is_stale() or not st.count() or not q.strip():
        return []
    v = embed_query(q)
    try:
        hits = st.search(v, k)
    except vectorstore.StaleStoreError:   # swapped for a rebuild between the check and the search
        return []
    return [(h.id, h.score) for h in hits]


def cut(cands: list, min_sim: float | None = None, rel_sim: float | None = None) -> list:
    """Keep hits (objects with ``.semantic``, sorted best first) above the absolute and
    relative similarity floors, at most MAX_HITS."""
    if not cands:
        return []
    min_sim = MIN_SIM if min_sim is None else min_sim
    rel_sim = REL_SIM if rel_sim is None else rel_sim
    floor = max(min_sim, (cands[0].semantic or 0) - rel_sim)
    return [c for c in cands if (c.semantic or 0) >= floor][:MAX_HITS]
