"""Search several namespaces at once: "find papers like this" over the library and the feed.

    from services.vectorstore.similar import find_similar, find_similar_text
    hits = find_similar(vector, namespaces=("library", "feed"), k=10)
    hits = find_similar_text(abstract, k=10, filter={"year": {"gte": 2024}})

Namespaces that do not exist yet, or that are stale (built with another model, so in another
space), are skipped and named in the result's ``skipped``. Scores of one model are comparable
across namespaces, so the lists are merged by score. ``find_similar_text`` embeds with the
configured model and, like every request path, never loads it: it raises ``RuntimeError`` when
the model is not loaded yet.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from services.vectorstore.registry import get_store


class SimilarHit(NamedTuple):
    namespace: str
    id: str
    score: float
    metadata: dict


class SimilarResult(NamedTuple):
    hits: list[SimilarHit]
    skipped: dict[str, str]     # namespace -> "missing" | "empty" | "stale"


def find_similar(vector: Any, namespaces: tuple[str, ...] = ("library", "feed"), k: int = 10,
                 filter: dict | None = None) -> SimilarResult:
    hits: list[SimilarHit] = []
    skipped: dict[str, str] = {}
    for ns in namespaces:
        store = get_store(ns, create=False)
        if store is None:
            skipped[ns] = "missing"
        elif store.count() == 0:
            skipped[ns] = "empty"
        elif store.is_stale():
            skipped[ns] = "stale"
        else:
            hits += [SimilarHit(ns, h.id, h.score, h.metadata) for h in store.search(vector, k, filter)]
    hits.sort(key=lambda h: -h.score)
    return SimilarResult(hits[:k], skipped)


def find_similar_text(text: str, namespaces: tuple[str, ...] = ("library", "feed"), k: int = 10,
                      filter: dict | None = None) -> SimilarResult:
    from services.conferences.embedder import embed_query, ready, remote_url

    if not text.strip():
        return SimilarResult([], {})
    if not (ready() or remote_url()):
        raise RuntimeError("the embedding model is not loaded yet")
    return find_similar(embed_query(text), namespaces, k, filter)
