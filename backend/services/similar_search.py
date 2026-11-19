"""Find papers like this abstract: nearest neighbours of a text in the library and the feed.

    from services.similar_search import search_by_text, search_by_paper
    res = search_by_text("alice", abstract, k=10, scope="both")
    res["hits"]        # [{source, id, title, authors, year, url, score, snippet, in_library, ...}]

The text is embedded with the configured model (services.vectorstore.model_config) the way
stored papers are, as a *document*: a title and a paragraph, or a description of a paper that
does not exist yet. Only a short phrase (24 words or fewer) is embedded as a *query* with the
model's retrieval instruction (services.conferences.embedder.embed_search_text). The vector is
searched in the ``library`` namespace and, when the optional feed is on, in the ``feed`` one
(.specs/019_vector_store.md); the lists are merged by cosine score. Spec: .specs/020_similar_search.md.

* Library hits are over-fetched (5x, up to 1,000 vectors) and then filtered by the visibility
  clause of the requesting user, so ``k`` survive; reference stubs are dropped unless asked for.
* Feed hits carry only the requesting user's own label and a flag whether the paper is in the
  library that user may see.
* A store that is missing, empty, stale (another embedding model) or still building does not
  raise: the answer is ``{"available": False, "reason": ...}``.
* ``follow=True`` is for the MCP server, which only reads: it opens the stores read-only and
  gets its vectors from the backend (PM_EMBED_URL).
"""
from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from config import settings
from db.queries.visibility import paper_visibility_clause
from services.auth import reset_request_user, set_request_user
from services.library_lookup import REF_TAG, build_index
from services.vectorstore import StaleStoreError

log = logging.getLogger(__name__)

TEXT_MIN, TEXT_MAX = 20, 20000
K_MIN, K_MAX, K_DEFAULT = 1, 50, 10
SCOPES = ("library", "feed", "both")
OVERFETCH = 5            # vectors read per wanted hit before the visibility filter
FETCH_CAP = 1000         # most vectors read for one search of one namespace
SNIPPET_CHARS = 300
FULL_ABSTRACT_MAX = 3000


class SimilarError(Exception):
    """Base of the errors callers turn into a response (HTTP status in ``status``)."""
    status = 400


class InvalidRequest(SimilarError, ValueError):
    status = 422


class FeedDisabled(SimilarError):
    status = 404


class PaperNotFound(SimilarError):
    status = 404


# ── request values ────────────────────────────────────────────────────────────

def paper_url(paper_id: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/paper/{paper_id}"


def _clean_text(text: str | None) -> str:
    text = (text or "").strip()
    if len(text) < TEXT_MIN:
        raise InvalidRequest(f"text must have at least {TEXT_MIN} characters: a title and a paragraph work best")
    if len(text) > TEXT_MAX:
        raise InvalidRequest(f"text must have at most {TEXT_MAX} characters")
    return text


def _check(k: int, scope: str, min_score: float) -> None:
    if not isinstance(k, int) or isinstance(k, bool) or not K_MIN <= k <= K_MAX:
        raise InvalidRequest(f"k must be a whole number from {K_MIN} to {K_MAX}")
    if scope not in SCOPES:
        raise InvalidRequest(f"scope must be one of {', '.join(SCOPES)}")
    if not -1.0 <= float(min_score) <= 1.0:
        raise InvalidRequest("min_score must be between -1 and 1")


def parse_since(since: str | date | datetime | None) -> str | None:
    """``YYYY-MM-DD`` (a date, or the date part of an ISO timestamp), or None for no limit."""
    if since is None or since == "":
        return None
    if isinstance(since, datetime):
        return since.date().isoformat()
    if isinstance(since, date):
        return since.isoformat()
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2})(?:[T ].*)?$", str(since))
    if not m:
        raise InvalidRequest("since must be a date such as 2026-01-31")
    try:
        return date.fromisoformat(m.group(1)).isoformat()
    except ValueError:
        raise InvalidRequest("since must be a date such as 2026-01-31") from None


