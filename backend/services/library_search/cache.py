"""Small in-process cache of ranked candidate lists (before sorting, paging and hydration).

Paging, changing the sort and going back to a search re-use the ranked list instead of
running every retrieval query again. Keyed by (request user, query, filters, mode); entries
live ``TTL`` seconds, at most ``MAX_ENTRIES`` of them (least recently used goes first).

Writes invalidate through a generation counter: ``bump()`` is called after every non-GET
HTTP request (a middleware in main.py), and an entry stored under an older generation is a
miss. ``generation()`` is read *before* the search runs and passed to ``put``, so a search
that raced with a write is stored under the old generation and never served afterwards.
Background jobs (uploads still processing, the embedding sync) and other processes (the MCP
server) do not bump; the TTL bounds how stale an answer can be.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict

TTL = 60.0
MAX_ENTRIES = 64


def enabled() -> bool:
    """``LIBRARY_SEARCH_CACHE=0`` / ``false`` switches the cache off (tests do)."""
    return os.environ.get("LIBRARY_SEARCH_CACHE", "1").strip().lower() not in ("0", "false", "no", "off")

_lock = threading.Lock()
_entries: "OrderedDict[tuple, tuple[float, int, object]]" = OrderedDict()
_generation = 0


def _now() -> float:  # replaced in tests
    return time.monotonic()


def generation() -> int:
    return _generation


def bump() -> None:
    """Invalidate everything stored so far (a write happened)."""
    global _generation
    with _lock:
        _generation += 1
        _entries.clear()


def get(key: tuple) -> object | None:
    with _lock:
        hit = _entries.get(key)
        if hit is None:
            return None
        stamp, gen, value = hit
        if gen != _generation or _now() - stamp > TTL:
            del _entries[key]
            return None
        _entries.move_to_end(key)
        return value


def put(key: tuple, value: object, gen: int) -> None:
    """Store ``value`` unless a write happened since ``gen`` was read."""
    with _lock:
        if gen != _generation:
            return
        _entries[key] = (_now(), gen, value)
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def clear() -> None:
    with _lock:
        _entries.clear()


def size() -> int:
    with _lock:
        return len(_entries)
