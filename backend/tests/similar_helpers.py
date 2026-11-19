"""Synthetic library for the similar-search tests: a fake graph driver that answers the three
queries of services/similar_search.py with the app's per-user visibility rule, and topic-clustered
vectors (tests/feed_helpers.py). No database, no model, no network."""
from __future__ import annotations

import numpy as np

from services import vectorstore
from tests.feed_helpers import topic_vec


class Rows(list):
    def single(self):
        return self[0] if self else None


class FakeLibraryDriver:
    """Papers are dicts; ``project`` is a project name or None; ``members`` maps a project to its users.
    Visibility mirrors db/queries/visibility.paper_visibility_clause: a paper outside every project is
    visible to everyone, one in a project to its members. No ``vis_user`` parameter means an admin."""

    def __init__(self):
        self.papers: dict[str, dict] = {}
        self.members: dict[str, set[str]] = {}
        self.queries: list[tuple[str, dict]] = []

    def add(self, pid: str, topic: int, *, title=None, abstract=None, project=None, stub=False, year=2024,
            doi=None, authors=("Ada Example",), summary=None, vec=True) -> str:
        self.papers[pid] = {
            "id": pid, "title": title or f"Synthetic paper {pid} topic-{topic}",
            "abstract": abstract if abstract is not None else f"Abstract of {pid}. " + "word " * 80,
            "summary": summary, "year": year, "venue": "Synthetic Venue", "doi": doi, "arxiv_id": None,
            "rating": None, "bookmarked": False, "reading_status": "unread", "authors": list(authors),
            "stub": stub, "project": project, "topic": topic,
        }
        if vec:
            vectorstore.get_store("library").upsert(
                [pid], topic_vec(topic, pid)[None, :], [{"kind": "paper", "source": "library"}])
        return pid

    def visible(self, p: dict, params: dict) -> bool:
        if "vis_user" not in params:
            return True
        if not p["project"]:
            return True
        return params["vis_user"].lower() in {u.lower() for u in self.members.get(p["project"], set())}

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query: str, **params):
        self.queries.append((query, params))
        if "IN_PROJECT" not in query and "true" not in query:
            raise AssertionError("the query does not carry the visibility clause")
        if "p.id IN $ids" in query:
            return Rows(dict(p) for pid in params["ids"] if (p := self.papers.get(pid)) and self.visible(p, params))
        if "{id: $id}" in query:
            p = self.papers.get(params["id"])
            return Rows([dict(p)] if p and self.visible(p, params) else [])
        if "AS doi, p.title AS title" in query:
            return Rows({"id": p["id"], "doi": p["doi"], "title": p["title"]}
                        for p in self.papers.values() if self.visible(p, params))
        raise AssertionError(f"unexpected query: {query}")


def query_vec(topic: int) -> np.ndarray:
    return topic_vec(topic, "the-query", spread=0.2)


def patch_embedder(monkeypatch, topic: int | None = 1, mode: str = "document", calls: list | None = None):
    """The embedder answers with a vector of ``topic`` (and records the texts); the model counts as loaded."""
    from services.conferences import embedder

    monkeypatch.setattr(embedder, "ready", lambda: True)

    def embed_search_text(text):
        if calls is not None:
            calls.append(text)
        return query_vec(topic), mode

    monkeypatch.setattr(embedder, "embed_search_text", embed_search_text)
    monkeypatch.setattr(embedder, "embed_document", lambda text: (calls.append(text) if calls is not None else None) or query_vec(topic))