def snippet(text: str | None) -> str:
    """The first 300 characters of ``text`` on one line (an ellipsis marks a cut)."""
    t = " ".join((text or "").split())
    return t if len(t) <= SNIPPET_CHARS else t[:SNIPPET_CHARS].rstrip() + "…"


def _score(v: float) -> float:
    return round(float(v), 4)


@contextmanager
def _as_user(user: str):
    """Run with ``user`` as the request user, so the app's visibility clause speaks for them."""
    token = set_request_user(user)
    try:
        yield
    finally:
        reset_request_user(token)


def _driver(driver=None):
    if driver is not None:
        return driver
    from db.connection import get_driver
    return get_driver()


def feed_enabled() -> bool:
    from services.feed import config
    return config.enabled()


# ── namespaces ────────────────────────────────────────────────────────────────

def _library_store(follow: bool):
    """(store, reason): the library namespace if it can be searched, else why not."""
    from services import vectorstore
    from services.library_search import semantic

    if not semantic.enabled():
        return None, "semantic search is switched off on this instance (LIBRARY_SEMANTIC=false)"
    try:
        if follow:
            st = vectorstore.get_store("library", create=False, follow=True)
            if st is None:      # the backend has not migrated the old index files yet: do it once, here
                from services.vectorstore import migrate, model_config
                migrate.migrate_library(semantic.data_dir(), model_config.current())
                st = vectorstore.get_store("library", create=False, follow=True)
        else:
            st = semantic.peek()
    except Exception as exc:  # noqa: BLE001 — a request must not fail because a store cannot be opened
        log.warning("Library vector store not opened: %s", exc)
        return None, "the library index could not be opened"
    if st is None:
        return None, "the library index has not been built yet"
    if st.is_stale():
        return None, "the embedding model was changed and the library index is being rebuilt"
    if st.count() == 0:
        return None, "the library index is still being built"
    return st, None


class _LiveFeed:
    """The feed as the backend process sees it: its shared FeedStore."""

    def __init__(self):
        from services.feed.store import get_store
        self.store = get_store()

    def vectors(self):
        return self.store.vectors()

    def candidates(self, ids: list[str]) -> dict:
        return self.store.by_ids(ids)

    def labels(self, user: str) -> dict[str, int]:
        return {cid: v for cid, (v, _) in self.store.labels(user).items()}


class _FollowFeed:
    """The feed as a read-only process (the MCP server) sees it: the ``feed`` namespace in follow
    mode and the candidate table through a read-only SQLite connection. Nothing is created."""

    def __init__(self):
        from services.feed import config
        self.path = config.feed_dir() / "feed.sqlite"

    def vectors(self):
        from services import vectorstore
        return vectorstore.get_store("feed", create=False, follow=True)

    def _rows(self, sql: str, args: tuple = ()):
        if not self.path.exists():
            return []
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            return db.execute(sql, args).fetchall()
        finally:
            db.close()

    def candidates(self, ids: list[str]) -> dict:
        from services.feed.store import candidates_by_ids
        return candidates_by_ids(self._rows, ids)

    def labels(self, user: str) -> dict[str, int]:
        return {r["candidate_id"]: r["value"] for r in
                self._rows("SELECT candidate_id, value FROM label WHERE user = ?", (user,))}


def _feed_store(feed):
    """(vectors, reason) of the feed namespace if it can be searched."""
    try:
        vs = feed.vectors()
    except Exception as exc:  # noqa: BLE001
        log.warning("Feed vector store not opened: %s", exc)
        return None, "the feed index could not be opened"
    if vs is None:
        return None, "the feed has no vectors yet"
    if vs.is_stale():
        return None, "the embedding model was changed and the feed vectors are being rebuilt"
    if vs.count() == 0:
        return None, "no feed papers have been embedded yet"
    return vs, None


# ── hydration ─────────────────────────────────────────────────────────────────

