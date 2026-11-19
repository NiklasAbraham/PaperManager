"""Similarity search tools: papers in the library (and the optional feed) that resemble a text or a
paper. Read-only, no language model: the text is embedded by the backend (PM_EMBED_URL) and the
vector stores are read through their follower mode (services/similar_search.py,
.specs/020_similar_search.md)."""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from config import settings
from services import similar_search as ss
from services.auth import get_request_user
from tools._compact import json_tool

log = logging.getLogger(__name__)

_AUTHORS = 3


def _user() -> str:
    return get_request_user() or settings.default_user_name


def _compact(hit: dict) -> dict:
    """One hit as a short row: no empty fields, three authors, the 300-character snippet."""
    authors = hit.get("authors") or []
    out = {
        "title": hit["title"], "url": hit["url"], "score": hit["score"], "source": hit["source"],
        "in_library": hit["in_library"], "id": hit["id"],
        "authors": ", ".join(authors[:_AUTHORS]) + (" et al." if len(authors) > _AUTHORS else ""),
        "year": hit.get("year"), "snippet": hit.get("snippet"),
    }
    if hit["source"] == "feed":
        out["library_paper_id"] = hit.get("library_paper_id")
        out["published"] = hit.get("published")
        out["my_label"] = hit.get("my_label")
    else:
        out["venue"] = hit.get("venue")
        out["reading_status"] = hit.get("reading_status")
    return {k: v for k, v in out.items() if v not in (None, "")}


def _tidy(res: dict) -> dict:
    if not res.get("available"):
        return {"available": False, "reason": res.get("reason"), "hits": []}
    out = {"available": True, "scope": res["scope"], "mode": res["mode"], "total": res["total"],
           "hits": [_compact(h) for h in res["hits"]]}
    if res.get("skipped"):
        out["skipped"] = res["skipped"]
    if res.get("warnings"):
        out["warnings"] = res["warnings"]
    return out


def _run(fn, *args, **kw) -> dict:
    try:
        return _tidy(fn(_user(), *args, follow=True, **kw))
    except ss.SimilarError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a clear message for the model, never a stack trace
        log.warning("Similarity search failed: %s", exc)
        return {"error": f"similarity search failed ({type(exc).__name__}); is the backend running?"}


def register(mcp: FastMCP) -> None:
    @json_tool(mcp)
    def find_similar_papers(text: str, scope: str = "both", k: int = 10, since: str = "", min_score: float = 0.0) -> dict:
        """Does a paper like this already exist? Nearest papers in the library and, if the feed is on,
        the feed, by embedding similarity. `text`: a title and an abstract-style paragraph (20 to
        20,000 characters), not keywords; a hypothetical abstract of a paper you wish existed works.
        `scope`: library, feed or both. `since`: YYYY-MM-DD, published on or after. Returns
        {available, hits [{title, url, score (cosine), source, in_library, library_paper_id, snippet}]};
        below about 0.6 is a weak match. available=false says why not."""
        return _run(ss.search_by_text, text, scope=scope.strip().lower(), k=max(1, min(int(k), ss.K_MAX)),
                    since=since.strip() or None, min_score=max(-1.0, min(float(min_score), 1.0)))

    @json_tool(mcp)
    def papers_like(paper_id: str, scope: str = "both", k: int = 10) -> dict:
        """More like this paper: the nearest papers to a library paper (by id) in the library and,
        if the feed is on, the feed; the paper itself is left out. Same result as
        find_similar_papers."""
        return _run(ss.search_by_paper, paper_id.strip(), scope=scope.strip().lower(), k=max(1, min(int(k), ss.K_MAX)))
