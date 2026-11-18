"""The refresh: fetch new papers, embed them, store them. Runs in a daemon thread.

``start_background`` is a no-op unless the feed is enabled. A refresh fetches only what the
users asked for: the union of the arXiv categories of every user who uses arXiv, and
bioRxiv / medRxiv when any user turned them on. With nothing chosen, nothing is fetched.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from services.feed import config, sources
from services.feed.store import Candidate, FeedStore, get_store

log = logging.getLogger(__name__)

_refresh_lock = threading.Lock()
_thread: threading.Thread | None = None
FIRST_DELAY = 20.0       # seconds after startup before the first refresh
OVERLAP = timedelta(days=1)
_EMBED_CHUNK = 64


def is_running() -> bool:
    if _refresh_lock.acquire(blocking=False):
        _refresh_lock.release()
        return False
    return True


def plan(configs: dict[str, config.FeedConfig]) -> dict:
    """What to fetch for these users: arXiv categories, bioRxiv / medRxiv switches, and the
    longest digest window any of them asked for (how far back a first fetch reaches)."""
    cats: set[str] = set()
    out = {"arxiv": [], "biorxiv": False, "medrxiv": False, "days": config.DIGEST_DAYS_DEFAULT}
    for cfg in configs.values():
        out["days"] = max(out["days"], cfg.digest_days)
        if "arxiv" in cfg.sources:
            cats.update(cfg.arxiv_categories)
        out["biorxiv"] = out["biorxiv"] or "biorxiv" in cfg.sources
        out["medrxiv"] = out["medrxiv"] or "medrxiv" in cfg.sources
    out["arxiv"] = sorted(cats)
    return out


def _since(store: FeedStore, key: str, now: datetime, days: int) -> datetime:
    last = store.get_since(key)
    if last:
        try:
            return datetime.fromisoformat(last) - OVERLAP
        except ValueError:
            pass
    return now - timedelta(days=days)


def _candidate_text(c: Candidate) -> str:
    from services.library_search.semantic import paper_text
    return paper_text(c.title, c.abstract, None)


def embed_pending(store: FeedStore, embed) -> int:
    """Embed stored candidates that have no vector yet. Returns how many were embedded."""
    todo = store.without_embedding()
    done = 0
    for i in range(0, len(todo), _EMBED_CHUNK):
        chunk = todo[i:i + _EMBED_CHUNK]
        vecs = embed([_candidate_text(c) for c in chunk])
        store.set_embeddings({c.id: vecs[j] for j, c in enumerate(chunk)})
        done += len(chunk)
    return done


def refresh(driver=None, embed=None, now: datetime | None = None) -> dict:
    """One full refresh. Returns counts, or ``{"skipped": True}`` when one is already running.
    Failures of a source or of the embedder are recorded in the run history, never raised."""
    if not _refresh_lock.acquire(blocking=False):
        return {"skipped": True}
    run_id: int | None = None
    store: FeedStore | None = None
    errors: list[str] = []
    fetched = new = embedded = 0
    names: list[str] = []
    try:
        store = get_store()
        run_id = store.start_run()
        now = now or datetime.now(timezone.utc)
        wanted = plan(store.all_configs())
        cap = config.max_per_refresh()

        def take(key: str, source: str, cands: list[Candidate], err: str | None) -> None:
            nonlocal fetched, new
            fetched += len(cands)
            new += store.upsert_candidates(cands)
            if err:
                errors.append(err)
            else:
                store.set_since(key, now.isoformat(timespec="seconds"))
            if source not in names:
                names.append(source)

        total_arxiv = 0
        for cat in wanted["arxiv"]:
            if total_arxiv >= cap:
                break
            try:
                cands, err = sources.fetch_arxiv([cat], _since(store, f"arxiv:{cat}", now, wanted["days"]),
                                                 cap - total_arxiv)
            except Exception as exc:  # noqa: BLE001 — a source never stops the refresh
                cands, err = [], f"arxiv {cat}: {exc}"[:300]
            total_arxiv += len(cands)
            take(f"arxiv:{cat}", "arxiv", cands, err)
        for server in ("biorxiv", "medrxiv"):
            if not wanted[server]:
                continue
            since = _since(store, server, now, wanted["days"])
            try:
                cands, err = sources.fetch_biorxiv(server, since.date(), now.date(), cap)
            except Exception as exc:  # noqa: BLE001
                cands, err = [], f"{server}: {exc}"[:300]
            take(server, server, cands, err)

        try:
            if embed is None:
                from services.conferences.embedder import embed as embed_fn
            else:
                embed_fn = embed
            embedded = embed_pending(store, embed_fn)
            if wanted["arxiv"] or wanted["biorxiv"] or wanted["medrxiv"]:
                try:
                    from services.feed.library import sync_missing_embeddings
                    if driver is None:
                        from db.connection import get_driver
                        driver = get_driver()
                    sync_missing_embeddings(driver, store, embed_fn)
                except Exception as exc:  # noqa: BLE001 — the library cache is a bonus
                    log.warning("Feed: library embeddings not synced: %s", exc)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"embedding: {exc}"[:300])
            log.warning("Feed: embedding failed: %s", exc)

        store.purge(config.retention_days())
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc)[:300])
        log.exception("Feed refresh failed")
    finally:
        try:
            if store is not None and run_id is not None:
                store.finish_run(run_id, source=",".join(names), fetched=fetched, new=new, embedded=embedded,
                                 error="; ".join(errors)[:500] or None)
        except Exception:  # noqa: BLE001
            log.exception("Feed: could not record the run")
        finally:
            _refresh_lock.release()
    log.info("Feed refreshed: %d fetched, %d new, %d embedded%s", fetched, new, embedded,
             f", errors: {errors}" if errors else "")
    return {"fetched": fetched, "new": new, "embedded": embedded, "error": "; ".join(errors) or None}


def start_refresh_async() -> bool:
    """Run a refresh in its own thread now. False when one is running."""
    if is_running():
        return False
    threading.Thread(target=refresh, name="feed-refresh-now", daemon=True).start()
    return True


def _loop(interval: float) -> None:
    import time
    time.sleep(FIRST_DELAY)
    while True:
        try:
            refresh()
        except Exception:  # noqa: BLE001 — retry next round
            log.exception("Feed refresh crashed")
        time.sleep(interval)


def start_background() -> None:
    """Start the refresh thread once. Does nothing when the feed is off."""
    global _thread
    if not config.enabled() or (_thread and _thread.is_alive()):
        return
    _thread = threading.Thread(target=_loop, args=(config.interval_seconds(),), name="paper-feed", daemon=True)
    _thread.start()
