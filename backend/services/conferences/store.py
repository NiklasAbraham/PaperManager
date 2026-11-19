"""Build, keep and query conference datasets.

A build runs in one background worker thread, one conference at a time:

    queued -> fetching -> normalising -> embedding -> ready
                 \\-> unavailable (the source has no file for that year)
                 \\-> error

After ``normalising`` the dataset is already on disk and the institution views work;
areas and semantic topic search follow once ``embedding`` is done. Files live in
``<data dir>/<key>/``: ``dataset.json`` (papers, institutions, areas), ``emb.npy``
(float16 unit vectors of title + abstract, one row per paper), ``emb_title.npy`` (the
same for the title alone, written only when some papers have an abstract or keywords;
cross-conference search compares conferences on these) and ``status.json``.

The data directory is ``CONFERENCE_DATA_DIR``, else ``/data/conferences`` (the backend's
Docker volume), else a temp directory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import re
import tempfile
import threading
import time
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from services.conferences import areas as area_mod
from services.conferences import catalog, institutions, sources
from services.vectorstore import model_config

log = logging.getLogger(__name__)

# ── locations ─────────────────────────────────────────────────────────────────

_data_dir: Path | None = None


def data_dir() -> Path:
    global _data_dir
    if _data_dir is not None:
        return _data_dir
    configured = os.environ.get("CONFERENCE_DATA_DIR")
    candidates = [Path(configured)] if configured else []
    candidates += [Path("/data/conferences"), Path(tempfile.gettempdir()) / "papermanager-conferences"]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.access(path, os.W_OK):
                _data_dir = path
                return path
        except OSError:
            continue
    raise RuntimeError("No writable directory for conference data")


def _dir(key: str) -> Path:
    return data_dir() / key


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


# ── status ────────────────────────────────────────────────────────────────────

_status_lock = threading.Lock()
_status: dict[str, dict] = {}


def status(key: str) -> dict:
    with _status_lock:
        if key in _status:
            return dict(_status[key])
    p = _dir(key) / "status.json"
    if p.exists():
        try:
            st = json.loads(p.read_text())
            # A build that was running when the backend stopped never finished.
            if st.get("state") in ("queued", "fetching", "normalising", "embedding"):
                st["state"] = "ready" if (_dir(key) / "emb.npy").exists() else (
                    "partial" if (_dir(key) / "dataset.json").exists() else "none")
            return st
        except Exception:  # noqa: BLE001
            pass
    return {"state": "none"}


def _set_status(key: str, state: str, **extra) -> None:
    st = {"state": state, "updated_at": _now(), **extra}
    with _status_lock:
        _status[key] = st
    try:
        _dir(key).mkdir(parents=True, exist_ok=True)
        _write_json(_dir(key) / "status.json", st)
    except OSError as exc:
        log.warning("conference %s: cannot write status (%s)", key, exc)


# ── build ─────────────────────────────────────────────────────────────────────

def _pid(title: str) -> str:
    return hashlib.sha1(re.sub(r"[^a-z0-9]+", "", title.lower()).encode()).hexdigest()[:10]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", institutions.fold(name)).strip("-") or "x"


def needs_title_embedding(papers: list[dict]) -> bool:
    """Whether ``emb.npy`` holds more than titles. Cross-conference search ranks every
    conference by title-only vectors: title + abstract vectors sit 0.03-0.07 higher in
    cosine to any query than title-only ones, so a conference with abstracts would
    otherwise win every comparison against one without."""
    return any(p.get("a") or p.get("kw") for p in papers)


def _embed_text(p: dict) -> str:
    parts = [p["t"]]
    if p.get("a"):
        parts.append(p["a"])
    elif p.get("kw"):
        parts.append("; ".join(p["kw"]))
    return ". ".join(parts)


def build(key: str) -> None:
    edition = catalog.get_edition(key)
    if edition is None:
        raise ValueError(f"unknown conference {key}")
    t0 = time.time()
    _set_status(key, "fetching", progress=0.0, message=f"Downloading {edition.name}")
    try:
        raw, info = sources.fetch(edition)
    except Exception as exc:  # noqa: BLE001
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code == 404:
            _set_status(key, "unavailable", message=f"{edition.name} is not published at the source yet.")
        else:
            _set_status(key, "error", message=f"Download failed: {exc}")
        log.warning("conference %s: fetch failed: %s", key, exc)
        return
    if not raw:
        _set_status(key, "unavailable", message=f"The source lists no accepted papers for {edition.name}.")
        return

    _set_status(key, "normalising", progress=0.0, message=f"Normalising {len(raw)} papers")
    inst_index: dict[str, int] = {}
    inst_rows: list[dict] = []
    papers: list[dict] = []
    seen: set[str] = set()

    def inst_id(name: str, sec: str) -> int:
        k = institutions.merge_key(name)
        if k not in inst_index:
            inst_index[k] = len(inst_rows)
            inst_rows.append({"n": name, "s": sec, "variants": Counter()})
        row = inst_rows[inst_index[k]]
        row["variants"][name] += 1
        return inst_index[k]

    for r in raw:
        pid = _pid(r["title"])
        if pid in seen:
            continue
        seen.add(pid)
        author_insts: list[list[int]] = []
        for a in r["authors"]:
            ids: list[int] = []
            for rawinst in a["insts"]:
                for name, sec in institutions.split_and_normalise(rawinst):
                    i = inst_id(name, sec)
                    if i not in ids:
                        ids.append(i)
            author_insts.append(ids)
        uniq = sorted({i for ids in author_insts for i in ids})
        papers.append({
            "id": pid, "t": r["title"], "a": r["abstract"],
            "au": [a["name"] for a in r["authors"]], "ai": author_insts, "i": uniq,
            "ar": -1, "d": r["decision"], "tr": r["track"], "s": r["session"],
            "u": r["url"], "f": r["forum"], "nt": r["native_topic"], "kw": r.get("keywords") or [],
        })

    # Display name: the most frequent spelling of each merged institution.
    for row in inst_rows:
        variants = row.pop("variants")
        if row["n"] not in institutions.CANONICAL and variants:
            row["n"] = variants.most_common(1)[0][0]

    dataset = {
        "key": key, "name": edition.name, "series": edition.series.name, "slug": edition.series.slug,
        "field": edition.series.field, "year": edition.year, "source": edition.source,
        "source_url": edition.source_url, "fetched_at": _now(), "partial": bool(info.get("partial")),
        "expected": info.get("expected", len(papers)), "areas_ready": False,
        "papers": papers, "insts": inst_rows,
    }
    _finalise(dataset)
    _dir(key).mkdir(parents=True, exist_ok=True)
    (_dir(key) / "emb.npy").unlink(missing_ok=True)
    (_dir(key) / "emb_title.npy").unlink(missing_ok=True)
    _write_json(_dir(key) / "dataset.json", dataset)
    _cache_drop(key)

    # Embeddings and areas.
    from services.conferences import embedder

    def prog(done, total):
        _set_status(key, "embedding", progress=round(done / max(1, total), 3),
                    message=f"Embedding {done} of {total} papers", papers=len(papers))

    prog(0, len(papers))
    try:
        emb = embedder.conference_embed([_embed_text(p) for p in papers], progress=prog)
        protos = area_mod.prototypes(lambda xs: embedder.conference_embed(xs, max_length=64))
        temb = None
        if needs_title_embedding(papers):
            _set_status(key, "embedding", progress=1.0, message=f"Embedding {len(papers)} titles",
                        papers=len(papers))
            temb = embedder.conference_embed([p["t"] for p in papers], max_length=64)
    except Exception as exc:  # noqa: BLE001
        log.exception("conference %s: embedding failed", key)
        _set_status(key, "partial", message=f"Institutions ready; topic search unavailable ({exc})",
                    papers=len(papers))
        return
    labels = area_mod.assign(emb, protos)
    for p, lab in zip(papers, labels.tolist()):
        p["ar"] = int(lab)
    dataset["areas_ready"] = True
    _finalise(dataset)
    np.save(_dir(key) / "emb.npy", emb.astype(np.float16))
    if temb is not None:
        np.save(_dir(key) / "emb_title.npy", temb.astype(np.float16))
    else:
        (_dir(key) / "emb_title.npy").unlink(missing_ok=True)
    _write_json(_dir(key) / "dataset.json", dataset)
    _cache_drop(key)
    _set_status(key, "ready", progress=1.0, papers=len(papers), institutions=len(inst_rows),
                partial=dataset["partial"], expected=dataset["expected"],
                seconds=round(time.time() - t0, 1), message="")
    log.info("conference %s ready: %d papers, %d institutions, %.0fs", key, len(papers), len(inst_rows),
             time.time() - t0)


def _finalise(ds: dict) -> None:
    """Per-institution counts (full and fractional), area mix and rank."""
    n_areas = len(area_mod.AREAS)
    for row in ds["insts"]:
        row.update({"p": 0, "f": 0.0, "a": [0] * n_areas})
    for p in ds["papers"]:
        for i in p["i"]:
            row = ds["insts"][i]
            row["p"] += 1
            if p["ar"] >= 0:
                row["a"][p["ar"]] += 1
        # Fractional: each author is 1/n of the paper, split over their institutions.
        n = len(p["ai"]) or 1
        for ids in p["ai"]:
            for i in ids:
                ds["insts"][i]["f"] += 1.0 / n / len(ids)
    order = sorted(range(len(ds["insts"])), key=lambda i: (-ds["insts"][i]["p"], -ds["insts"][i]["f"]))
    rank, prev = 0, None
    for pos, i in enumerate(order, 1):
        row = ds["insts"][i]
        if row["p"] != prev:
            rank, prev = pos, row["p"]
        row["r"] = rank
        row["f"] = round(row["f"], 2)
        row["slug"] = _slug(row["n"])
    # Two names may fold to the same slug; keep slugs unique.
    seen: Counter = Counter()
    for i in order:
        row = ds["insts"][i]
        seen[row["slug"]] += 1
        if seen[row["slug"]] > 1:
            row["slug"] = f"{row['slug']}-{seen[row['slug']]}"


def build_title_embeddings(key: str) -> bool:
    """Add ``emb_title.npy`` to a dataset built before it existed. No status change: the
    conference stays usable throughout. Returns whether a file was written."""
    path = _dir(key) / "emb_title.npy"
    if path.exists() or not (_dir(key) / "emb.npy").exists():
        return False
    ds = load(key)
    if ds is None or not needs_title_embedding(ds.papers):
        return False
    from services.conferences import embedder

    t0 = time.time()
    temb = embedder.conference_embed([p["t"] for p in ds.papers], max_length=64)
    tmp = path.with_name("emb_title.tmp.npy")
    np.save(tmp, temb.astype(np.float16))
    tmp.replace(path)
    _cache_drop(key)
    log.info("conference %s: title embeddings for %d papers, %.0fs", key, len(ds.papers), time.time() - t0)
    return True


# ── worker ────────────────────────────────────────────────────────────────────

_TITLES = "titles:"

_queue: "queue.Queue[str]" = queue.Queue()
_queued: set[str] = set()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _work() -> None:
    while True:
        key = _queue.get()
        try:
            if key.startswith(_TITLES):
                build_title_embeddings(key[len(_TITLES):])
            else:
                build(key)
        except Exception as exc:  # noqa: BLE001
            if key.startswith(_TITLES):
                log.exception("conference %s: title embeddings failed", key[len(_TITLES):])
            else:
                log.exception("conference %s: build failed", key)
                _set_status(key, "error", message=str(exc))
        finally:
            with _worker_lock:
                _queued.discard(key)
            _queue.task_done()


def request_build(key: str) -> dict:
    """Queue a (re)build unless one is already queued or running."""
    if catalog.get_edition(key) is None:
        raise KeyError(key)
    global _worker
    with _worker_lock:
        if key not in _queued:
            _queued.add(key)
            _set_status(key, "queued", progress=0.0, message="Waiting for the builder",
                        position=len(_queued))
            _queue.put(key)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="conference-builder", daemon=True)
            _worker.start()
    return status(key)


def request_title_embeddings(key: str) -> None:
    """Queue ``build_title_embeddings`` behind any running build."""
    global _worker
    item = _TITLES + key
    with _worker_lock:
        if item in _queued:
            return
        _queued.add(item)
        _queue.put(item)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="conference-builder", daemon=True)
            _worker.start()


def loaded_keys() -> list[str]:
    """Keys of every conference-year with a dataset on disk, in catalog order (series,
    newest year first). A conference being refreshed keeps its previous files until the
    new ones replace them, so it stays searchable."""
    return [e.key for e in catalog.editions() if (_dir(e.key) / "dataset.json").exists()]


_DEFAULTS = "neurips2026,icml2026,iclr2026,cvpr2026,iccv2025,eccv2026,neurips2025,acl2025"


def default_keys() -> list[str]:
    raw = os.environ.get("CONFERENCES_DEFAULT", "").strip() or _DEFAULTS
    return [k.strip().lower() for k in raw.split(",") if catalog.get_edition(k.strip().lower())]


def start_auto_build() -> None:
    """At startup: build the default conferences that are missing, and rebuild this
    year's ones when they are older than ``CONFERENCES_REFRESH_DAYS`` (the sites add
    abstracts, sessions and late papers until the conference)."""
    if os.environ.get("CONFERENCES_AUTO", "true").strip().lower() in ("0", "false", "no", "off"):
        log.info("Conference auto-build off (CONFERENCES_AUTO=false)")
        return
    refresh_days = float(os.environ.get("CONFERENCES_REFRESH_DAYS", "14"))
    year = datetime.now(timezone.utc).year
    todo = []
    for key in default_keys():
        st = status(key)
        if st.get("state") in ("none", "error", "partial"):
            todo.append(key)
            continue
        ed = catalog.get_edition(key)
        ds_path = _dir(key) / "dataset.json"
        if ed and ed.year >= year and ds_path.exists() and refresh_days > 0:
            age_days = (time.time() - ds_path.stat().st_mtime) / 86400
            if age_days > refresh_days:
                todo.append(key)
        elif st.get("state") == "unavailable" and ed and ed.year >= year:
            todo.append(key)  # may have been published since
    if todo:
        log.info("Conference auto-build queued: %s", ", ".join(todo))
    for key in todo:
        request_build(key)
    # Datasets built before title-only vectors existed get them (cross-conference search).
    for key in loaded_keys():
        if key not in todo and (_dir(key) / "emb.npy").exists() and not (_dir(key) / "emb_title.npy").exists():
            request_title_embeddings(key)
    # Load every dataset, the search index and the model once, so the first search is fast.
    from services.conferences import search as search_mod

    threading.Thread(target=search_mod.warm, name="conference-search-warm", daemon=True).start()


# ── loaded datasets ───────────────────────────────────────────────────────────

class Dataset:
    def __init__(self, raw: dict, emb: np.ndarray | None, temb: np.ndarray | None = None):
        self.raw = raw
        self.key = raw["key"]
        self.papers: list[dict] = raw["papers"]
        self.insts: list[dict] = raw["insts"]
        self.emb = emb
        # Title-only vectors for cross-conference comparison: emb itself when it holds
        # nothing but titles, else emb_title.npy (None until that is built).
        if temb is None and emb is not None and not needs_title_embedding(self.papers):
            temb = emb
        self.temb = temb
        self.by_slug = {r["slug"]: i for i, r in enumerate(self.insts)}
        self.by_pid = {p["id"]: j for j, p in enumerate(self.papers)}
        self.folded = [institutions.fold(r["n"]) for r in self.insts]
        self._idf: dict[str, float] | None = None
        self.area_totals = [0] * len(area_mod.AREAS)
        for p in self.papers:
            if p["ar"] >= 0:
                self.area_totals[p["ar"]] += 1

    @property
    def areas_ready(self) -> bool:
        return bool(self.raw.get("areas_ready")) and self.emb is not None


_cache: "OrderedDict[str, tuple[tuple[float, float], Dataset]]" = OrderedDict()
_cache_lock = threading.Lock()
# Cross-conference search holds every loaded conference at once (20-40 MB each in memory,
# embeddings included), so the cache must not be smaller than the loaded set.
_CACHE_MAX = int(os.environ.get("CONFERENCE_CACHE_MAX", "32"))


def _cache_drop(key: str) -> None:
    with _cache_lock:
        _cache.pop(key, None)


def load(key: str) -> Dataset | None:
    path = _dir(key) / "dataset.json"
    if not path.exists():
        return None
    tpath = _dir(key) / "emb_title.npy"
    mtime = (path.stat().st_mtime, tpath.stat().st_mtime if tpath.exists() else 0.0)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            _cache.move_to_end(key)
            return hit[1]
    raw = json.loads(path.read_text(encoding="utf-8"))
    emb_path = _dir(key) / "emb.npy"
    emb = None
    if raw.get("areas_ready") and emb_path.exists():
        emb = np.load(emb_path).astype(np.float32)
        # Vectors of another embedding model (the conference model changed) cannot meet today's queries.
        if len(emb) != len(raw["papers"]) or emb.ndim != 2 or emb.shape[1] != model_config.conference_dim():
            emb = None
    temb = None
    if emb is not None and tpath.exists():
        try:
            temb = np.load(tpath).astype(np.float32)
        except (OSError, ValueError):
            temb = None
        if temb is not None and (len(temb) != len(raw["papers"]) or temb.shape[1:] != (model_config.conference_dim(),)):
            temb = None
    ds = Dataset(raw, emb, temb)
    with _cache_lock:
        _cache[key] = (mtime, ds)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return ds


# ── queries ───────────────────────────────────────────────────────────────────

def catalog_rows() -> list[dict]:
    rows = []
    for e in catalog.editions():
        st = status(e.key)
        rows.append({
            "key": e.key, "name": e.name, "series": e.series.name, "slug": e.series.slug,
            "field": e.series.field, "year": e.year, "source": e.source,
            "state": st.get("state", "none"), "progress": st.get("progress"),
            "message": st.get("message", ""), "papers": st.get("papers"),
            "institutions": st.get("institutions"), "partial": st.get("partial", False),
            "expected": st.get("expected"),
        })
    return rows


def _inst_brief(ds: Dataset, i: int) -> dict:
    r = ds.insts[i]
    return {"name": r["n"], "slug": r["slug"], "sector": r["s"], "papers": r["p"], "rank": r["r"]}


def _area_list(counts: list[int]) -> list[dict]:
    return [{**a, "index": k, "count": counts[k]} for k, a in enumerate(area_mod.public())]


def overview(ds: Dataset) -> dict:
    n = len(ds.papers)
    with_inst = sum(1 for p in ds.papers if p["i"])
    with_ind = sum(1 for p in ds.papers if any(ds.insts[i]["s"] == "I" for i in p["i"]))
    decisions = Counter(p["d"] for p in ds.papers)
    order = sorted(range(len(ds.insts)), key=lambda i: ds.insts[i]["r"])
    aca = [i for i in order if ds.insts[i]["s"] == "A"][:12]
    ind = [i for i in order if ds.insts[i]["s"] == "I"][:12]
    raw = ds.raw
    return {
        "key": ds.key, "name": raw["name"], "series": raw["series"], "year": raw["year"],
        "field": raw.get("field"), "source": raw["source"], "source_url": raw["source_url"],
        "fetched_at": raw["fetched_at"], "partial": raw.get("partial", False), "expected": raw.get("expected"),
        "papers": n, "institutions": len(ds.insts), "with_institution": with_inst,
        "with_industry": with_ind, "areas_ready": ds.areas_ready,
        "decisions": [{"label": k, "count": v} for k, v in decisions.most_common()],
        "areas": _area_list(ds.area_totals),
        "top_academia": [_inst_brief(ds, i) for i in aca],
        "top_industry": [_inst_brief(ds, i) for i in ind],
    }


def _name_score(folded: str, q: str, words: list[str]) -> int:
    if folded == q:
        return 100
    if folded.startswith(q):
        return 80
    if (" " + folded).find(" " + q) >= 0:
        return 60
    if q in folded:
        return 40
    if len(words) > 1 and all((" " + folded).find(" " + w) >= 0 for w in words):
        return 30
    return 0


def search_institutions(ds: Dataset, q: str = "", sector: str = "", area: int = -1,
                        offset: int = 0, limit: int = 50) -> dict:
    fq = institutions.fold(q)
    words = fq.split()
    items = []
    for i, r in enumerate(ds.insts):
        if sector and r["s"] != sector:
            continue
        count = r["a"][area] if area >= 0 else r["p"]
        if count <= 0:
            continue
        score = _name_score(ds.folded[i], fq, words) if fq else 0
        if fq and not score:
            continue
        items.append((i, count, score))
    if fq:
        items.sort(key=lambda t: (-t[2], -t[1]))
    else:
        items.sort(key=lambda t: (-t[1], -ds.insts[t[0]]["f"]))
    total = len(items)
    n = len(ds.papers)
    rows = []
    for pos, (i, count, _) in enumerate(items[offset:offset + limit], offset + 1):
        r = ds.insts[i]
        rows.append({
            "name": r["n"], "slug": r["slug"], "sector": r["s"], "rank": r["r"],
            "area_rank": pos if (area >= 0 and not fq) else None,
            "papers": r["p"], "fractional": r["f"], "count": count,
            "share": round(r["p"] / max(1, n), 4),
            "of_own": round(count / max(1, r["p"]), 4) if area >= 0 else None,
            "areas": r["a"],
        })
    return {"total": total, "offset": offset, "rows": rows}


def _paper_row(ds: Dataset, j: int, sim: float | None = None, library: dict | None = None,
               focus: int | None = None) -> dict:
    p = ds.papers[j]
    insts = p["i"]
    if focus is not None and focus in insts:
        insts = [focus] + [i for i in insts if i != focus]
    row = {
        "id": p["id"], "title": p["t"], "area": p["ar"], "decision": p["d"], "track": p["tr"],
        "session": p["s"], "url": p["u"], "forum": p["f"],
        "institutions": [{"name": ds.insts[i]["n"], "slug": ds.insts[i]["slug"], "sector": ds.insts[i]["s"]}
                         for i in insts[:8]],
        "more_institutions": max(0, len(insts) - 8),
        "authors": len(p["au"]),
    }
    if sim is not None:
        row["match"] = round(float(sim), 4)
    if library is not None:
        row["library_id"] = library.get(_title_key(p["t"]))
    return row


def _title_key(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def institution_detail(ds: Dataset, slug: str, library: dict | None = None) -> dict | None:
    i = ds.by_slug.get(slug)
    if i is None:
        return None
    r = ds.insts[i]
    n = len(ds.papers)
    js = [j for j, p in enumerate(ds.papers) if i in p["i"]]
    # Collaborators: other institutions on the same papers.
    co = Counter(k for j in js for k in ds.papers[j]["i"] if k != i)
    sector_order = sorted((k for k, x in enumerate(ds.insts) if x["s"] == r["s"]), key=lambda k: ds.insts[k]["r"])
    sector_rank = sector_order.index(i) + 1 if i in sector_order else None
    authors = Counter()
    for j in js:
        p = ds.papers[j]
        for name, ids in zip(p["au"], p["ai"]):
            if i in ids:
                authors[name] += 1
    js.sort(key=lambda j: ({"Oral": 0, "Spotlight": 1, "Highlight": 1}.get(ds.papers[j]["d"], 2), ds.papers[j]["t"]))
    return {
        "name": r["n"], "slug": r["slug"], "sector": r["s"], "rank": r["r"], "sector_rank": sector_rank,
        "papers": r["p"], "fractional": r["f"], "share": round(r["p"] / max(1, n), 4),
        "areas": _area_list(r["a"]), "conference_areas": _area_list(ds.area_totals),
        "collaborators": [{**_inst_brief(ds, k), "shared": c} for k, c in co.most_common(12)],
        "authors": [{"name": a, "papers": c} for a, c in authors.most_common(15)],
        "paper_list": [_paper_row(ds, j, library=library, focus=i) for j in js],
    }


def _lexical(ds: Dataset, text: str) -> np.ndarray:
    if ds._idf is None:
        df: Counter = Counter()
        for p in ds.papers:
            df.update(set(institutions.fold(p["t"] + " " + (p["a"] or "")[:600]).split()))
        ds._idf = {w: math.log(len(ds.papers) / c) for w, c in df.items()}
    qw = {w for w in institutions.fold(text).split() if len(w) > 2}
    out = np.zeros(len(ds.papers), dtype=np.float32)
    for j, p in enumerate(ds.papers):
        tw = set(institutions.fold(p["t"]).split())
        aw = set(institutions.fold((p["a"] or "")[:600]).split())
        out[j] = sum(ds._idf.get(w, 0) * (2.0 if w in tw else 1.0 if w in aw else 0.0) for w in qw)
    top = out.max() if len(out) else 0
    return out / top if top > 0 else out


def topic(ds: Dataset, text: str, k: int = 100, library: dict | None = None, sector_top: int = 10,
          paper_top: int = 25) -> dict:
    text = text.strip()
    k = max(10, min(int(k), 500))
    mode = "semantic"
    if ds.areas_ready:
        from services.conferences import embedder

        try:
            q = embedder.conference_embed_query(text)
            sims = ds.emb @ q
        except Exception as exc:  # noqa: BLE001
            log.warning("conference %s: query embedding failed (%s); keyword fallback", ds.key, exc)
            sims, mode = _lexical(ds, text), "keyword"
    else:
        sims, mode = _lexical(ds, text), "keyword"
    order = np.argsort(-sims)[:k]
    if mode == "keyword":
        order = [j for j in order if sims[j] > 0]
    order = [int(j) for j in order]
    cnt: Counter = Counter()
    wsum: Counter = Counter()
    area_counts = [0] * len(area_mod.AREAS)
    with_ind = 0
    for j in order:
        p = ds.papers[j]
        if p["ar"] >= 0:
            area_counts[p["ar"]] += 1
        if any(ds.insts[i]["s"] == "I" for i in p["i"]):
            with_ind += 1
        for i in p["i"]:
            cnt[i] += 1
            wsum[i] += float(sims[j])
    ranked = sorted(cnt, key=lambda i: (-cnt[i], -wsum[i]))

    def side(sec: str) -> list[dict]:
        return [{**_inst_brief(ds, i), "count": cnt[i],
                 "of_own": round(cnt[i] / max(1, ds.insts[i]["p"]), 3)}
                for i in ranked if ds.insts[i]["s"] == sec][:sector_top]

    return {
        "query": text, "mode": mode, "k": len(order), "total": len(ds.papers),
        "with_industry": with_ind, "areas": _area_list(area_counts),
        "academia": side("A"), "industry": side("I"),
        "papers": [_paper_row(ds, j, float(sims[j]) if mode == "semantic" else None, library)
                   for j in order[:paper_top]],
    }


def paper_detail(ds: Dataset, pid: str, library: dict | None = None) -> dict | None:
    j = ds.by_pid.get(pid)
    if j is None:
        return None
    p = ds.papers[j]
    row = _paper_row(ds, j, library=library)
    row.update({
        "abstract": p["a"], "native_topic": p["nt"], "keywords": p.get("kw") or [],
        "author_list": [{"name": name, "institutions": [ds.insts[i]["n"] for i in ids]}
                        for name, ids in zip(p["au"], p["ai"])],
        "conference": ds.raw["name"], "year": ds.raw["year"],
    })
    if ds.areas_ready:
        sims = ds.emb @ ds.emb[j]
        sims[j] = -1
        row["similar"] = [_paper_row(ds, int(s), float(sims[s])) for s in np.argsort(-sims)[:8]]
    return row
