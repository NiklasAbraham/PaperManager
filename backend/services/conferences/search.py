"""Search across every loaded conference at once: papers by title and by meaning, authors
by name, and how much of each conference (and each year of a series) is about a topic.

One in-memory index over all loaded datasets, rebuilt when one of them is reloaded:

* titles: folded word -> postings (global paper ids). A query word matches a title word
  exactly, as a plural / singular, as a prefix when it is the word being typed, or one
  edit away (typos, words of five letters or more);
* authors: folded full name -> mentions (paper, author position), and name words -> names,
  so "deane", "charlotte dea", "c deane" and "Deane, Charlotte" find the same name. One
  name can be two people: results group by name and keep each mention's institutions.

Semantic ranking and the topic counts use title-only vectors (``Dataset.temb``): title +
abstract vectors sit 0.03-0.07 higher in cosine to any query than title-only ones, so a
conference with abstracts would otherwise outrank one without on every topic.
"""
from __future__ import annotations

import bisect
import logging
import math
import re
import threading
import time
from collections import Counter, defaultdict
from typing import Iterable

import numpy as np

from services.conferences import areas as area_mod
from services.conferences import institutions, store

log = logging.getLogger(__name__)

_STOP = frozenset(
    "a an and are as at by for from in into is it its of on or over the to under via with without "
    "towards toward using".split())
_WORD = re.compile(r"[a-z0-9]+")
_PREFIX_CAP = 5000          # vocabulary words a typed prefix may expand to


def _words(s: str) -> list[str]:
    return _WORD.findall(institutions.fold(s or ""))


def _deletes(w: str) -> set[str]:
    return {w[:i] + w[i + 1:] for i in range(len(w))}


