"""Embedding index of the library for semantic and hybrid search.

Every Paper's title plus abstract (or, failing that, its AI summary) is embedded with the
conference explorer's BAAI/bge-small-en-v1.5 model (services.conferences.embedder, 384-dim
unit vectors, CPU) into ``<dir>/emb.npy`` with the paper ids and a hash of each embedded
text in ``<dir>/meta.json``. ``<dir>`` is ``LIBRARY_SEARCH_DIR`` or ``/data/library_search``.

A daemon thread started at backend startup loads the file, then syncs every
``LIBRARY_SEMANTIC_INTERVAL`` seconds (default 600): papers that are new or whose text
changed are embedded, deleted papers are dropped, the file is rewritten atomically. Nothing
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

log = logging.getLogger(__name__)

DIM = 384
_TEXT_MAX = 1500
_CHUNK = 256
_SAVE_EVERY = 2048
# A semantic hit must reach MIN_SIM and lie within REL_SIM of the best hit; at most MAX_HITS.
MIN_SIM = float(os.environ.get("LIBRARY_SEMANTIC_MIN_SIM", "0.62"))
REL_SIM = float(os.environ.get("LIBRARY_SEMANTIC_REL_SIM", "0.12"))
MAX_HITS = 100

_lock = threading.RLock()       # guards the arrays below
_sync_lock = threading.Lock()   # one sync at a time
_ids: list[str] = []
_hashes: list[str] = []
_emb = np.zeros((0, DIM), dtype=np.float32)
_state: dict = {"state": "idle", "done": 0, "todo": 0, "papers": 0, "error": None,
                "last_sync": None, "last_build_seconds": None}
_thread: threading.Thread | None = None
_dir: Path | None = None


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


def _model_name() -> str:
    from services.conferences.embedder import MODEL
    return MODEL


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
        out["indexed"] = len(_ids)
    out["enabled"] = enabled()
    try:
        from services.conferences.embedder import ready
        out["model_loaded"] = ready()
    except Exception:  # noqa: BLE001
        out["model_loaded"] = False
    return out


# ── disk ──────────────────────────────────────────────────────────────────────

def _load() -> None:
    global _ids, _hashes, _emb
    d = data_dir()
    meta_p, emb_p = d / "meta.json", d / "emb.npy"
    if not meta_p.exists() or not emb_p.exists():
        return
    try:
        meta = json.loads(meta_p.read_text())
        emb = np.load(emb_p)
        if meta.get("model") != _model_name() or emb.shape != (len(meta["ids"]), DIM):
            log.info("Library embedding file is for another model or damaged; rebuilding")
            return
        with _lock:
            _ids, _hashes, _emb = list(meta["ids"]), list(meta["hashes"]), emb.astype(np.float32)
        log.info("Library embeddings loaded: %d papers", len(_ids))
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read the library embeddings (%s); rebuilding", exc)


def _save() -> None:
    d = data_dir()
    with _lock:
        ids, hashes, emb = list(_ids), list(_hashes), _emb.copy()
    tmp_emb, tmp_meta = d / "emb.tmp.npy", d / "meta.tmp.json"
    np.save(tmp_emb, emb)
    tmp_meta.write_text(json.dumps({"model": _model_name(), "dim": DIM, "ids": ids, "hashes": hashes,
                                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    os.replace(tmp_emb, d / "emb.npy")
    os.replace(tmp_meta, d / "meta.json")


# ── build ─────────────────────────────────────────────────────────────────────

def _fetch_texts(driver) -> dict[str, str]:
    with driver.session() as s:
        return {r["id"]: paper_text(r["title"], r["abstract"], r["summary"]) for r in s.run(
            "MATCH (p:Paper) RETURN p.id AS id, p.title AS title, p.abstract AS abstract, "
            "p.summary AS summary")}


def sync(driver=None) -> dict:
    """Bring the index in line with the library: embed new and changed papers, drop
    deleted ones. Returns counts. Safe to call from any thread; concurrent calls skip."""
    global _ids, _hashes, _emb
    if not _sync_lock.acquire(blocking=False):
        return {"skipped": True}
    try:
        from services.conferences.embedder import embed

        if driver is None:
            from db.connection import get_driver
            driver = get_driver()
        t0 = time.perf_counter()
        texts = _fetch_texts(driver)
        want = {pid: text_hash(t) for pid, t in texts.items()}
        with _lock:
            keep = [i for i, (pid, h) in enumerate(zip(_ids, _hashes)) if want.get(pid) == h]
            removed = len(_ids) - len(keep)
            if removed:
                _ids = [_ids[i] for i in keep]
                _hashes = [_hashes[i] for i in keep]
                _emb = _emb[keep]
            have = set(_ids)
        todo = [pid for pid in texts if pid not in have]
        with _lock:
            _state.update(state="building" if todo else "ready", done=0, todo=len(todo),
                          papers=len(texts), error=None)
        unsaved = removed
        for s in range(0, len(todo), _CHUNK):
            chunk = todo[s:s + _CHUNK]
            vecs = embed([texts[pid] for pid in chunk])
            with _lock:
                _ids = _ids + chunk
                _hashes = _hashes + [want[pid] for pid in chunk]
                _emb = np.vstack([_emb, vecs]) if len(_emb) else vecs
                _state["done"] = s + len(chunk)
            unsaved += len(chunk)
            if unsaved >= _SAVE_EVERY:
                _save()
                unsaved = 0
        if unsaved or not (data_dir() / "emb.npy").exists():
            _save()
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
    """For processes without the sync thread (the MCP server): read the index file and, unless
    PM_EMBED_URL lets the backend embed the queries, load the model. Blocks for a few seconds
    once in that case; never call it in a web request."""
    if not enabled():
        return False
    with _lock:
        have = bool(_ids)
    if not have:
        _load()
    from services.conferences.embedder import embed, ready, remote_url
    # With PM_EMBED_URL the backend embeds the queries (query() falls back to a local
    # load if it cannot), so the model is not loaded here up front.
    if not ready() and not remote_url():
        embed(["warm up"])
    with _lock:
        return bool(_ids)


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
    with _lock:
        ids, emb = _ids, _emb
    if not ids or not q.strip():
        return []
    v = embed_query(q)
    sims = emb @ v
    k = min(k, len(ids))
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    return [(ids[i], float(sims[i])) for i in top]


def cut(cands: list, min_sim: float | None = None, rel_sim: float | None = None) -> list:
    """Keep hits (objects with ``.semantic``, sorted best first) above the absolute and
    relative similarity floors, at most MAX_HITS."""
    if not cands:
        return []
    min_sim = MIN_SIM if min_sim is None else min_sim
    rel_sim = REL_SIM if rel_sim is None else rel_sim
    floor = max(min_sim, (cands[0].semantic or 0) - rel_sim)
    return [c for c in cands if (c.semantic or 0) >= floor][:MAX_HITS]
