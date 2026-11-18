"""The digest: score stored candidates for one user and say why.

Everything the user's library contributes is read per request with the user's visibility,
so the result only ever reflects papers that user may see. The fitted model is cached per
user and refitted when the set of signals changes or after 24 hours.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np

from services.feed import config, library, model
from services.feed.store import DIM, FeedStore

log = logging.getLogger(__name__)

NEIGHBOURS = 3

_lock = threading.Lock()
_models: dict[str, model.Model] = {}
_info: dict[str, dict] = {}          # last digest facts per user, for the status strip
_fitting: set[str] = set()


def forget(user: str | None = None) -> None:
    """Drop cached models (all, or one user's). For tests and after bulk changes."""
    with _lock:
        if user is None:
            _models.clear()
            _info.clear()
        else:
            _models.pop(user, None)
            _info.pop(user, None)


def user_info(user: str) -> dict:
    with _lock:
        return dict(_info.get(user) or {})


# ── training set ──────────────────────────────────────────────────────────────

def _entries(rows: list[dict], single_user: bool, labels: dict[str, tuple[int, str]]):
    """(positives, negatives) as lists of (key, kind, weight, added_at). ``kind`` is 'lib' or 'feed'."""
    pos, neg = [], []
    for r in rows:
        # Rating, bookmark and reading status are global: they speak for this user only on a
        # single-user instance or for papers the user added. "Kept" is derived per user.
        shared = single_user or r.get("mine")
        kept = bool(not r.get("stub") and r.get("has_text") and (r.get("mine") or r.get("in_project")))
        lab = model.library_label(
            r.get("rating") if shared else None, r.get("bookmarked") if shared else None,
            r.get("status") if shared else None, r.get("highlights") if shared else None, kept=kept)
        if lab is None:
            continue
        (pos if lab[0] > 0 else neg).append((r["id"], "lib", lab[1], str(r.get("created_at") or "")))
    for cid, (value, at) in labels.items():
        (pos if value == 1 else neg).append((cid, "feed", 1.0, at))
    return pos, neg


def _signature(pos, neg) -> str:
    h = hashlib.sha1()
    for tag, items in (("p", pos), ("n", neg)):
        for key, kind, w, _ in sorted(items):
            h.update(f"{tag}|{kind}|{key}|{w};".encode())
    return h.hexdigest()


def build_training_set(store: FeedStore, pos, neg, lib_vec: dict[str, np.ndarray], signature: str,
                       user: str) -> model.TrainingSet:
    cand_vec = store.get_embeddings([k for k, kind, *_ in pos + neg if kind == "feed"])

    def vec(key, kind):
        return (lib_vec if kind == "lib" else cand_vec).get(key)

    p = [(vec(k, kind), w, at) for k, kind, w, at in pos if vec(k, kind) is not None]
    n = [(vec(k, kind), w) for k, kind, w, _ in neg if vec(k, kind) is not None]
    labelled = set(store.labels(user))
    return model.TrainingSet(
        pos=model.stack([v for v, _, _ in p]), pos_weight=np.array([w for _, w, _ in p], dtype=np.float64),
        pos_time=[at for _, _, at in p],
        neg=model.stack([v for v, _ in n]), neg_weight=np.array([w for _, w in n], dtype=np.float64),
        random_neg=store.sample_embeddings(labelled, model.RANDOM_NEGATIVES_MAX),
        signature=(signature,),
    )


def _fit_in_background(user: str, ts: model.TrainingSet) -> None:
    def work():
        try:
            m = model.fit_model(ts)
            with _lock:
                _models[user] = m
        except Exception:  # noqa: BLE001
            log.exception("Feed: background fit failed")
        finally:
            with _lock:
                _fitting.discard(user)

    with _lock:
        if user in _fitting:
            return
        _fitting.add(user)
    threading.Thread(target=work, name="feed-fit", daemon=True).start()


def _model_for(store: FeedStore, user: str, pos, neg, lib_vec, signature: str) -> model.Model | None:
    """The classifier for this signal set: the cached one, a fresh fit when that is cheap, or
    None (similarity ranking now, a fit in the background)."""
    with _lock:
        cached = _models.get(user)
    if cached and cached.signature == (signature,) and time.time() - cached.fitted_at < model.MODEL_MAX_AGE:
        return cached
    ts = build_training_set(store, pos, neg, lib_vec, signature, user)
    if len(ts.pos) < model.MIN_POSITIVES:
        return None
    if ts.n_rows <= model.FIT_MAX_ROWS:
        m = model.fit_model(ts)
        with _lock:
            _models[user] = m
        return m
    _fit_in_background(user, ts)
    return cached if cached and cached.signature == (signature,) else None


# ── digest ────────────────────────────────────────────────────────────────────

def _wanted(c, cfg: config.FeedConfig, source: str | None) -> bool:
    if c.source not in cfg.sources or (source and c.source != source):
        return False
    if c.source == "arxiv":
        return bool(set(c.categories) & set(cfg.arxiv_categories))
    return True


def digest(driver, store: FeedStore, user: str, *, days: int | None = None, skip: int = 0, limit: int = 30,
           include_rated: bool = False, source: str | None = None, now: datetime | None = None) -> dict:
    from services.library_lookup import build_index, match_item

    cfg = store.get_config(user) or config.FeedConfig()
    days = days or cfg.digest_days
    now = now or datetime.now(timezone.utc)
    rows, single_user = library.visible_papers(driver, user)
    labels = store.labels(user)
    pos, neg = _entries(rows, single_user, labels)

    visible = {r["id"] for r in rows}
    lib_ids, lib_mat = library.vectors(store, visible)
    lib_vec = {pid: lib_mat[i] for i, pid in enumerate(lib_ids)}

    pool = [c for c in store.embedded_since((now - timedelta(days=days)).date().isoformat())
            if _wanted(c, cfg, source) and (include_rated or c.id not in labels)]

    sig = _signature(pos, neg)
    n_pos_vec = sum(1 for k, kind, *_ in pos if kind == "lib" and k in lib_vec) \
        + sum(1 for k, kind, *_ in pos if kind == "feed")
    m = _model_for(store, user, pos, neg, lib_vec, sig) if n_pos_vec >= model.MIN_POSITIVES and pool else None

    X = np.vstack([c.emb for c in pool]) if pool else np.zeros((0, DIM), dtype=np.float32)
    if m is not None:
        mode, scores = "classifier", m.score(X)
    elif n_pos_vec >= model.MIN_POSITIVES and not pool:
        mode, scores = "classifier", np.zeros(0)
    elif n_pos_vec > 0:
        mode = "similarity"
        cand_pos = store.get_embeddings([k for k, kind, *_ in pos if kind == "feed"])
        P = model.stack([lib_vec[k] for k, kind, *_ in pos if kind == "lib" and k in lib_vec]
                        + list(cand_pos.values()))
        scores = model.similarity_scores(P, X)
    else:
        mode, scores = "newest", None

    index = build_index([[r["id"], r.get("doi"), r.get("title")] for r in rows])
    titles = {r["id"]: r.get("title") or "" for r in rows}

    items = []
    for i, c in enumerate(pool):
        score = None if scores is None else float(scores[i])
        if score is not None and cfg.min_score > 0 and score < cfg.min_score:
            continue
        ids = []
        arxiv_doi = f"arXiv:{c.ext_id}" if c.source == "arxiv" else c.doi
        for doi in (arxiv_doi, c.doi):
            if doi:
                _, ids = match_item(doi, "", index)
                if ids:
                    break
        if not ids:
            _, ids = match_item("", c.title, index)
        items.append((c, score, ids[0] if ids else None, i))

    if scores is None:
        items.sort(key=lambda t: t[0].published, reverse=True)
        items.sort(key=lambda t: t[2] is not None)           # stable: papers already owned go last
    else:
        items.sort(key=lambda t: (t[2] is not None, -t[1]))
    total = len(items)
    page = items[skip:skip + limit]

    out = []
    for c, score, lib_id, i in page:
        neighbours = []
        if len(lib_ids):
            sims = lib_mat @ X[i]
            if lib_id in lib_vec:
                sims[lib_ids.index(lib_id)] = -1.0    # a paper the user owns is not its own neighbour
            for j in np.argsort(-sims)[:NEIGHBOURS]:
                if sims[j] < 0:
                    break
                neighbours.append({"paper_id": lib_ids[j], "title": titles.get(lib_ids[j], ""),
                                   "similarity": round(float(sims[j]), 3)})
        out.append({**c.to_public(), "score": None if score is None else round(score, 4),
                    "neighbours": neighbours, "in_library": lib_id is not None, "library_paper_id": lib_id,
                    "my_label": labels[c.id][0] if c.id in labels else None})

    info = {"mode": mode, "positives": n_pos_vec, "quality": m.quality if m else None}
    with _lock:
        _info[user] = info
    return {"mode": mode, "total": total, "days": days, "skip": skip, "limit": limit,
            "positives": n_pos_vec, "quality": info["quality"], "items": out}