def _within_one(a: str, b: str) -> bool:
    """Optimal-string-alignment distance <= 1 (insert, delete, substitute, swap)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    i = 0
    while i < min(la, lb) and a[i] == b[i]:
        i += 1
    if la == lb:
        if a[i + 1:] == b[i + 1:]:
            return True
        return i + 1 < la and a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:]
    return a[i + 1:] == b[i:] if la > lb else a[i:] == b[i + 1:]


class _Vocab:
    """Sorted words for prefix lookup; a symmetric-delete table (built on first use) for
    words one edit away."""

    def __init__(self, words: Iterable[str]):
        self.sorted = sorted(set(words))
        self.set = set(self.sorted)
        self._del: dict[str, list[str]] | None = None
        self._lock = threading.Lock()

    def prefixed(self, p: str, cap: int = _PREFIX_CAP) -> list[str]:
        i = bisect.bisect_left(self.sorted, p)
        out: list[str] = []
        while i < len(self.sorted) and self.sorted[i].startswith(p) and len(out) < cap:
            out.append(self.sorted[i])
            i += 1
        return out

    def near(self, w: str) -> set[str]:
        if len(w) < 5:
            return set()
        if self._del is None:
            with self._lock:
                if self._del is None:
                    d: dict[str, list[str]] = defaultdict(list)
                    for v in self.sorted:
                        if len(v) >= 4:
                            for x in _deletes(v):
                                d[x].append(v)
                    self._del = dict(d)
        cands = set(self._del.get(w, ()))
        for x in _deletes(w):
            if x in self.set:
                cands.add(x)
            cands.update(self._del.get(x, ()))
        return {c for c in cands if c != w and _within_one(w, c)}


class _Term:
    """One query word and the vocabulary words it may stand for, with weights:
    exact 1.0, plural / singular 0.95, prefix 0.9, one edit away 0.8."""

    def __init__(self, w: str, vocab: _Vocab, prefix: bool, plural: bool):
        self.w = w
        self.prefix = prefix
        self.alts: dict[str, float] = {}
        if w in vocab.set:
            self.alts[w] = 1.0
        if plural:
            for v in (w + "s", w + "es", w[:-1] if w.endswith("s") and len(w) > 3 else ""):
                if v and v in vocab.set:
                    self.alts.setdefault(v, 0.95)
        self.typos: set[str] = set() if w in vocab.set else vocab.near(w)
        for v in self.typos:
            self.alts.setdefault(v, 0.8)
        self.prefixed: list[str] = vocab.prefixed(w) if prefix else []

    @property
    def corrected(self) -> str | None:
        """The vocabulary word a typo stands for, when the word itself is unknown and no
        known word starts with it."""
        if self.w in self.alts or self.prefixed or not self.typos:
            return None
        return sorted(self.typos)[0]

    def postings_size(self, post: dict[str, list[int]]) -> int:
        n = sum(len(post[v]) for v in self.alts)
        n += sum(len(post[v]) for v in self.prefixed)
        return n

    def candidates(self, post: dict[str, list[int]]) -> set[int]:
        out: set[int] = set()
        for v in self.alts:
            out.update(post[v])
        for v in self.prefixed:
            out.update(post[v])
        return out

    def weight(self, toks) -> float:
        if self.w in toks:
            return 1.0
        best = 0.0
        for t in toks:
            a = self.alts.get(t)
            if a is not None and a > best:
                best = a
            elif self.prefix and best < 0.9 and t.startswith(self.w):
                best = 0.9
        return best


# ── the index ─────────────────────────────────────────────────────────────────

class _Index:
    def __init__(self, dss: list[store.Dataset]):
        t0 = time.time()
        self.dss = dss
        self.ds_of: list[int] = []          # global paper id -> dataset index
        self.j_of: list[int] = []           # global paper id -> paper index in its dataset
        self.tfold: list[str] = []          # folded title, words joined by one space
        self.ttoks: list[frozenset[str]] = []
        tpost: dict[str, list[int]] = defaultdict(list)
        self.names: list[str] = []          # folded full name
        self.ntoks: list[tuple[str, ...]] = []
        self.mentions: list[list[tuple[int, int]]] = []   # name id -> [(paper id, author position)]
        npost: dict[str, list[int]] = defaultdict(list)
        name_id: dict[str, int] = {}
        folded: dict[str, tuple[str, ...]] = {}
        for di, ds in enumerate(dss):
            for j, p in enumerate(ds.papers):
                doc = len(self.ds_of)
                self.ds_of.append(di)
                self.j_of.append(j)
                words = _words(p["t"])
                self.tfold.append(" ".join(words))
                ws = frozenset(words)
                self.ttoks.append(ws)
                for w in ws:
                    tpost[w].append(doc)
                for pos, raw in enumerate(p["au"]):
                    if not raw:
                        continue
                    toks = folded.get(raw)
                    if toks is None:
                        toks = folded[raw] = tuple(_words(raw))
                    if not toks:
                        continue
                    key = " ".join(toks)
                    nid = name_id.get(key)
                    if nid is None:
                        nid = name_id[key] = len(self.names)
                        self.names.append(key)
                        self.ntoks.append(toks)
                        self.mentions.append([])
                        for t in set(toks):
                            npost[t].append(nid)
                    self.mentions[nid].append((doc, pos))
        self.tpost = dict(tpost)
        self.npost = dict(npost)
        self.tvocab = _Vocab(self.tpost)
        self.nvocab = _Vocab(self.npost)
        self.folded_names = folded
        n = max(1, len(self.ds_of))
        self.idf = {w: math.log(n / len(d)) for w, d in self.tpost.items()}
        self.seconds = round(time.time() - t0, 2)
        log.info("conference search index: %d conferences, %d papers, %d author names, %.1fs",
                 len(dss), len(self.ds_of), len(self.names), self.seconds)


_index: _Index | None = None
_index_lock = threading.Lock()


def _datasets() -> list[store.Dataset]:
    out = []
    for key in store.loaded_keys():
        try:
            ds = store.load(key)
        except Exception as exc:  # noqa: BLE001 — one broken dataset must not stop the search
            log.warning("conference %s: cannot load for search (%s)", key, exc)
            continue
        if ds is not None:
            out.append(ds)
    return out


def _same(ix: _Index | None, dss: list[store.Dataset]) -> bool:
    return ix is not None and len(ix.dss) == len(dss) and all(a is b for a, b in zip(ix.dss, dss))


def index() -> _Index:
    """The index over every loaded conference, rebuilt when a dataset was (re)loaded."""
    global _index
    dss = _datasets()
    if _same(_index, dss):
        return _index  # type: ignore[return-value]
    with _index_lock:
        if not _same(_index, dss):
            _index = _Index(dss)
        return _index  # type: ignore[return-value]


def warm() -> None:
    """Load every dataset, build the index and load the embedder (startup thread)."""
    try:
        ix = index()
        ix.tvocab.near("warmup")          # build the typo tables now, not on a user's query
        ix.nvocab.near("warmup")
        if any(ds.emb is not None for ds in ix.dss):
            from services.conferences import embedder

            embedder.conference_embed_query("warm up")
    except Exception as exc:  # noqa: BLE001
        log.warning("conference search warm-up failed: %s", exc)


# ── helpers ───────────────────────────────────────────────────────────────────

def _select(ix: _Index, series: str = "", field: str = "", year_min: int | None = None,
            year_max: int | None = None) -> list[int]:
    """Dataset indices passing the filters. ``series`` and ``field`` take comma lists of
    slugs or names ("neurips,icml", "Vision")."""
    slugs = {s.strip().lower() for s in (series or "").split(",") if s.strip()}
    fields = {f.strip().lower() for f in (field or "").split(",") if f.strip()}
    out = []
    for di, ds in enumerate(ix.dss):
        r = ds.raw
        if slugs and (r.get("slug") or "").lower() not in slugs and (r.get("series") or "").lower() not in slugs:
            continue
        if fields and (r.get("field") or "").lower() not in fields:
            continue
        if year_min and r["year"] < year_min:
            continue
        if year_max and r["year"] > year_max:
            continue
        out.append(di)
    return out


def _conf(ds: store.Dataset) -> dict:
    r = ds.raw
    return {"key": ds.key, "name": r["name"], "series": r["series"], "slug": r.get("slug"),
            "field": r.get("field"), "year": r["year"], "papers": len(ds.papers)}


def _row(ds: store.Dataset, j: int, sim: float | None = None, library: dict | None = None) -> dict:
    row = store._paper_row(ds, j, sim, library)
    row.update({"conf_key": ds.key, "conf_name": ds.raw["name"], "conf_year": ds.raw["year"]})
    return row


def _vectors(ds: store.Dataset, for_counts: bool) -> np.ndarray | None:
    """Title-only vectors when present. Until a dataset has them, its backfill is queued;
    paper search meanwhile uses the title + abstract vectors, topic counts skip it."""
    if ds.temb is not None:
        return ds.temb
    if ds.emb is not None:
        try:
            store.request_title_embeddings(ds.key)
        except Exception:  # noqa: BLE001
            pass
        return None if for_counts else ds.emb
    return None


def _highlight(terms: list[_Term]) -> dict:
    """Folded word forms the client marks in titles or names: every form a query word
    matched (itself, plural, typo neighbours) and the words that match as a prefix."""
    words: set[str] = set()
    prefixes: list[str] = []
    for t in terms:
        words.add(t.w)
        words.update(t.alts)
        if t.prefix:
            prefixes.append(t.w)
    return {"words": sorted(words), "prefixes": prefixes}


def _corrected(ix: _Index, text: str) -> str:
    """The query with each unknown word of five letters or more replaced by the most
    frequent title word one edit away ("difusion protien" -> "diffusion protein"), so
    a typo does not send the embedding elsewhere. Long texts are left alone."""
    words = text.split()
    if len(words) > 24:
        return text
    changed = False
    out = []
    for raw in words:
        ws = _words(raw)
        if len(ws) == 1 and ws[0] not in ix.tvocab.set:
            near = ix.tvocab.near(ws[0])
            if near:
                out.append(max(near, key=lambda v: len(ix.tpost[v])))
                changed = True
                continue
        out.append(raw)
    return " ".join(out) if changed else text


def _embed(text: str) -> np.ndarray | None:
    from services.conferences import embedder

    try:
        # bge-small's tokenizer lowercases anyway; doing it here keeps case irrelevant
        # whatever the model.
        return embedder.conference_embed_query(text.lower())
    except Exception as exc:  # noqa: BLE001
        log.warning("conference search: query embedding failed (%s)", exc)
        return None


# ── papers ────────────────────────────────────────────────────────────────────

def _title_terms(ix: _Index, text: str) -> tuple[list[str], list[str], list[_Term]]:
    words = _words(text)
    content = [w for w in words if w not in _STOP] or words
    terms = [_Term(w, ix.tvocab, prefix=(k == len(content) - 1 and w == words[-1] and len(w) >= 2), plural=True)
             for k, w in enumerate(content)]
    return words, content, terms


def _title_candidates(ix: _Index, allowed: set[int], text: str) -> list[tuple[int, float, float]]:
    """(paper id, tier, coverage) for titles matching the query words. Tiers: 4 the whole
    title, 3 the title starts with the query, 2.5 the query as a phrase, 2 every word,
    1 all but one word (queries of three words or more)."""
    words, content, terms = _title_terms(ix, text)
    if not words:
        return []
    usable = sorted((k for k, t in enumerate(terms) if t.alts or t.prefixed),
                    key=lambda k: terms[k].postings_size(ix.tpost))
    if not usable:
        return []
    need = len(terms) if len(terms) < 3 else len(terms) - 1
    if len(usable) < need:
        return []
    # A paper missing at most one word contains one of the two rarest ones.
    cands: set[int] = set()
    for k in usable[: (1 if need == len(terms) else 2)]:
        cands |= terms[k].candidates(ix.tpost)
    qidf = []
    for t in terms:
        if t.w in ix.idf:
            qidf.append(ix.idf[t.w])
        else:
            alts = [ix.idf[v] for v in t.alts] or [1.0]
            qidf.append(min(alts))
    idf_total = sum(qidf) or 1.0
    qfold = " ".join(words)
    out = []
    for doc in cands:
        if ix.ds_of[doc] not in allowed:
            continue
        ts = ix.ttoks[doc]
        got, cov = 0, 0.0
        for t, w_idf in zip(terms, qidf):
            w = t.weight(ts)
            if w:
                got += 1
                cov += w * w_idf
        if got < need:
            continue
        tf = ix.tfold[doc]
        if tf == qfold:
            tier = 4.0
        elif len(qfold) >= 8 and tf.startswith(qfold):
            tier = 3.0
        elif len(words) >= 2 and f" {qfold} " in f" {tf} ":
            tier = 2.5
        elif got == len(terms):
            tier = 2.0
        else:
            tier = 1.0
        out.append((doc, tier, cov / idf_total))
    return out


def _sims(ix: _Index, allowed: list[int], q: np.ndarray, for_counts: bool) -> dict[int, np.ndarray]:
    out = {}
    for di in allowed:
        m = _vectors(ix.dss[di], for_counts)
        if m is not None:
            out[di] = m @ q
    return out


def search_papers(text: str, limit: int = 20, series: str = "", field: str = "", year_min: int | None = None,
                  year_max: int | None = None, library: dict | None = None, semantic: bool = True) -> dict:
    """Papers across conferences: title matches first (ranked by how completely and how
    exactly the title matches, ties by meaning), then the closest titles by meaning that
    did not match by words."""
    ix = index()
    allowed = _select(ix, series, field, year_min, year_max)
    allowed_set = set(allowed)
    hits = _title_candidates(ix, allowed_set, text)
    corrected = _corrected(ix, text)
    q = _embed(corrected) if semantic and text.strip() else None
    sims = _sims(ix, allowed, q, for_counts=False) if q is not None else {}

    def sim_of(doc: int) -> float | None:
        s = sims.get(ix.ds_of[doc])
        return float(s[ix.j_of[doc]]) if s is not None else None

    hits.sort(key=lambda h: (-h[1], -h[2], -(sim_of(h[0]) or 0.0), len(ix.tfold[h[0]])))
    shown = hits[:limit]
    title_rows = []
    for doc, tier, _cov in shown:
        ds = ix.dss[ix.ds_of[doc]]
        row = _row(ds, ix.j_of[doc], sim_of(doc), library)
        row["title_match"] = "exact" if tier >= 4 else "prefix" if tier >= 3 else "phrase" if tier >= 2.5 \
            else "words" if tier >= 2 else "most words"
        title_rows.append(row)
    semantic_rows = []
    if sims:
        taken = {doc for doc, _, _ in shown}
        pool = []
        for di, s in sims.items():
            top = np.argpartition(-s, min(len(s) - 1, limit + len(taken)))[: limit + len(taken)] if len(s) else []
            for j in top:
                pool.append((float(s[j]), di, int(j)))
        pool.sort(reverse=True)
        base = _doc_base(ix)
        for sim, di, j in pool:
            if base[di] + j in taken:
                continue
            semantic_rows.append(_row(ix.dss[di], j, sim, library))
            if len(semantic_rows) >= limit:
                break
    return {
        "query": text, "title": title_rows, "title_total": len(hits), "semantic": semantic_rows,
        "semantic_ready": bool(sims), "highlight": _highlight(_title_terms(ix, text)[2]),
        "corrected": corrected if corrected.lower() != text.lower() else None,
        "conferences": [_conf(ix.dss[di]) for di in allowed],
    }


def _doc_base(ix: _Index) -> list[int]:
    base, n = [], 0
    for ds in ix.dss:
        base.append(n)
        n += len(ds.papers)
    return base


# ── authors ───────────────────────────────────────────────────────────────────

def _name_terms(ix: _Index, text: str) -> list[_Term]:
    return [_Term(w, ix.nvocab, prefix=True, plural=False) for w in _words(text)]


def _author_matches(ix: _Index, allowed: set[int], text: str) -> list[tuple[int, float, int]]:
    """(name id, score, papers in the selected conferences). Every query word must match a
    word of the name, exactly (1.0), as a prefix (0.9: initials, typing) or one edit away
    (0.8). Score 100: the full name; 90: all words exact; +5: the surname exact."""
    q = _words(text)
    if not q:
        return []
    terms = _name_terms(ix, text)
    usable = [k for k, t in enumerate(terms) if (t.alts or t.prefixed) and len(t.w) >= 2]
    if len(usable) == 0 or any(not (t.alts or t.prefixed) for t in terms):
        return []
    anchor = min(usable, key=lambda k: terms[k].postings_size(ix.npost))
    out = []
    for nid in terms[anchor].candidates(ix.npost):
        toks = ix.ntoks[nid]
        ws = [t.weight(toks) for t in terms]
        if not all(ws):
            continue
        papers = sum(1 for doc, _ in ix.mentions[nid] if ix.ds_of[doc] in allowed)
        if not papers:
            continue
        exact = all(w == 1.0 for w in ws)
        score = 50 + 40 * sum(ws) / len(ws)
        if exact and len(set(q)) == len(set(toks)):
            score = 100.0
        elif any(t.w == toks[-1] for t in terms):
            score += 5
        out.append((nid, round(score, 1), papers))
    out.sort(key=lambda m: (-m[1], -m[2], ix.names[m[0]]))
    return out


def _author_card(ix: _Index, nid: int, score: float, allowed: set[int], library: dict | None,
                 paper_cap: int = 100) -> dict:
    mentions = [(doc, pos) for doc, pos in ix.mentions[nid] if ix.ds_of[doc] in allowed]
    spellings: Counter = Counter()
    insts: dict[str, dict] = {}
    coauthors: set[str] = set()
    # Mentions joined by a shared institution or co-author are likely one person.
    parent = list(range(len(mentions)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    first_with: dict[str, int] = {}
    per_mention_insts: list[list[str]] = []
    for m, (doc, pos) in enumerate(mentions):
        ds = ix.dss[ix.ds_of[doc]]
        p = ds.papers[ix.j_of[doc]]
        spellings[p["au"][pos]] += 1
        ids = p["ai"][pos] if pos < len(p["ai"]) else []
        names = [ds.insts[i]["n"] for i in ids]
        per_mention_insts.append(names)
        links = []
        for i in ids:
            mk = institutions.merge_key(ds.insts[i]["n"])
            row = insts.setdefault(mk, {"name": ds.insts[i]["n"], "sector": ds.insts[i]["s"], "papers": 0})
            row["papers"] += 1
            links.append("i:" + mk)
        for k, other in enumerate(p["au"]):
            if k == pos or not other:
                continue
            f = " ".join(ix.folded_names.get(other) or _words(other))
            if f and f != ix.names[nid]:
                coauthors.add(f)
                links.append("a:" + f)
        for token in links:
            if token in first_with:
                ra, rb = find(m), find(first_with[token])
                if ra != rb:
                    parent[ra] = rb
            else:
                first_with[token] = m
    groups: dict[int, list[int]] = defaultdict(list)
    for m in range(len(mentions)):
        groups[find(m)].append(m)
    identities = []
    for ms in sorted(groups.values(), key=len, reverse=True):
        c = Counter(n for m in ms for n in per_mention_insts[m])
        identities.append({"papers": len(ms), "institutions": [n for n, _ in c.most_common(4)],
                           "conferences": sorted({ix.dss[ix.ds_of[mentions[m][0]]].key for m in ms})})
    by_conf: dict[int, list[dict]] = defaultdict(list)
    for m, (doc, pos) in enumerate(sorted(mentions)[:paper_cap]):
        di = ix.ds_of[doc]
        ds = ix.dss[di]
        j = ix.j_of[doc]
        row = _row(ds, j, library=library)
        p = ds.papers[j]
        ids = p["ai"][pos] if pos < len(p["ai"]) else []
        row["author_institutions"] = [ds.insts[i]["n"] for i in ids]
        row["author_position"] = pos + 1
        by_conf[di].append(row)
    confs = sorted(by_conf, key=lambda di: (-ix.dss[di].raw["year"], ix.dss[di].raw["name"]))
    return {
        "name": spellings.most_common(1)[0][0] if spellings else ix.names[nid],
        "folded": ix.names[nid], "score": score, "papers": len(mentions),
        "conference_count": len({ix.ds_of[doc] for doc, _ in mentions}),
        "coauthors": len(coauthors),
        "institutions": sorted(insts.values(), key=lambda r: -r["papers"])[:12],
        "identities": identities if len(identities) > 1 else [],
        "conferences": [{**_conf(ix.dss[di]), "papers_by_author": by_conf[di]} for di in confs],
        "more_papers": max(0, len(mentions) - paper_cap),
    }


def search_authors(text: str, limit: int = 20, series: str = "", field: str = "", year_min: int | None = None,
                   year_max: int | None = None, library: dict | None = None) -> dict:
    ix = index()
    allowed = set(_select(ix, series, field, year_min, year_max))
    matches = _author_matches(ix, allowed, text)
    terms = _name_terms(ix, text)
    corrected = None
    if matches and any(t.corrected for t in terms):
        corrected = _author_card(ix, matches[0][0], matches[0][1], allowed, None, paper_cap=0)["name"]
    return {
        "query": text, "total": len(matches), "highlight": _highlight(terms), "corrected": corrected,
        "authors": [_author_card(ix, nid, score, allowed, library) for nid, score, _ in matches[:limit]],
    }


# ── both at once (the search box) ─────────────────────────────────────────────

def search(text: str, kind: str = "all", limit: int = 20, series: str = "", field: str = "",
           year_min: int | None = None, year_max: int | None = None, library: dict | None = None) -> dict:
    """``kind`` = paper, author or all (both). ``suggested`` says which tab
    the search box should open: topic for a pasted abstract, author for a name that
    matches an author and no title, paper otherwise."""
    text = (text or "").strip()[:500]
    t0 = time.time()
    out: dict = {"query": text, "kind": kind}
    filt = dict(series=series, field=field, year_min=year_min, year_max=year_max)
    if kind in ("all", "author"):
        out["authors"] = search_authors(text, limit=limit, library=library, **filt)
    if kind in ("all", "paper"):
        out["papers"] = search_papers(text, limit=limit, library=library, **filt)
    words = text.split()
    best_author = out["authors"]["authors"][0]["score"] if out.get("authors", {}).get("authors") else 0
    strong_title = any(r["title_match"] in ("exact", "prefix", "phrase") for r in out.get("papers", {}).get("title", []))
    any_title = bool(out.get("papers", {}).get("title"))
    if len(words) > 12:
        out["suggested"] = "topic"
    elif best_author >= 90 and not strong_title:
        out["suggested"] = "author"
    elif best_author and not any_title and kind != "paper":
        out["suggested"] = "author"
    else:
        out["suggested"] = "paper"
    ix = index()
    out["conferences"] = [_conf(ix.dss[di]) for di in _select(ix, **filt)]
    out["ms"] = round((time.time() - t0) * 1000)
    return out


# ── topic across conferences ──────────────────────────────────────────────────

def _merge_keys(ds: store.Dataset) -> dict[str, int]:
    mk = getattr(ds, "_merge_keys", None)
    if mk is None:
        mk = {}
        for i, r in enumerate(ds.insts):
            mk.setdefault(institutions.merge_key(r["n"]), i)
        ds._merge_keys = mk  # type: ignore[attr-defined]
    return mk


def topic(text: str, k: int = 300, series: str = "", field: str = "", year_min: int | None = None,
          year_max: int | None = None, library: dict | None = None, paper_top: int = 25, per_conference: int = 3,
          sector_top: int = 12) -> dict:
    """Where a topic is published. The k papers closest to the query are pooled over all
    selected conferences (title-only vectors, so every conference is measured the same
    way); the k-th similarity is in effect one threshold for all of them. Per conference:
    how many pooled papers it holds, per 1,000 of its papers; per series with several
    years: that rate per year; pooled over everything: institutions, areas, closest papers."""
    text = text.strip()
    k = max(10, min(int(k), 2000))
    ix = index()
    allowed = _select(ix, series, field, year_min, year_max)
    corrected = _corrected(ix, text)
    q = _embed(corrected)
    if q is None:
        raise RuntimeError("The embedding model is not available, so topic search cannot run.")
    sims = _sims(ix, allowed, q, for_counts=True)
    skipped = [{**_conf(ix.dss[di]),
                "reason": "not indexed yet" if ix.dss[di].emb is None else "title index is being built"}
               for di in allowed if di not in sims]
    if not sims:
        return {"query": text, "corrected": None, "k": 0, "threshold": None, "total": 0, "conferences": [], "skipped": skipped,
                "trend": [], "areas": [], "with_industry": 0, "with_institution": 0,
                "academia": [], "industry": [], "papers": []}
    allsims = np.concatenate([sims[di] for di in sims])
    kk = min(k, len(allsims))
    thr = float(np.partition(allsims, len(allsims) - kk)[len(allsims) - kk])

    pool: list[tuple[float, int, int]] = []
    confs = []
    for di, s in sims.items():
        ds = ix.dss[di]
        js = np.nonzero(s >= thr)[0]
        for j in js:
            pool.append((float(s[j]), di, int(j)))
        n_top = min(per_conference, len(s))
        top = np.argsort(-s)[:n_top]
        confs.append({**_conf(ds), "count": int(len(js)), "per_1k": round(1000 * len(js) / max(1, len(s)), 2),
                      "best": round(float(s.max()), 4) if len(s) else None,
                      "top": [_row(ds, int(j), float(s[j]), library) for j in top]})
    pool.sort(reverse=True)
    pool = pool[:max(kk, 1) + 50]                     # ties at the threshold: a few extra at most
    confs.sort(key=lambda c: (-c["per_1k"], -c["count"], c["name"]))

    by_series: dict[str, list[dict]] = defaultdict(list)
    for c in confs:
        by_series[c["slug"] or c["series"]].append(c)
    trend = []
    for slug, cs in by_series.items():
        if len(cs) < 2:
            continue
        cs = sorted(cs, key=lambda c: c["year"])
        trend.append({"series": cs[0]["series"], "slug": slug,
                      "points": [{"year": c["year"], "key": c["key"], "count": c["count"], "per_1k": c["per_1k"],
                                  "papers": c["papers"]} for c in cs]})
    trend.sort(key=lambda t: -sum(p["count"] for p in t["points"]))

    inst: dict[str, dict] = {}
    area_counts = [0] * len(area_mod.AREAS)
    with_ind = with_inst = 0
    for sim, di, j in pool:
        ds = ix.dss[di]
        p = ds.papers[j]
        if p["ar"] >= 0:
            area_counts[p["ar"]] += 1
        if p["i"]:
            with_inst += 1
        if any(ds.insts[i]["s"] == "I" for i in p["i"]):
            with_ind += 1
        for i in p["i"]:
            r = ds.insts[i]
            mk = institutions.merge_key(r["n"])
            row = inst.get(mk)
            if row is None:
                row = inst[mk] = {"name": r["n"], "sector": r["s"], "count": 0, "wsum": 0.0, "by": Counter(),
                                  "slugs": {}}
            row["count"] += 1
            row["wsum"] += sim
            row["by"][ds.key] += 1
            row["slugs"][ds.key] = r["slug"]
    ranked = sorted(inst.items(), key=lambda kv: (-kv[1]["count"], -kv[1]["wsum"]))

    def side(sec: str) -> list[dict]:
        rows = []
        for mk, r in ranked:
            if r["sector"] != sec:
                continue
            total = 0
            for di in sims:
                i = _merge_keys(ix.dss[di]).get(mk)
                if i is not None:
                    total += ix.dss[di].insts[i]["p"]
            rows.append({"name": r["name"], "sector": sec, "count": r["count"], "papers": total,
                         "of_own": round(r["count"] / max(1, total), 3),
                         "conferences": [{"key": key, "count": c, "slug": r["slugs"][key]}
                                         for key, c in r["by"].most_common()]})
            if len(rows) >= sector_top:
                break
        return rows

    return {
        "query": text, "corrected": corrected if corrected.lower() != text.lower() else None,
        "k": len(pool), "threshold": round(thr, 4), "total": int(len(allsims)),
        "conferences": confs, "skipped": skipped, "trend": trend,
        "areas": store._area_list(area_counts), "with_industry": with_ind, "with_institution": with_inst,
        "academia": side("A"), "industry": side("I"),
        "papers": [_row(ix.dss[di], j, sim, library) for sim, di, j in pool[:paper_top]],
    }