_LIBRARY_ROWS = """
MATCH (p:Paper)
WHERE p.id IN $ids AND {vis}
RETURN p.id AS id, p.title AS title, p.year AS year, p.venue AS venue, p.doi AS doi,
       p.arxiv_id AS arxiv_id, p.abstract AS abstract, p.summary AS summary, p.rating AS rating,
       p.bookmarked AS bookmarked, p.reading_status AS reading_status,
       [(p)-[:AUTHORED_BY]->(a:Person) | a.name][..8] AS authors,
       EXISTS {{ (p)-[:TAGGED]->(:Tag {{name: $ref_tag}}) }} AS stub
"""

_VISIBLE_IDENTITIES = "MATCH (p:Paper) WHERE {vis} RETURN p.id AS id, p.doi AS doi, p.title AS title"


def _library_rows(driver, ids: list[str]) -> dict[str, dict]:
    """The papers among ``ids`` that the request user may see, with the fields of a hit."""
    if not ids:
        return {}
    vis, params = paper_visibility_clause("p")
    with driver.session() as s:
        return {r["id"]: dict(r) for r in s.run(_LIBRARY_ROWS.format(vis=vis), ids=ids, ref_tag=REF_TAG, **params)}


def _body(row: dict) -> str:
    from services.library_search.query import clean

    return (row.get("abstract") or "").strip() or clean(row.get("summary") or "")


def _library_hit(row: dict, score: float, full_text: bool) -> dict:
    body = _body(row)
    hit = {
        "source": "library", "id": row["id"], "title": row.get("title") or "", "authors": list(row.get("authors") or []),
        "year": row.get("year"), "venue": row.get("venue"), "doi": row.get("doi"), "arxiv_id": row.get("arxiv_id"),
        "url": paper_url(row["id"]), "score": _score(score), "snippet": snippet(body),
        "in_library": True, "library_paper_id": row["id"], "my_label": None,
        "rating": row.get("rating"), "bookmarked": bool(row.get("bookmarked")),
        "reading_status": row.get("reading_status"), "reference_stub": bool(row.get("stub")),
    }
    if full_text:
        hit["abstract"] = body[:FULL_ABSTRACT_MAX]
    return hit


def _library_hits(driver, store, vec, k: int, *, since: str | None, min_score: float, include_stubs: bool,
                  exclude: str | None, full_text: bool) -> list[dict]:
    """The ``k`` nearest papers this user may see. Visibility, stubs and the year limit are applied
    after the vector search, so more vectors than ``k`` are read, and more again while the survivors
    are fewer than ``k`` and the store may still hold more."""
    fetch = min(OVERFETCH * k, FETCH_CAP)
    flt = {"exclude_id": [exclude]} if exclude else None
    since_year = int(since[:4]) if since else None
    while True:
        raw = store.search(vec, fetch, flt)
        near = [h for h in raw if h.score >= min_score]
        rows = _library_rows(driver, [h.id for h in near])
        hits: list[dict] = []
        for h in near:
            row = rows.get(h.id)
            if row is None or (row.get("stub") and not include_stubs):
                continue
            if since_year is not None and not (isinstance(row.get("year"), int) and row["year"] >= since_year):
                continue
            hits.append(_library_hit(row, h.score, full_text))
            if len(hits) == k:
                return hits
        if len(raw) < fetch or len(near) < len(raw) or fetch >= FETCH_CAP:
            return hits     # nothing further out can qualify
        fetch = min(fetch * 4, FETCH_CAP)


def _visible_index(driver):
    vis, params = paper_visibility_clause("p")
    with driver.session() as s:
        rows = [[r["id"], r["doi"], r["title"]] for r in s.run(_VISIBLE_IDENTITIES.format(vis=vis), **params)]
    return build_index(rows)


