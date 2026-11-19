"""Fakes for the abstract-backfill tests: an in-memory graph driver that answers exactly the
queries of services/abstract_backfill.py, and an HTTP layer on httpx.MockTransport. No database,
no network, no sleeping."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from urllib.parse import unquote

import httpx

from services import abstract_backfill as ab

_HTTP = ab.Http      # the real class, kept for tests that patch ``ab.Http`` with a factory

LONG = ("We study the behaviour of synthetic systems under repeated perturbation and report "
        "how the measured response scales with the size of the perturbation.")


class Rows(list):
    def single(self):
        return self[0] if self else None


class FakeDriver:
    """Papers are dicts (id, doi, title, abstract, tags, ...). ``before_write(paper_id, driver)`` runs
    just before a write query is evaluated (to simulate a race). ``fail_write`` makes writes raise."""

    def __init__(self, papers: list[dict]):
        self.papers = {p["id"]: dict(p) for p in papers}
        self.queries: list[tuple[str, dict]] = []
        self.writes: list[dict] = []
        self.before_write = None
        self.fail_write: set[str] = set()

    def session(self):
        return _Session(self)

    def get(self, pid: str) -> dict:
        return self.papers[pid]


class _Session:
    def __init__(self, driver: FakeDriver):
        self.d = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @staticmethod
    def _empty(p) -> bool:
        return not (p.get("abstract") or "").strip()

    def run(self, query: str, parameters: dict | None = None, **kw):
        params = {**(parameters or {}), **kw}
        used = set(re.findall(r"\$(\w+)", query))
        assert used <= set(params), f"unbound parameters {used - set(params)}"
        self.d.queries.append((query, params))
        d = self.d
        stub_ok = lambda p: params["include_stubs"] or ab.REF_TAG not in (p.get("tags") or [])  # noqa: E731
        if query == ab.CANDIDATES_QUERY:
            rows = [p for p in sorted(d.papers.values(), key=lambda p: p["id"])
                    if self._empty(p) and (p.get("doi") or "").strip() and stub_ok(p)]
            return Rows({"id": p["id"], "doi": p["doi"], "title": p.get("title")} for p in rows)
        if query == ab.NO_DOI_QUERY:
            rows = [p for p in sorted(d.papers.values(), key=lambda p: p["id"])
                    if self._empty(p) and not (p.get("doi") or "").strip() and stub_ok(p)]
            return Rows({"id": p["id"], "title": p.get("title")} for p in rows)
        if query == ab.WRITE_QUERY:
            if d.before_write:
                d.before_write(params["id"], d)
            if params["id"] in d.fail_write:
                raise RuntimeError("database down")
            p = d.papers.get(params["id"])
            if p is None or not self._empty(p):
                return Rows()
            p["abstract"] = params["abstract"]
            p["abstract_source"] = params["source"]
            p["abstract_fetched_at"] = params["now"]
            d.writes.append({"id": params["id"], "source": params["source"]})
            return Rows([{"id": p["id"]}])
        if query == ab.UNDO_READ_QUERY:
            p = d.papers.get(params["id"])
            return Rows([{"abstract": p.get("abstract"), "source": p.get("abstract_source")}] if p else [])
        if query == ab.UNDO_WRITE_QUERY:
            p = d.papers.get(params["id"])
            if p and p.get("abstract_source") == params["source"] and p.get("abstract") == params["abstract"]:
                for k in ("abstract", "abstract_source", "abstract_fetched_at"):
                    p.pop(k, None)
                return Rows([{"id": p["id"]}])
            return Rows()
        raise AssertionError(f"unexpected query: {query[:80]}")


# ── HTTP ──────────────────────────────────────────────────────────────────────

class FakeClock:
    """``sleep`` advances ``now``; both are injected into abstract_backfill.Http."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


