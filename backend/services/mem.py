"""Return freed heap arenas to the OS after memory-heavy work.

Figure extraction churns hundreds of MB per PDF (zip body → base64 data URIs →
PIL buffers → re-encoded PNGs). Python frees all of it, but glibc keeps the
arenas mapped, so RSS stays pinned at the high-water mark of the largest ingest
instead of dropping back. Calling malloc_trim(0) once the buffers are gone
hands the arenas back.

Everything here is best-effort: on a non-glibc libc it degrades to a no-op.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging

log = logging.getLogger(__name__)

_libc: ctypes.CDLL | None = None
_libc_loaded = False


def _get_libc() -> ctypes.CDLL | None:
    global _libc, _libc_loaded
    if _libc_loaded:
        return _libc
    _libc_loaded = True
    try:
        name = ctypes.util.find_library("c") or "libc.so.6"
        candidate = ctypes.CDLL(name)
        candidate.malloc_trim  # raises AttributeError on non-glibc (e.g. musl)
        _libc = candidate
    except Exception as exc:
        log.debug("malloc_trim unavailable, memory trimming disabled: %s", exc)
        _libc = None
    return _libc


def current_rss_mb() -> float | None:
    """Resident set size of this process in MB, or None if unavailable."""
    try:
        with open("/proc/self/statm", encoding="ascii") as fh:
            pages = int(fh.read().split()[1])
        return pages * 4096 / (1024 * 1024)
    except Exception:
        return None


def trim_memory(reason: str = "") -> None:
    """Ask glibc to return free heap arenas to the OS. Safe to call anywhere."""
    libc = _get_libc()
    if libc is None:
        return
    before = current_rss_mb()
    try:
        libc.malloc_trim(0)
    except Exception as exc:
        log.debug("malloc_trim failed: %s", exc)
        return
    after = current_rss_mb()
    if before is not None and after is not None:
        log.info(
            "malloc_trim%s | rss %.0f MB → %.0f MB (released %.0f MB)",
            f" after {reason}" if reason else "",
            before, after, before - after,
        )
