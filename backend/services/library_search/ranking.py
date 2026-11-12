"""Scoring, coverage filter and rank fusion for the library search. Pure functions.

Every source (paper fields, author/topic/tag names, venue, notes, highlights, claims, full
text, DOI/arXiv id) returns Lucene scores. Raw Lucene scores are not comparable across
indexes, so each source's scores are divided by the best score that source returned for
the query and multiplied by the source weight. Title bonuses are computed in Python from
the title itself. A hit must contain every unit of the query somewhere (coverage 1); only
when no hit does is the filter relaxed and partial hits are ranked by how much they cover.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

from services.library_search.query import (
    Coverage,
    ParsedQuery,
    Unit,
    UnitMatcher,
    tokenize,
)

WEIGHTS: dict[str, float] = {
    "identifier": 20.0,  # DOI / arXiv id typed as the query
    "paper": 4.0,        # paper_search index: title^4, abstract, summary^0.7
    "author": 3.0,
    "topic": 2.0,
    "tag": 1.5,
    "venue": 1.0,
    "note": 2.5,
    "highlight": 2.5,
    "claim": 1.5,
    "fulltext": 1.5,
}
TITLE_ALL_UNITS = 3.0    # every unit occurs in the title
TITLE_PHRASE = 2.0       # the query occurs in the title as a phrase
TITLE_EXACT = 4.0        # the title is the query
AUTHOR_ALL_UNITS = 5.0   # the query is (part of) an author's name: "Karras", "tero karras"
REFERENCE_FACTOR = 0.6   # reference stubs (tag from-references) rank below library papers
CITED_WEIGHT = 0.12      # x (1 + w * ln(1 + papers in the library citing it)): 16 citers -> x1.34
COVERAGE_FLOOR = 0.4     # multiplier of a hit covering no unit (only seen in relaxed mode)
RRF_K = 20               # reciprocal-rank fusion constant for hybrid mode
RRF_WEIGHTS = {"lexical": 1.0, "semantic": 0.7}

# Display order of the matched_fields list.
FIELD_ORDER = ["doi", "title", "author", "topic", "tag", "venue", "abstract", "summary",
               "note", "highlight", "claim", "fulltext", "semantic"]
# Fine-grained field -> the coarse matched_in string older clients read ("note+paper").
_LEGACY = {"doi": "paper", "title": "paper", "author": "paper", "topic": "paper", "tag": "paper",
           "venue": "paper", "abstract": "paper", "summary": "paper"}


@dataclass
class Candidate:
    id: str
    title: str = ""
    year: int | None = None
    created_at: str | None = None
    ref: bool = False
    cited: int = 0                                               # library papers citing it
    rating: int | None = None                                    # sort fields, see sort_candidates
    citation_count: int | None = None
    updated_at: str | None = None
    fields_loaded: bool = False                                  # year/created_at/rating/... are set
    scores: dict[str, float] = field(default_factory=dict)     # source -> best Lucene score
    texts: dict[str, list[str]] = field(default_factory=dict)  # field -> matched texts
    pages: list[int] = field(default_factory=list)             # pages of matched highlights
    score: float = 0.0
    coverage: float = 0.0
    fields: list[str] = field(default_factory=list)
    semantic: float | None = None                              # cosine similarity

    def add(self, source: str, score: float, fld: str | None = None, text: str | None = None,
            cap: int = 4) -> None:
        self.scores[source] = max(self.scores.get(source, 0.0), float(score or 0.0))
        if fld and text:
            bucket = self.texts.setdefault(fld, [])
            if text not in bucket and len(bucket) < cap:
                bucket.append(text)


@lru_cache(maxsize=20000)
def _title_tokens(title: str) -> tuple[str, ...]:
    return tuple(tokenize(title))


def score_candidates(cands: list[Candidate], pq: ParsedQuery) -> None:
    """Set ``score``, ``coverage`` and ``fields`` on every candidate in place."""
    maxima: dict[str, float] = {}
    for c in cands:
        for s, v in c.scores.items():
            maxima[s] = max(maxima.get(s, 0.0), v)
    n = len(pq.units)
    cover = Coverage(pq.units, (t for c in cands for t in [c.title, *(x for ts in c.texts.values() for x in ts)]))
    phrase = UnitMatcher(Unit(pq.phrase)) if pq.phrase else None
    query_tokens = tuple(tokenize(pq.raw))
    everything = set(range(n))

    for c in cands:
        base = sum(WEIGHTS.get(s, 1.0) * (v / maxima[s] if maxima.get(s) else 1.0)
                   for s, v in c.scores.items())
        title_cov = cover.covered([c.title])
        if "fulltext" in c.scores or "identifier" in c.scores or (n <= 1 and c.scores):
            cov = everything
        elif len(title_cov) == n:
            cov = title_cov
        else:
            cov = title_cov | cover.covered([t for ts in c.texts.values() for t in ts])
        bonus = 0.0
        if n and len(title_cov) == n:
            bonus += TITLE_ALL_UNITS
        if phrase and phrase.found(c.title):
            bonus += TITLE_PHRASE
        if query_tokens and _title_tokens(c.title) == query_tokens:
            bonus += TITLE_EXACT
        if n and c.texts.get("author") and len(cover.covered(c.texts["author"])) == n:
            # Papers BY Karras before papers that cite Karras in their summary.
            bonus += AUTHOR_ALL_UNITS
        c.coverage = len(cov) / n if n else 1.0
        c.score = (base + bonus) * (COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * c.coverage)
        if c.ref:
            c.score *= REFERENCE_FACTOR
        if c.cited:
            # Foundational papers of the library (cited by many of its papers) win ties
            # among many similar titles ("flow matching" -> Lipman et al.).
            c.score *= 1 + CITED_WEIGHT * math.log1p(c.cited)

        fields = set()
        if "identifier" in c.scores:
            fields.add("doi")
        if title_cov:
            fields.add("title")
        for f in ("abstract", "summary"):
            if cover.covered(c.texts.get(f, [])):
                fields.add(f)
        for f in ("author", "topic", "tag", "venue", "note", "highlight", "claim"):
            if c.texts.get(f):
                fields.add(f)
        if "fulltext" in c.scores:
            fields.add("fulltext")
        if "paper" in c.scores and not fields & {"title", "abstract", "summary"}:
            # Lucene matched a paper field the Python matcher did not confirm (analyzer
            # differences such as "3's"); report it as a title/abstract match anyway.
            fields.add("title" if c.title else "abstract")
        c.fields = [f for f in FIELD_ORDER if f in fields]


def rank(cands: list[Candidate]) -> tuple[list[Candidate], bool]:
    """Hits covering every unit, best first. If there are none, every hit ordered by
    score, and ``relaxed`` is True."""
    full = [c for c in cands if c.coverage >= 1.0]
    relaxed = not full
    pool = cands if relaxed else full
    return sorted(pool, key=lambda c: (-c.score, c.title or "", c.id)), relaxed


def rrf(rankings: dict[str, list[str]], weights: dict[str, float] | None = None,
        k: int = RRF_K) -> dict[str, float]:
    """Weighted reciprocal-rank fusion: sum over lists of ``w / (k + rank)``, rank from 1."""
    weights = weights or RRF_WEIGHTS
    out: dict[str, float] = {}
    for name, ids in rankings.items():
        w = weights.get(name, 1.0)
        for r, pid in enumerate(ids, start=1):
            out[pid] = out.get(pid, 0.0) + w / (k + r)
    return out


def hybrid_weights(n_units: int, relaxed: bool, top_sim: float | None) -> dict[str, float]:
    """RRF weights for hybrid mode. Lexical counts less for long natural-language queries
    (every word is then matched somewhere in many long full texts) and in relaxed mode;
    semantic counts less when even the best embedding match is weak (jargon the model
    does not know: ``over-conditioning`` peaks near 0.66, ``flow matching`` at 0.89)."""
    lex = 1.0 if n_units <= 3 else 0.8 if n_units == 4 else 0.4
    if relaxed:
        lex *= 0.6
    conf = 1.0 if top_sim is None else min(1.0, max(0.0, (top_sim - 0.6) / 0.2))
    return {"lexical": lex, "semantic": RRF_WEIGHTS["semantic"] * conf}


def fuse(lexical: list[Candidate], semantic: list[Candidate], weights: dict[str, float]) -> list[Candidate]:
    """Merge a ranked lexical list and a ranked semantic list by weighted RRF. Papers in
    both keep their lexical fields plus "semantic"; the result is sorted by fused score."""
    by_id = {c.id: c for c in lexical}
    fused = rrf({"lexical": [c.id for c in lexical], "semantic": [c.id for c in semantic]}, weights)
    for c in semantic:
        if c.id in by_id:
            by_id[c.id].semantic = c.semantic
            if "semantic" not in by_id[c.id].fields:
                by_id[c.id].fields = by_id[c.id].fields + ["semantic"]
        else:
            c.fields = ["semantic"]
            by_id[c.id] = c
    for pid, c in by_id.items():
        c.score = fused.get(pid, 0.0)
    return sorted(by_id.values(), key=lambda c: (-c.score, c.title or "", c.id))


SORTS = {"relevance", "year_desc", "year_asc", "date_desc", "date_asc", "title_asc",
         "rating_desc", "citations_desc", "updated_desc"}


def sort_candidates(cands: list[Candidate], sort: str) -> list[Candidate]:
    """Re-order ranked hits by a field; ``relevance`` (or unknown) keeps the order. Ties
    keep the incoming (relevance) order; missing ratings / citation counts / years sort last."""
    if sort == "year_desc":
        return sorted(cands, key=lambda c: (-(c.year or 0), -c.score))
    if sort == "year_asc":
        return sorted(cands, key=lambda c: (c.year or 9999, -c.score))
    if sort == "date_desc":
        return sorted(cands, key=lambda c: str(c.created_at or ""), reverse=True)
    if sort == "date_asc":
        return sorted(cands, key=lambda c: str(c.created_at or ""))
    if sort == "title_asc":
        return sorted(cands, key=lambda c: (c.title or "").lower())
    if sort == "rating_desc":
        newest = sorted(cands, key=lambda c: str(c.created_at or ""), reverse=True)
        return sorted(newest, key=lambda c: (c.rating is None, -(c.rating or 0)))
    if sort == "citations_desc":
        return sorted(cands, key=lambda c: (c.citation_count is None, -(c.citation_count or 0)))
    if sort == "updated_desc":
        return sorted(cands, key=lambda c: str(c.updated_at or c.created_at or ""), reverse=True)
    return cands


def legacy_matched_in(fields: list[str]) -> str:
    """The pre-2026-10 ``matched_in`` string: coarse sources joined with '+'."""
    coarse = {_LEGACY.get(f, f) for f in fields}
    return "+".join(sorted(coarse)) if coarse else "paper"
