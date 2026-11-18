"""Instance settings (environment) and the per-user feed configuration."""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SOURCES = ("arxiv", "biorxiv", "medrxiv")
CATEGORY_RE = re.compile(r"^[a-z\-]+(\.[A-Za-z\-]+)?$")
MAX_CATEGORIES = 30
DIGEST_DAYS_MIN, DIGEST_DAYS_MAX, DIGEST_DAYS_DEFAULT = 1, 14, 3


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _number(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def enabled() -> bool:
    """Master switch. Off unless ``PAPER_FEED`` is true; every other function here may be
    called only when it is on."""
    return _flag("PAPER_FEED")


def interval_seconds() -> float:
    return _number("PAPER_FEED_INTERVAL", 21600, 60)


def retention_days() -> int:
    return int(_number("PAPER_FEED_RETENTION_DAYS", 30, 1))


def max_per_refresh() -> int:
    return int(_number("PAPER_FEED_MAX_PER_REFRESH", 2000, 100))


def contact() -> str:
    return os.environ.get("PAPER_FEED_CONTACT", "").strip()


def user_agent() -> str:
    c = contact()
    return f"PaperManager-feed ({c})" if c else "PaperManager-feed"


def feed_dir() -> Path:
    """The sidecar directory: ``PAPER_FEED_DIR`` or ``/data/feed``, falling back to a
    temporary directory when neither is writable. Created on first call (only reached when
    the feed is enabled)."""
    configured = os.environ.get("PAPER_FEED_DIR", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates += [Path("/data/feed"), Path(tempfile.gettempdir()) / "papermanager-feed"]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.access(path, os.W_OK):
                return path
        except OSError:
            continue
    raise RuntimeError("No writable directory for the paper feed")


@dataclass
class FeedConfig:
    """What one user wants in the digest."""

    sources: list[str] = field(default_factory=lambda: ["arxiv"])
    arxiv_categories: list[str] = field(default_factory=list)
    digest_days: int = DIGEST_DAYS_DEFAULT
    min_score: float = 0.0

    def to_dict(self) -> dict:
        return {"sources": list(self.sources), "arxiv_categories": list(self.arxiv_categories),
                "digest_days": self.digest_days, "min_score": self.min_score}

    @classmethod
    def from_dict(cls, d: dict | None) -> "FeedConfig":
        """Lenient read of a stored config: unknown or invalid values fall back to defaults."""
        d = d or {}
        base = cls()
        sources = [s for s in d.get("sources", base.sources) if s in SOURCES]
        cats = [c for c in d.get("arxiv_categories", []) if isinstance(c, str) and CATEGORY_RE.match(c)]
        days = d.get("digest_days", base.digest_days)
        score = d.get("min_score", base.min_score)
        return cls(
            sources=list(dict.fromkeys(sources)),
            arxiv_categories=list(dict.fromkeys(cats))[:MAX_CATEGORIES],
            digest_days=days if isinstance(days, int) and DIGEST_DAYS_MIN <= days <= DIGEST_DAYS_MAX
            else base.digest_days,
            min_score=float(score) if isinstance(score, (int, float)) and 0 <= score <= 1 else 0.0,
        )
