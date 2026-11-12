"""Heartbeats of the background loops, read by the system health page (.specs/016_health.md).

A loop calls ``beat("name", ok=..., error=..., interval_s=...)`` after every round;
``snapshot()`` returns the last beat of each.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()
_beats: dict[str, dict] = {}


def beat(name: str, ok: bool = True, error: str | None = None, interval_s: float | None = None) -> None:
    """Record that loop *name* just finished a round."""
    with _lock:
        previous = _beats.get(name, {})
        _beats[name] = {
            "last_run": datetime.now(timezone.utc).isoformat(),
            "last_run_ts": time.time(),
            "last_ok": bool(ok),
            "last_error": (str(error)[:300] if error else None),
            "interval_s": interval_s if interval_s is not None else previous.get("interval_s"),
            "runs": previous.get("runs", 0) + 1,
        }


def snapshot() -> dict[str, dict]:
    """A copy of the last beat per loop name."""
    with _lock:
        return {name: dict(b) for name, b in _beats.items()}


def reset() -> None:
    """Forget every beat (tests)."""
    with _lock:
        _beats.clear()