def _feed_hits(driver, feed, vs, vec, user: str, k: int, *, since: str | None, min_score: float,
               exclude_library_id: str | None, full_text: bool) -> list[dict]:
    from services.feed import library as feed_library

    flt = {"published": {"gte": since}} if since else None
    raw = [h for h in vs.search(vec, k + 10, flt) if h.score >= min_score]
    cands = feed.candidates([h.id for h in raw])
    raw = [h for h in raw if h.id in cands]
    if not raw:
        return []
    index = _visible_index(driver)
    labels = feed.labels(user)
    hits: list[dict] = []
    for h in raw:
        c = cands[h.id]
        lib_id = feed_library.match_candidate(index, c)
        if exclude_library_id and lib_id == exclude_library_id:
            continue
        hit = {
            "source": "feed", "id": c.id, "title": c.title, "authors": list(c.authors),
            "year": int(c.published[:4]) if c.published[:4].isdigit() else None, "published": c.published,
            "doi": c.doi, "url": c.url, "score": _score(h.score), "snippet": snippet(c.abstract),
            "in_library": lib_id is not None, "library_paper_id": lib_id,
            "my_label": labels.get(c.id), "feed_source": c.source, "categories": list(c.categories),
        }
        if full_text:
            hit["abstract"] = (c.abstract or "")[:FULL_ABSTRACT_MAX]
        hits.append(hit)
        if len(hits) == k:
            break
    return hits


# ── the search ────────────────────────────────────────────────────────────────

def _unavailable(reason: str, scope: str, skipped: dict | None = None, mode: str | None = None) -> dict:
    return {"available": False, "reason": reason, "scope": scope, "mode": mode, "total": 0, "hits": [],
            "skipped": skipped or {}}


class _NotReady(Exception):
    """No embedding model here and no backend to ask (a request never loads the model)."""


def _require_embedder() -> None:
    from services.conferences.embedder import ready, remote_url

    if not (ready() or remote_url()):
        raise _NotReady("the embedding model is still loading; try again in a minute")


def _plan(scope: str, follow: bool):
    """(effective scope, library store, feed access + store, skipped) for a request."""
    if scope in ("feed", "both") and not feed_enabled():
        if scope == "feed":
            raise FeedDisabled("The paper feed is not enabled on this instance")
        scope = "library"
    skipped: dict[str, str] = {}
    lib = feed = vs = None
    if scope in ("library", "both"):
        lib, why = _library_store(follow)
        if lib is None:
            skipped["library"] = why
    if scope in ("feed", "both"):
        try:
            feed = _FollowFeed() if follow else _LiveFeed()
            vs, why = _feed_store(feed)
        except Exception as exc:  # noqa: BLE001 — no writable feed directory, and the like
            log.warning("Feed not opened for similar search: %s", exc)
            vs, why = None, "the feed could not be opened"
        if vs is None:
            skipped["feed"] = why
    return scope, lib, feed, vs, skipped


def _search_vector(user: str, vec_fn, *, k: int, scope: str, since: str | None, min_score: float,
                   include_stubs: bool, follow: bool, full_text: bool, driver, exclude: str | None = None,
                   mode_hint: str | None = None) -> dict:
    """Shared body of both searches. ``vec_fn(lib_store)`` returns ``(vector, mode)``; it runs only
    when there is something to search."""
    scope, lib, feed, vs, skipped = _plan(scope, follow)
    if lib is None and vs is None:
        return _unavailable("; ".join(f"{ns}: {why}" for ns, why in skipped.items()), scope, skipped)
    try:
        vec, mode = vec_fn(lib)
    except _NotReady as exc:
        return _unavailable(str(exc), scope, skipped)
    except SimilarError:
        raise
    except Exception as exc:  # noqa: BLE001 — no model, no backend, no torch: say so, do not raise
        log.warning("Similar search: the text could not be embedded: %s", exc)
        return _unavailable(f"the text could not be embedded ({type(exc).__name__}); is the embedding model available?",
                            scope, skipped)
    driver = _driver(driver)
    hits: list[dict] = []
    warnings: list[str] = []
    try:
        with _as_user(user):
            if lib is not None:
                hits += _library_hits(driver, lib, vec, k, since=since, min_score=min_score, include_stubs=include_stubs,
                                      exclude=exclude, full_text=full_text)
                if not follow:
                    from services.library_search import semantic
                    st = semantic.status()
                    if st.get("state") == "building":
                        warnings.append(f"the library index is still being built ({st.get('done', 0)} of "
                                        f"{st.get('todo', 0)} new papers embedded); some papers may be missing")
            if vs is not None:
                hits += _feed_hits(driver, feed, vs, vec, user, k, since=since, min_score=min_score,
                                   exclude_library_id=exclude, full_text=full_text)
    except StaleStoreError:     # a store was swapped for a rebuild between the check and the search
        return _unavailable("the embedding model was changed and the index is being rebuilt", scope, skipped)
    hits.sort(key=lambda h: -h["score"])
    hits = hits[:k]
    out = {"available": True, "reason": None, "scope": scope, "mode": mode_hint or mode, "k": k, "total": len(hits),
           "hits": hits, "skipped": skipped}
    if warnings:
        out["warnings"] = warnings
    return out