class FakeWeb:
    """Canned answers per service. ``openalex``/``s2``/``crossref`` map a DOI to ``(title, abstract)``,
    ``arxiv`` an arXiv id. A host in ``down`` answers 503; a host in ``limited`` answers 429 with
    ``Retry-After: <retry_after>`` ``limited[host]`` times first."""

    def __init__(self):
        self.openalex: dict[str, tuple[str, str]] = {}
        self.s2: dict[str, tuple[str, str]] = {}
        self.arxiv: dict[str, tuple[str, str]] = {}
        self.crossref: dict[str, tuple[str, str]] = {}
        self.openalex_by_title: dict[str, list[tuple[str, str]]] = {}
        self.down: set[str] = set()
        self.limited: dict[str, int] = {}
        self.retry_after = "7"
        self.requests: list[httpx.Request] = []
        self.clock = FakeClock()

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]

    def to(self, host: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == host]

    def http(self, contact: str = "", **kw) -> ab.Http:
        client = httpx.Client(transport=httpx.MockTransport(self.handle))
        return _HTTP(client, contact=contact, sleep=self.clock.sleep, clock=self.clock.clock, **kw)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.down:
            return httpx.Response(503, text="down")
        if self.limited.get(host, 0) > 0:
            self.limited[host] -= 1
            return httpx.Response(429, headers={"Retry-After": self.retry_after}, text="slow down")
        if host == "api.openalex.org":
            return self._openalex(request)
        if host == "api.semanticscholar.org":
            return self._s2(request)
        if host == "export.arxiv.org":
            return self._arxiv(request)
        if host == "api.crossref.org":
            return self._crossref(request)
        return httpx.Response(404)

    def _openalex(self, request):
        flt = request.url.params.get("filter", "")
        if flt.startswith("title.search:"):
            title = flt.split(":", 1)[1].strip()
            works = [{"id": "W1", "title": t, "doi": None, "abstract_inverted_index": _invert(a)}
                     for t, a in self.openalex_by_title.get(title, [])]
            return httpx.Response(200, json={"results": works})
        assert flt.startswith("doi:")
        dois = [x.removeprefix("https://doi.org/") for x in flt[4:].split("|")]
        assert len(dois) <= 50
        works = [{"id": f"W{i}", "doi": f"https://doi.org/{d}", "title": self.openalex[d][0],
                  "abstract_inverted_index": _invert(self.openalex[d][1]) if self.openalex[d][1] else None}
                 for i, d in enumerate(dois) if d in self.openalex]
        return httpx.Response(200, json={"meta": {"count": len(works)}, "results": works})

    def _s2(self, request):
        ids = json.loads(request.content)["ids"]
        out = []
        for i in ids:
            d = i.removeprefix("DOI:")
            out.append({"paperId": "x", "title": self.s2[d][0], "abstract": self.s2[d][1] or None,
                        "externalIds": {"DOI": d}} if d in self.s2 else None)
        return httpx.Response(200, json=out)

    def _arxiv(self, request):
        ids = request.url.params["id_list"].split(",")
        entries = ""
        for i in ids:
            if i in self.arxiv:
                t, a = self.arxiv[i]
                entries += (f"<entry><id>http://arxiv.org/abs/{i}v1</id><title>{t}</title>"
                            f"<summary>{a}</summary></entry>")
        xml = f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
        return httpx.Response(200, text=xml)

    def _crossref(self, request):
        doi = unquote(request.url.path.removeprefix("/works/"))
        if doi not in self.crossref:
            return httpx.Response(404, text="Resource not found.")
        t, a = self.crossref[doi]
        return httpx.Response(200, json={"status": "ok", "message": {"title": [t], "abstract": a}})


def _invert(text: str) -> dict[str, list[int]]:
    idx: dict[str, list[int]] = defaultdict(list)
    for pos, word in enumerate(text.split()):
        idx[word].append(pos)
    return dict(idx)


def paper(pid: str, doi: str | None, title: str, **extra) -> dict:
    return {"id": pid, "doi": doi, "title": title, **extra}
