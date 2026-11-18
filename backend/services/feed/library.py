"""The user's library as the feed sees it: signals, titles and embeddings.

Embeddings come from the library search index (``services.library_search.semantic``) when it
holds them; papers it lacks are embedded by the refresh thread and kept in the feed store.
Nothing here loads the embedding model except ``sync_missing_embeddings``, which only the
refresh thread calls.
"""
from __future__ import annotations

import logging

import numpy as np

from db.queries.visibility import paper_visibility_clause, project_visibility_clause
from services.library_lookup import REF_TAG
from services.feed.store import DIM, FeedStore

log = logging.getLogger(__name__)

_ROWS_QUERY = """
MATCH (p:Paper)
WHERE {vis}
RETURN p.id AS id, p.title AS title, p.doi AS doi, p.rating AS rating,
       p.bookmarked AS bookmarked, p.reading_status AS status, p.created_at AS created_at,
       size([(p)-[:HAS_ANNOTATION]->(a:Annotation) | a]) AS highlights,
       EXISTS {{ MATCH (u:User)-[:ADDED]->(p) WHERE toLower(u.name) = toLower($feed_user) }} AS mine,
       EXISTS {{ MATCH (p)-[:IN_PROJECT]->(pr:Project) WHERE {pvis} }} AS in_project,
       EXISTS {{ MATCH (p)-[:TAGGED]->(:Tag {{name: $ref_tag}}) }} AS stub,
       (trim(coalesce(p.abstract, '')) <> '' OR trim(coalesce(p.summary, '')) <> '') AS has_text
"""


def visible_papers(driver, user: str) -> tuple[list[dict], bool]:
    """Every paper ``user`` may see, with the signals the feed uses, and whether the instance
    has a single user. Rating, bookmark and reading status are stored once per paper, not per
    user, so on an instance with several users they only count for papers that user added
    (``mine``); with one user they count for every paper. ``kept`` needs no such care: it is
    derived per user from ``mine`` (added by this user) and ``in_project`` (a project this user
    may see), and only for real papers (``stub`` false) with an abstract or summary (``has_text``)."""
    vis, params = paper_visibility_clause("p")
    pvis, pparams = project_visibility_clause("pr")
    with driver.session() as s:
        rows = [dict(r) for r in s.run(_ROWS_QUERY.format(vis=vis, pvis=pvis), feed_user=user,
                                        ref_tag=REF_TAG, **{**params, **pparams})]
        n_users = s.run("MATCH (u:User) RETURN count(u) AS n").single()["n"]
    return rows, n_users <= 1


def semantic_snapshot() -> tuple[list[str], np.ndarray]:
    """Ids and vectors held by the library search index right now (empty when it is off or still building)."""
    try:
        from services.library_search import semantic
        if not semantic.enabled():
            return [], np.zeros((0, DIM), dtype=np.float32)
        with semantic._lock:
            return list(semantic._ids), semantic._emb
    except Exception:  # noqa: BLE001
        return [], np.zeros((0, DIM), dtype=np.float32)


def vectors(store: FeedStore, wanted: set[str] | None = None) -> tuple[list[str], np.ndarray]:
    """Library paper ids and vectors: the search index first, the feed's own cache for the rest.
    ``wanted`` limits the result to those ids."""
    ids, emb = semantic_snapshot()
    have = set(ids)
    own_ids, own = store.library_embeddings()
    keep_own = [i for i, pid in enumerate(own_ids) if pid not in have]
    all_ids = list(ids) + [own_ids[i] for i in keep_own]
    parts = ([emb] if len(ids) else []) + ([own[keep_own]] if keep_own else [])
    mat = np.vstack(parts) if parts else np.zeros((0, DIM), dtype=np.float32)
    if wanted is not None:
        idx = [i for i, pid in enumerate(all_ids) if pid in wanted]
        return [all_ids[i] for i in idx], mat[idx] if idx else np.zeros((0, DIM), dtype=np.float32)
    return all_ids, mat


def sync_missing_embeddings(driver, store: FeedStore, embed) -> int:
    """Embed library papers that neither the search index nor the feed cache holds (or whose
    text changed). Runs in the refresh thread. Returns how many were embedded."""
    from services.library_search import semantic

    with driver.session() as s:
        texts = {r["id"]: semantic.paper_text(r["title"], r["abstract"], r["summary"]) for r in s.run(
            "MATCH (p:Paper) RETURN p.id AS id, p.title AS title, p.abstract AS abstract, p.summary AS summary")}
    indexed = set(semantic_snapshot()[0])
    cached = store.library_hashes()
    stale = [pid for pid in cached if pid not in texts or pid in indexed]
    if stale:
        store.delete_library_embeddings(stale)
    todo = [pid for pid, t in texts.items() if pid not in indexed
            and cached.get(pid) != semantic.text_hash(t)]
    for i in range(0, len(todo), 128):
        chunk = todo[i:i + 128]
        vecs = embed([texts[pid] for pid in chunk])
        store.set_library_embeddings({pid: (semantic.text_hash(texts[pid]), vecs[j])
                                      for j, pid in enumerate(chunk)})
    return len(todo)