def search_by_text(user: str, text: str, k: int = K_DEFAULT, scope: str = "both", since=None,
                   min_score: float = 0.0, include_stubs: bool = False, *, follow: bool = False,
                   full_text: bool = False, driver=None) -> dict:
    """The papers nearest to ``text`` (20 to 20,000 characters) in the library and/or the feed.

    ``scope``: ``library``, ``feed`` (raises FeedDisabled when the feed is off) or ``both`` (the
    library only when the feed is off). ``since``: only papers published on or after that date (the
    library knows a paper's year only, so a library paper counts from the first day of its year).
    ``min_score``: cosine floor. ``full_text`` adds each hit's abstract (the page needs it, a tool
    result does not). Raises InvalidRequest for a bad argument; an index that cannot be searched
    gives ``{"available": False, "reason": ...}``."""
    from services.conferences.embedder import embed_search_text

    text = _clean_text(text)
    _check(k, scope, min_score)
    since = parse_since(since)
    def vector(lib):
        _require_embedder()
        return embed_search_text(text)

    return _search_vector(user, vector, k=k, scope=scope, since=since, min_score=min_score,
                          include_stubs=include_stubs, follow=follow, full_text=full_text, driver=driver)


def search_by_paper(user: str, paper_id: str, k: int = K_DEFAULT, scope: str = "both", since=None,
                    min_score: float = 0.0, include_stubs: bool = False, *, follow: bool = False,
                    full_text: bool = False, driver=None) -> dict:
    """The papers nearest to a library paper that ``user`` may see ("more like this"). The paper's
    stored vector is used; one that is not indexed yet is embedded from its title and abstract. The
    paper itself is left out. Raises PaperNotFound for a paper that does not exist or is not visible."""
    from services.conferences.embedder import embed_document
    from services.library_search.semantic import paper_text

    _check(k, scope, min_score)
    since = parse_since(since)
    drv = _driver(driver)
    with _as_user(user), drv.session() as s:
        vis, params = paper_visibility_clause("p")      # inside: the clause reads the request user
        rec = s.run(f"MATCH (p:Paper {{id: $id}}) WHERE {vis} "
                    "RETURN p.title AS title, p.abstract AS abstract, p.summary AS summary", id=paper_id, **params).single()
    if rec is None:
        raise PaperNotFound("Paper not found")
    text = paper_text(rec["title"], rec["abstract"], rec["summary"])

    def vector(lib):
        if lib is not None:
            got = lib.get([paper_id])
            if paper_id in got:
                return got[paper_id][0], "paper"
        if len(text) < 3:
            raise InvalidRequest("this paper has no title, abstract or summary to compare")
        _require_embedder()
        return embed_document(text), "paper"

    return _search_vector(user, vector, k=k, scope=scope, since=since, min_score=min_score,
                          include_stubs=include_stubs, follow=follow, full_text=full_text, driver=drv,
                          exclude=paper_id, mode_hint="paper")
