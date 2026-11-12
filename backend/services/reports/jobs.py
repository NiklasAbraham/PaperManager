"""Background execution of report jobs: a bounded number run at once, the rest wait as ``queued``."""
from __future__ import annotations

import contextvars
import logging
import threading

from config import settings
from db.queries import reports as rq

log = logging.getLogger(__name__)

_lock = threading.Lock()
_events: dict[str, threading.Event] = {}
_slots: threading.Semaphore | None = None


def _semaphore() -> threading.Semaphore:
    global _slots
    with _lock:
        if _slots is None:
            _slots = threading.Semaphore(max(1, int(settings.reports_max_parallel)))
        return _slots


def _worker(report_id: str, event: threading.Event) -> None:
    from services.reports import pipeline

    slots = _semaphore()
    try:
        with slots:
            if event.is_set():  # cancelled while waiting for a slot
                from db.connection import get_driver

                rq.cancel_report(get_driver(), report_id)
                return
            pipeline.run_report(report_id, cancel_event=event)
    except Exception:  # noqa: BLE001 — run_report does not raise, but a thread must never die loudly
        log.exception("report job %s crashed", report_id)
    finally:
        with _lock:
            _events.pop(report_id, None)


def start(report_id: str) -> None:
    """Start the job for a queued report in a daemon thread that inherits the caller's context."""
    event = threading.Event()
    with _lock:
        _events[report_id] = event
    ctx = contextvars.copy_context()  # carries the request user into the thread
    threading.Thread(
        target=ctx.run, args=(_worker, report_id, event), name=f"report-{report_id[:8]}", daemon=True
    ).start()


def cancel(report_id: str) -> bool:
    """Ask a running or waiting job to stop. True when this process had such a job."""
    with _lock:
        event = _events.get(report_id)
    if event is None:
        return False
    event.set()
    return True


def recover_interrupted(driver) -> int:
    """At startup: reports left queued or running by a restart become failed. Returns how many."""
    try:
        count = rq.fail_interrupted(driver)
    except Exception:  # noqa: BLE001 — never block the startup
        log.exception("could not recover interrupted reports")
        return 0
    if count:
        log.warning("%d report(s) were interrupted by a restart and marked failed", count)
    return count
