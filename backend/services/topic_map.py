"""Topic map: a 2D layout of every embedded paper, clustered and labelled.

The embeddings are the semantic-search index (``emb.npy`` / ``meta.json`` written by
services.library_search.semantic). The layout is a numpy-only UMAP-style embedding
(kNN graph -> fuzzy weights -> stochastic attract/repel optimisation). Nothing here computes
on the request path: ``get_topic_map`` reads cached state and, if there is no layout yet or
the embedding file changed, starts a background daemon thread.

Pure functions (layout, clustering, labelling, week bucketing, payload assembly) take plain
arrays so they can be tested without a database.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import multiprocessing
import os
import re
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- constants

CLUSTER_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
# slots beyond the first 8 (only used when a user asks for more than 8 clusters)
CLUSTER_COLORS_EXTRA = ["#7a5230", "#14a3b8", "#a64ca6", "#7d8c1f", "#c2185b", "#3f51b5", "#8d6e63", "#455a64"]
MIN_CLUSTERS, MAX_CLUSTERS = 2, 16
PROJECT_OFFSET = 3
SYSTEM_TAG = "from-references"
ATTR_TTL = 120.0
MIN_INTERVAL_DEFAULT = 1800.0   # seconds between layout rebuilds (TOPIC_MAP_MIN_INTERVAL)
BIG_CHANGE = 0.05              # a paper-count change above this rebuilds regardless of the interval
FAIL_BACKOFF = 60.0
KNN_K = 15
_A, _B = 1.577, 0.895          # UMAP curve for min_dist ~0.1, spread 1

# --------------------------------------------------------------------------- layout


def _pca2(X: np.ndarray) -> np.ndarray:
    n = X.shape[0]
    if n == 1:
        return np.zeros((1, 2))
    Xc = (X - X.mean(axis=0, keepdims=True)).astype(np.float64)
    try:
        vals, vecs = np.linalg.eigh(Xc.T @ Xc)          # d x d: much cheaper than an SVD of (n, d)
    except np.linalg.LinAlgError:
        return np.zeros((n, 2))
    out = np.zeros((n, 2))
    top = vecs[:, ::-1][:, :2]
    out[:, : top.shape[1]] = Xc @ top
    return out


def _knn(X: np.ndarray, k: int, chunk: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Cosine kNN of unit vectors. Returns (idx (n,k), dist (n,k)) sorted by distance."""
    n = X.shape[0]
    idx = np.empty((n, k), dtype=np.int32)
    dist = np.empty((n, k), dtype=np.float32)
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        S = X[s:e] @ X.T
        S[np.arange(e - s), np.arange(s, e)] = -np.inf
        part = np.argpartition(-S, k - 1, axis=1)[:, :k]
        sims = np.take_along_axis(S, part, axis=1)
        order = np.argsort(-sims, axis=1, kind="stable")
        idx[s:e] = np.take_along_axis(part, order, axis=1)
        dist[s:e] = 1.0 - np.take_along_axis(sims, order, axis=1)
    np.clip(dist, 0.0, None, out=dist)
    return idx, dist


def _fuzzy_graph(idx: np.ndarray, dist: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """UMAP fuzzy simplicial set, symmetrised with a + b - ab. Returns (u, v, w) with u<v."""
    n, k = idx.shape
    target = math.log2(k)
    d = dist.astype(np.float64)
    pos = np.where(d > 0, d, np.inf)
    rho = pos.min(axis=1)
    rho[~np.isfinite(rho)] = 0.0
    dd = np.maximum(d - rho[:, None], 0.0)
    lo = np.full(n, 1e-6)
    hi = np.full(n, 64.0)
    for _ in range(48):                       # bisection in log space
        mid = np.sqrt(lo * hi)
        f = np.exp(-dd / mid[:, None]).sum(axis=1)
        big = f > target
        hi = np.where(big, mid, hi)
        lo = np.where(big, lo, mid)
    sigma = np.sqrt(lo * hi)
    w = np.exp(-dd / sigma[:, None])
    rows = np.repeat(np.arange(n, dtype=np.int64), k)
    cols = idx.reshape(-1).astype(np.int64)
    w = w.reshape(-1)
    a, b = np.minimum(rows, cols), np.maximum(rows, cols)
    key = a * n + b
    uniq, inv = np.unique(key, return_inverse=True)
    s1 = np.bincount(inv, weights=w)
    s2 = np.bincount(inv, weights=w * w)
    wsym = s1 - (s1 * s1 - s2) / 2.0           # one entry: w, two entries: a+b-ab
    u, v = uniq // n, uniq % n
    keep = wsym > 1e-4
    return u[keep].astype(np.int64), v[keep].astype(np.int64), wsym[keep]


def _optimize(Y: np.ndarray, u: np.ndarray, v: np.ndarray, w: np.ndarray, epochs: int,
              rng: np.random.Generator, lr0: float = 1.0, neg: int = 5) -> np.ndarray:
    n = Y.shape[0]
    if len(w) == 0:
        return Y
    p = w / w.max()
    a, b = _A, _B
    for ep in range(epochs):
        lr = lr0 * (1.0 - ep / epochs)
        sel = np.nonzero(rng.random(len(p)) < p)[0]
        if len(sel) == 0:
            continue
        hu, hv = u[sel], v[sel]
        diff = Y[hu] - Y[hv]
        d2 = (diff * diff).sum(axis=1)
        coef = np.zeros_like(d2)
        nz = d2 > 0
        coef[nz] = (-2.0 * a * b * d2[nz] ** (b - 1.0)) / (1.0 + a * d2[nz] ** b)
        g = np.clip(coef[:, None] * diff, -4.0, 4.0)
        # negative samples for the head of every sampled edge
        m = len(sel)
        neg_idx = rng.integers(0, n, size=(m, neg))
        nd = Y[hu][:, None, :] - Y[neg_idx]                      # (m, neg, 2)
        nd2 = (nd * nd).sum(axis=2)
        ncoef = (2.0 * b) / ((0.001 + nd2) * (1.0 + a * nd2 ** b))
        ncoef[neg_idx == hu[:, None]] = 0.0
        ng = np.clip(ncoef[:, :, None] * nd, -4.0, 4.0).sum(axis=1)   # (m, 2)
        delta = np.zeros_like(Y)
        for c in (0, 1):
            delta[:, c] = (np.bincount(hu, weights=g[:, c] + ng[:, c], minlength=n)
                           - np.bincount(hv, weights=g[:, c], minlength=n))
        np.clip(delta, -4.0, 4.0, out=delta)
        Y = Y + lr * delta
    return Y


def normalize_xy(Y: np.ndarray) -> np.ndarray:
    """Robust normalisation to [0,1]: clip at the 0.5/99.5 percentiles, keep aspect ratio, centre."""
    n = len(Y)
    if n == 0:
        return np.zeros((0, 2))
    Y = np.asarray(Y, dtype=np.float64)
    if n < 20:
        lo, hi = Y.min(axis=0), Y.max(axis=0)
    else:
        lo, hi = np.percentile(Y, 0.5, axis=0), np.percentile(Y, 99.5, axis=0)
    span = float(max(hi[0] - lo[0], hi[1] - lo[1]))
    if not np.isfinite(span) or span <= 1e-12:
        return np.full((n, 2), 0.5)
    centre = (lo + hi) / 2.0
    out = (np.clip(Y, lo, hi) - centre) / span + 0.5
    return np.round(np.clip(out, 0.0, 1.0), 4)


def compute_layout(X: np.ndarray, seed: int = 0, init: np.ndarray | None = None,
                   epochs: int | None = None, timings: dict | None = None) -> np.ndarray:
    """Numpy-only UMAP-style 2D layout of unit vectors X (n, d) -> normalised (n, 2) in [0,1]."""
    t0 = time.perf_counter()
    X = np.ascontiguousarray(X, dtype=np.float32)
    n = X.shape[0]
    tm = timings if timings is not None else {}
    if n == 0:
        return np.zeros((0, 2))
    if n == 1:
        return np.full((1, 2), 0.5)
    if n < 20:
        P = _pca2(X)
        if np.ptp(P) < 1e-9:                    # identical vectors: a small circle
            ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
            P = np.stack([np.cos(ang), np.sin(ang)], axis=1)
        tm["total"] = time.perf_counter() - t0
        return normalize_xy(P)
    rng = np.random.default_rng(seed)
    k = min(KNN_K, n - 1)
    t = time.perf_counter()
    idx, dist = _knn(X, k)
    tm["knn"] = time.perf_counter() - t
    t = time.perf_counter()
    u, v, w = _fuzzy_graph(idx, dist)
    tm["weights"] = time.perf_counter() - t
    seeded = init is not None and np.shape(init) == (n, 2)
    base = np.asarray(init, dtype=np.float64) if seeded else _pca2(X.astype(np.float64))
    base = base - base.mean(axis=0, keepdims=True)
    scale = float(np.abs(base).max())
    base = base * (10.0 / scale) if scale > 1e-12 else base
    Y = base + rng.normal(scale=1e-3 if seeded else 1e-2, size=(n, 2))   # separates duplicates
    ep = epochs if epochs is not None else (60 if seeded else 200)
    t = time.perf_counter()
    Y = _optimize(Y, u, v, w, ep, rng, lr0=0.4 if seeded else 1.0)
    tm["optimize"] = time.perf_counter() - t
    Y = np.nan_to_num(Y, nan=0.0, posinf=0.0, neginf=0.0)
    tm["total"] = time.perf_counter() - t0
    return normalize_xy(Y)


# --------------------------------------------------------------------------- clustering


def cluster_count(n: int) -> int:
    return int(min(len(CLUSTER_COLORS), max(3, round(math.sqrt(max(n, 0)) / 5))))


def cluster(xy: np.ndarray, k: int | None = None, seed: int = 0) -> np.ndarray:
    """Deterministic k-means++ on the 2D layout; labels ordered by cluster size (0 = biggest)."""
    n = len(xy)
    if n == 0:
        return np.zeros(0, dtype=np.int32)
    k = cluster_count(n) if k is None else k
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    xy = np.asarray(xy, dtype=np.float64)
    centres = [xy[int(rng.integers(n))]]
    d2 = ((xy - centres[0]) ** 2).sum(axis=1)
    for _ in range(1, k):
        tot = d2.sum()
        if tot <= 0:
            nxt = int(rng.integers(n))
        else:
            nxt = int(rng.choice(n, p=d2 / tot))
        centres.append(xy[nxt])
        d2 = np.minimum(d2, ((xy - xy[nxt]) ** 2).sum(axis=1))
    C = np.array(centres)
    lab = np.zeros(n, dtype=np.int32)
    for _ in range(40):
        dm = ((xy[:, None, :] - C[None, :, :]) ** 2).sum(axis=2) if n * k < 4_000_000 else \
            np.stack([((xy - c) ** 2).sum(axis=1) for c in C], axis=1)
        new = dm.argmin(axis=1).astype(np.int32)
        for j in range(k):
            m = new == j
            if m.any():
                C[j] = xy[m].mean(axis=0)
        if np.array_equal(new, lab):
            break
        lab = new
    sizes = np.bincount(lab, minlength=k)
    order = np.argsort(-sizes, kind="stable")
    remap = np.empty(k, dtype=np.int32)
    remap[order] = np.arange(k, dtype=np.int32)
    return remap[lab]


# --------------------------------------------------------------------------- labels

_STOP = set("""a about above across after again against all almost also although always am among an and any are as at be
because been before being between both but by can could did do does doing done down during each either else enough even
ever every for from further had has have having he her here hers him his how however i if in into is it its itself just
like made make many may me might more most much must my no nor not of off often on once one only onto or other our out
over own per rather same several she should since so some such than that the their them then there these they this those
through thus to too toward towards under until up upon us use used using via was we were what when where whether which
while who whom whose why will with within without would yet you your""".split())
_STOP |= set("""approach approaches analysis based case data effect effects efficient evaluation framework improving improved
method methods model models new novel paper performance results study studies system systems task tasks towards
technique techniques unified towards understanding toward learning large scale simple towards via better
beyond problem problems network networks end""".split())
# "learning", "model(s)", "large", "network(s)" are kept out of single-word labels only; see _terms()
_WEAK = {"learning", "model", "models", "large", "network", "networks", "data", "systems", "system", "based"}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")


_AUTHOR_LIST = re.compile(r"\b[A-Z][A-Za-z\-]+ [A-Z]{1,3}\b\s*(?:,|and\b|\()")


def looks_like_author_list(title: str) -> bool:
    """Reference stubs whose 'title' is really 'Smith J, Doe AB, and Roe C (2020)'."""
    t = title or ""
    if re.search(r"\((?:19|20)\d\d\)\s*$", t) or len(_AUTHOR_LIST.findall(t)) >= 2:
        return True
    chunks = [c.strip() for c in re.split(r",|&|\band\b", t) if c.strip()]
    if len(chunks) < 3:
        return False
    namey = sum(1 for c in chunks if len(c.split()) <= 4 and all(w[:1].isupper() for w in c.split()))
    return namey >= 0.7 * len(chunks)


_STATEMENT = re.compile(r"^\s*(?:competing interests?|conflicts? of interests?|declaration|acknowledge?ments?|funding|"
                        r"author contributions?|data availability|supplementary|correspondence|"
                        r"this (?:work|research|study) was|all rights reserved|copyright|available at|accessed)\b", re.I)
_ETAL = re.compile(r"\bet\.? ?al\b\.?[\s,.)]*$|\bet\.? ?al\b\.?\s*(?:\(|\d{4}|,)", re.I)
_SURNAME_INIT = re.compile(r"\b[A-Z][a-zà-ÿ'\-]+,? (?:[A-Z]\.?-?){1,4}(?=\s*[,.&;:(]|\s+and\b|\s*$)")
_FULLNAME = re.compile(r"^(?:[A-ZÀ-Ý][\w'\-.]+\s+){1,3}[A-ZÀ-Ý][\w'\-.]+$")


def junk_title(title: str | None) -> bool:
    """True for strings that are not paper titles: author lists ('Zhan, F. et al'), statements
    ('Competing interest statement: ...'), institutions or fragments (a single word)."""
    t = re.sub(r"\s+", " ", title or "").strip()
    if len(t) < 6 or len(t.split()) < 2:
        return True
    if _STATEMENT.match(t) or _ETAL.search(t) or looks_like_author_list(t):
        return True
    if len(_SURNAME_INIT.findall(t)) >= 2:
        return True
    chunks = [c.strip() for c in re.split(r",|&|\band\b", t) if c.strip()]
    if len(chunks) >= 3 and all(_FULLNAME.match(c) and not any(w.lower() in _STOP for w in c.split()) for c in chunks):
        return True
    return False


# stop words that may still close a bigram: "language models", "machine learning", "neural networks"
_BI_TAIL = {"model", "models", "learning", "network", "networks", "systems", "analysis"}


def _terms(title: str) -> tuple[list[str], list[str]]:
    if looks_like_author_list(title):
        return [], []
    toks = _TOKEN.findall(title or "")
    keys = [t.lower().strip("-") for t in toks]
    uni, bi = [], []
    prev = None
    for key in keys:
        if key in _STOP or len(key) < 3 or key.isdigit():
            if key in _BI_TAIL and prev is not None:
                bi.append(prev + " " + key)
            prev = None
            continue
        if key not in _WEAK:
            uni.append(key)
        if prev is not None:
            bi.append(prev + " " + key)
        prev = key
    return uni, bi


def _title_case(term: str, upper: set[str]) -> str:
    return " ".join(w.upper() if w in upper else w.capitalize() for w in term.split())


def _title_terms(members: list[int], titles: list[str], df_uni: Counter, df_bi: Counter, n_all: int,
                 upper: set[str], limit: int = 6) -> list[str]:
    cu, cb = Counter(), Counter()
    for i in members:
        uni, bi = _terms(titles[i])
        cu.update(set(uni))
        cb.update(set(bi))
    size = max(1, len(members))
    cands: list[tuple[float, str]] = []
    min_count = max(3, int(0.02 * size))
    for t, c in cb.items():
        if c >= min_count:
            cands.append((1.35 * (c / size) * math.log(n_all / (1 + df_bi[t])) + 1.0, t))  # bigrams preferred
    for t, c in cu.items():
        if c >= min_count:
            cands.append(((c / size) * math.log(n_all / (1 + df_uni[t])), t))
    cands.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    for _, t in cands:
        if any(t in o.split() or o in t for o in out):
            continue
        out.append(t)
        if len(out) >= limit:
            break
    return [_title_case(t, upper) for t in out]


MIN_ATTR_COVERAGE = 0.10     # a topic / tag must cover this share of the cluster to be a label
MUTED_SHARE = 0.5            # a cluster with this share of junk titles is "Unparsed references"
MUTED_LABEL = "Unparsed references"
MUTED_COLOR = "#b4b2a9"


def _stem_eq(a: str, b: str) -> bool:
    a, b = a.split()[-1], b.split()[-1]
    return a[:5] == b[:5]


def _display(kind: str, x: str, upper: set[str]) -> str:
    if kind == "tag":
        return x.replace("-", " ").replace("_", " ").title()
    return x if kind == "topic" else _title_case(x, upper)


def _compose_label(cands: list[tuple[float, str, str]], used: set[str], upper: set[str]) -> str | None:
    """Best candidate; a lone word grows into a bigram that contains it (diffusion -> diffusion models)
    or pairs with a clearly strong second term (Image & Video)."""
    ok = [(s, kd, x) for s, kd, x in cands if _display(kd, x, upper).lower() not in used]
    if not ok:
        return None
    s0, k0, x0 = ok[0]
    if k0 in ("topic", "tag", "bigram"):
        return _display(k0, x0, upper)
    grown = next((c for c in ok if c[1] == "bigram" and x0 in c[2].split() and c[0] >= 0.6 * s0), None)
    if grown:
        return _display("bigram", grown[2], upper)
    for s, kd, x in ok[1:]:
        if s < 0.45 * s0:
            break
        if kd == "word" and not _stem_eq(x, x0) and x not in x0 and x0 not in x:
            return f"{_display('word', x0, upper)} & {_display('word', x, upper)}"
    return _display(k0, x0, upper)


def label_clusters_info(assign: np.ndarray, k: int, titles: list[str], topics: list[list[str]],
                        tags: list[list[str]], include: np.ndarray | None = None, top: int = 5) -> dict:
    """Label every cluster by what the bulk of its papers are about.

    Candidates are topics, tags, title bigrams and title unigrams. Each is scored by coverage
    (share of the cluster's papers carrying it) x distinctiveness (share of all papers carrying it
    that sit in this cluster); topics and tags must cover >= 10 % of the cluster's members (not
    just of the members that have one). Junk titles (author lists, statements) carry no terms.
    ``include`` (bool per paper) restricts the statistics to those papers: used for the public
    label set that must not be derived from hidden papers.

    Returns {"labels": [...], "muted": [...], "candidates": [[(score, kind, name), ...top] per cluster]}.
    """
    n_total = len(assign)
    inc = np.ones(n_total, dtype=bool) if include is None else np.asarray(include, dtype=bool)
    n = int(inc.sum())
    members = [np.nonzero((assign == j) & inc)[0].tolist() for j in range(k)]
    junk = [junk_title(titles[i]) if inc[i] else True for i in range(n_total)]
    tag_df = Counter(t for i in range(n_total) if inc[i] for t in set(tags[i]))
    banned = {t for t in tag_df if is_system_tag(t)} | {t for t, c in tag_df.items() if c > 0.4 * max(1, n)}
    topic_df = Counter(t for i in range(n_total) if inc[i] for t in set(topics[i]))
    topic_banned = {t for t, c in topic_df.items() if c > 0.4 * max(1, n)}
    df_uni, df_bi = Counter(), Counter()
    terms_of: dict[int, tuple[list[str], list[str]]] = {}
    seen_upper, seen_total = Counter(), Counter()
    for i in range(n_total):
        if not inc[i] or junk[i]:
            continue
        uni, bi = _terms(titles[i])
        terms_of[i] = (uni, bi)
        df_uni.update(set(uni))
        df_bi.update(set(bi))
        for tok in _TOKEN.findall(titles[i] or ""):
            low = tok.lower().strip("-")
            seen_total[low] += 1
            if tok.isupper() and len(tok) >= 2:
                seen_upper[low] += 1
    upper = {t for t, c in seen_upper.items() if c * 2 > seen_total[t]}

    per_cluster: list[list[tuple[float, str, str]]] = []
    muted = []
    for j in range(k):
        mem = members[j]
        size = max(1, len(mem))
        muted.append(bool(mem) and sum(junk[i] for i in mem) >= MUTED_SHARE * len(mem))
        cands: list[tuple[float, str, str]] = []
        ct, cg, cu, cb = Counter(), Counter(), Counter(), Counter()
        for i in mem:
            ct.update(set(topics[i]) - topic_banned)
            cg.update(set(tags[i]) - banned)
            if i in terms_of:
                cu.update(set(terms_of[i][0]))
                cb.update(set(terms_of[i][1]))
        for kind, cnt, dfc, weight in (("topic", ct, topic_df, 1.0), ("tag", cg, tag_df, 0.9)):
            for x, c in cnt.items():
                if c >= 3 and c >= MIN_ATTR_COVERAGE * size:
                    cands.append((weight * (c / size) * (c / dfc[x]), kind, x))
        min_count = max(3, int(0.02 * size))
        for kind, cnt, dfc, weight in (("bigram", cb, df_bi, 1.3), ("word", cu, df_uni, 1.0)):
            for x, c in cnt.items():
                if c >= min_count:
                    cands.append((weight * (c / size) * (c / dfc[x]), kind, x))
        cands.sort(key=lambda t: (-t[0], t[2]))
        per_cluster.append(cands)

    used: set[str] = set()
    out: dict[int, str] = {}
    for j in sorted(range(k), key=lambda j: -len(members[j])):
        if muted[j]:
            out[j] = MUTED_LABEL
            used.add(MUTED_LABEL.lower())
            continue
        lab = _compose_label(per_cluster[j], used, upper)
        if lab is None:
            lab = f"Cluster {j + 1}"
        used.add(lab.lower())
        out[j] = lab
    return {"labels": [out[j] for j in range(k)], "muted": muted,
            "candidates": [[(round(s, 3), kd, x) for s, kd, x in c[:top]] for c in per_cluster]}


def label_clusters(assign: np.ndarray, k: int, titles: list[str], topics: list[list[str]],
                   tags: list[list[str]]) -> list[str]:
    """Unique label per cluster (see label_clusters_info)."""
    return label_clusters_info(assign, k, titles, topics, tags)["labels"]


# --------------------------------------------------------------------------- dashboard helpers


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def parse_ts(s) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def week_buckets(created: list, now: datetime | None = None, weeks: int = 12) -> list[dict]:
    """Exactly `weeks` ISO weeks (Monday start), oldest first, zero-filled; the last is this week."""
    now = now or datetime.now(timezone.utc)
    this = monday_of(now.date())
    starts = [this - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]
    counts = {s: 0 for s in starts}
    for c in created:
        dt = c if isinstance(c, datetime) else parse_ts(c)
        if dt is None:
            continue
        m = monday_of(dt.astimezone(timezone.utc).date())
        if m in counts:
            counts[m] += 1
    return [{"week_start": s.isoformat(), "count": counts[s]} for s in starts]


def is_system_tag(name: str) -> bool:
    return name == SYSTEM_TAG or name.startswith("from-") or name == "pdf-upload"


# --------------------------------------------------------------------------- colours / payload


def project_colors(project_ids: list[str]) -> dict[str, str]:
    """Stable colour per project by sorted id order, offset so the first is not cluster 0's blue."""
    return {pid: CLUSTER_COLORS[(i + PROJECT_OFFSET) % len(CLUSTER_COLORS)]
            for i, pid in enumerate(sorted(project_ids))}


def _jitter(pid: str, scale: float = 0.01) -> tuple[float, float]:
    h = hashlib.md5(pid.encode()).digest()
    return ((h[0] / 255 - 0.5) * 2 * scale, (h[1] / 255 - 0.5) * 2 * scale)


def clamp_clusters(k: int) -> int:
    return max(MIN_CLUSTERS, min(MAX_CLUSTERS, int(k)))


def derive(layout: dict, attrs: dict, k: int | None = None) -> dict:
    """Join layout and attributes: places papers missing from the embedding file, clusters, labels.

    Returns arrays aligned by point: ids, xy (n,2), assign, plus clusters and project meta.
    """
    pos = {pid: (x, y) for pid, x, y in zip(layout["ids"], layout["x"], layout["y"])}
    papers = attrs["papers"]
    ids = [p["id"] for p in papers if p["id"] in pos]
    placed = {p["id"]: p for p in papers if p["id"] in pos}
    xy = np.array([pos[i] for i in ids], dtype=np.float64).reshape(-1, 2)
    informative = lambda p: [("t", t) for t in p.get("topics", [])] + \
        [("g", g) for g in p.get("tags", []) if g != SYSTEM_TAG and not is_system_tag(g)]
    # papers in the graph but absent from the embedding file: mean of papers sharing tags/topics
    missing = [p for p in papers if p["id"] not in pos]
    miss_ids, miss_xy = [], []
    if missing:
        acc: dict = {}
        for i, pid in enumerate(ids):
            for key in informative(placed[pid]):
                s = acc.setdefault(key, [0.0, 0.0, 0])
                s[0] += xy[i, 0]; s[1] += xy[i, 1]; s[2] += 1
        for p in missing:
            sx = sy = cnt = 0.0
            for key in informative(p):
                a = acc.get(key)
                if a and a[2] < 0.4 * max(1, len(ids)):
                    sx += a[0]; sy += a[1]; cnt += a[2]
            if cnt:
                jx, jy = _jitter(p["id"])
                miss_ids.append(p["id"])
                miss_xy.append((min(1, max(0, sx / cnt + jx)), min(1, max(0, sy / cnt + jy))))
    n_emb = len(ids)
    all_ids = ids + miss_ids
    all_xy = np.vstack([xy, np.array(miss_xy, dtype=np.float64).reshape(-1, 2)]) if miss_ids else xy
    by_id = {**placed, **{p["id"]: p for p in missing}}
    k = cluster_count(n_emb) if k is None else clamp_clusters(k)
    assign = cluster(xy, k) if n_emb else np.zeros(0, dtype=np.int32)
    kk = int(assign.max()) + 1 if n_emb else 0
    if miss_ids:
        cent = np.array([xy[assign == j].mean(axis=0) for j in range(kk)])
        extra = ((all_xy[n_emb:, None, :] - cent[None]) ** 2).sum(axis=2).argmin(axis=1).astype(np.int32)
        assign = np.concatenate([assign, extra])
    rec = [by_id[i] for i in all_ids]
    titles = [r.get("title") or "" for r in rec]
    tps, tgs = [r.get("topics", []) for r in rec], [r.get("tags", []) for r in rec]
    admin = label_clusters_info(assign, kk, titles, tps, tgs) if kk else {"labels": [], "muted": [], "candidates": []}
    public_mask = np.array([not r.get("projects") for r in rec], dtype=bool)
    public = label_clusters_info(assign, kk, titles, tps, tgs, include=public_mask) if kk else admin
    return {"ids": all_ids, "xy": all_xy, "assign": assign, "labels": admin["labels"], "muted": admin["muted"],
            "labels_public": public["labels"], "muted_public": public["muted"],
            "candidates": admin["candidates"], "k": kk, "rec": rec}


def _year_of(rec: dict) -> int | None:
    """Publication year, else the year the paper was added; None when neither is known."""
    try:
        y = int(rec.get("year"))
        if 1500 < y < 2200:
            return y
    except (TypeError, ValueError):
        pass
    d = parse_ts(rec.get("created"))
    return d.year if d else None


def _status_of(rec: dict) -> str:
    st = rec.get("status")
    return st if st in ("reading", "read") else "unread"


def build_payload(layout: dict, attrs: dict, derived: dict, hidden: set[str], refs: bool,
                  stale: bool = False) -> dict:
    """The /stats/topic-map payload, filtered to what the user may see."""
    visible_projects = {pr["id"]: pr["name"] for pr in attrs["projects"]}
    colors = project_colors(list(visible_projects))
    # visible = projects the user may see (given by attrs["visible_project_ids"] when not admin)
    vis_set = attrs.get("visible_project_ids")
    proj_list = sorted(visible_projects) if vis_set is None else sorted(p for p in visible_projects if p in vis_set)
    proj_index = {pid: i for i, pid in enumerate(proj_list)}
    public_view = vis_set is not None
    labels = derived.get("labels_public", derived["labels"]) if public_view else derived["labels"]
    muted = derived.get("muted_public", derived["muted"]) if public_view else derived["muted"]
    live = {p["id"]: p for p in attrs["papers"]}          # year / reading status are read live, not from the derived snapshot
    shown = []
    for pid, (x, y), c, r in zip(derived["ids"], derived["xy"], derived["assign"], derived["rec"]):
        if pid in hidden:
            continue
        is_ref = 1 if SYSTEM_TAG in r.get("tags", []) else 0
        if is_ref and not refs:
            continue
        shown.append((pid, x, y, int(c), is_ref, r))
    proj_count: Counter = Counter()
    for *_, r in shown:
        for q in set(r.get("projects", [])):
            if q in proj_index:
                proj_count[q] += 1
    proj_list = [q for q in proj_list if proj_count[q] > 0]        # no empty projects on the map
    proj_index = {pid: i for i, pid in enumerate(proj_list)}
    points, per_cluster, per_lib = [], Counter(), Counter()
    members: dict[int, list[tuple[float, float]]] = {}
    for pid, x, y, c, is_ref, r in shown:
        ps = sorted(proj_index[q] for q in set(r.get("projects", [])) if q in proj_index)
        topics = r.get("topics") or []
        points.append({"id": pid, "x": round(float(x), 4), "y": round(float(y), 4), "c": c,
                       "t": (r.get("title") or "")[:140], "r": is_ref, "p": ps,
                       "topic": topics[0] if topics else None,
                       "yr": _year_of(live.get(pid) or r), "s": _status_of(live.get(pid) or r)})
        per_cluster[c] += 1
        per_lib[c] += 0 if is_ref else 1
        members.setdefault(c, []).append((float(x), float(y)))
    clusters = []
    slot = 0                                     # palette slot = size rank among non-muted clusters
    for j in range(derived["k"]):
        mem = np.array(members.get(j) or [(0.5, 0.5)])
        is_muted = bool(muted[j])
        if is_muted:
            color = MUTED_COLOR
        else:
            color = (CLUSTER_COLORS + CLUSTER_COLORS_EXTRA)[slot % (len(CLUSTER_COLORS) + len(CLUSTER_COLORS_EXTRA))]
            slot += 1
        clusters.append({"id": j, "label": labels[j], "color": color, "muted": is_muted,
                         "x": round(float(np.median(mem[:, 0])), 4), "y": round(float(np.median(mem[:, 1])), 4),
                         "size": per_cluster[j], "library": per_lib[j]})
    projects = [{"id": pid, "name": visible_projects[pid], "color": colors[pid], "count": proj_count[pid]}
                for pid in proj_list]
    return {"state": "ready" if points or layout["n"] else "empty",
            "computed_at": layout["computed_at"], "seconds": layout["seconds"], "n": len(points),
            "stale": stale, "points": points, "clusters": clusters, "projects": projects}


def empty_payload(state: str) -> dict:
    return {"state": state, "computed_at": None, "seconds": None, "n": 0, "stale": False,
            "points": [], "clusters": [], "projects": []}


# --------------------------------------------------------------------------- state / cache

_lock = threading.RLock()         # guards the cache dict below
_attr_lock = threading.Lock()     # one attribute refresh at a time
_cache: dict = {"layout": None, "attrs": None, "attrs_ts": 0.0, "attrs_hash": None,
                "derived": None, "derived_key": None, "derived_loaded": False,
                "variants": {}, "kjobs": {}, "job": None, "job_fail_ts": 0.0, "error": None, "meta_mtime": None, "meta": None}
_executor: ProcessPoolExecutor | None = None
_use_pool = True

ATTR_QUERY = """
MATCH (p:Paper)
RETURN p.id AS id, p.title AS title, p.year AS year, p.reading_status AS status, p.created_at AS created,
       [(p)-[:TAGGED]->(g:Tag) | g.name] AS tags,
       [(p)-[:ABOUT]->(t:Topic) | t.name] AS topics,
       [(p)-[:IN_PROJECT]->(x:Project) | x.id] AS projects
"""
PROJECT_QUERY = "MATCH (x:Project) RETURN x.id AS id, x.name AS name"


def emb_dir() -> Path:
    try:
        from services.library_search import semantic
        return semantic.data_dir()
    except Exception:  # pragma: no cover
        return Path(os.environ.get("LIBRARY_SEARCH_DIR", "/data/library_search"))


def map_dir() -> Path:
    configured = os.environ.get("TOPIC_MAP_DIR")
    for c in ([Path(configured)] if configured else []) + [Path("/data/topic_map"),
                                                              Path(tempfile.gettempdir()) / "papermanager-topic-map"]:
        try:
            c.mkdir(parents=True, exist_ok=True)
            probe = c / ".w"
            probe.write_text("x")
            probe.unlink()
            return c
        except OSError:
            continue
    return Path(tempfile.gettempdir())


def _read_meta(edir: Path) -> dict | None:
    mp = edir / "meta.json"
    try:
        mt = mp.stat().st_mtime
    except OSError:
        return None
    if _cache["meta_mtime"] == mt and _cache["meta"] is not None:
        return _cache["meta"]
    try:
        raw = json.loads(mp.read_text())
    except (OSError, ValueError):
        return None
    meta = {"saved_at": raw.get("saved_at"), "n": len(raw.get("ids", [])), "ids": raw.get("ids", [])}
    _cache["meta_mtime"], _cache["meta"] = mt, meta
    return meta


def _load_layout_file() -> dict | None:
    f = map_dir() / "layout.json"
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return None


def _is_stale(layout: dict | None, meta: dict | None) -> bool:
    if meta is None:
        return False
    if layout is None:
        return True
    return layout.get("emb_saved_at") != meta["saved_at"] or layout.get("n") != meta["n"]


def seed_init(X: np.ndarray, ids: list[str], prev: dict | None, rng_seed: int = 0) -> np.ndarray | None:
    """Initial positions from a previous layout: kept ids keep their place, new ids start at the
    similarity-weighted mean of their nearest kept neighbours plus a small jitter."""
    if not prev or not prev.get("ids"):
        return None
    old = {pid: (x, y) for pid, x, y in zip(prev["ids"], prev["x"], prev["y"])}
    keep = np.array([i in old for i in ids])
    if keep.sum() < max(20, 0.3 * len(ids)):
        return None
    init = np.zeros((len(ids), 2))
    kept_idx = np.nonzero(keep)[0]
    init[kept_idx] = np.array([old[ids[i]] for i in kept_idx])
    new_idx = np.nonzero(~keep)[0]
    rng = np.random.default_rng(rng_seed)
    Xk = X[kept_idx]
    for s in range(0, len(new_idx), 1024):
        part = new_idx[s:s + 1024]
        S = X[part] @ Xk.T
        kk = min(5, Xk.shape[0])
        top = np.argpartition(-S, kk - 1, axis=1)[:, :kk]
        sims = np.maximum(np.take_along_axis(S, top, axis=1), 1e-6)
        wts = sims / sims.sum(axis=1, keepdims=True)
        init[part] = (init[kept_idx][top] * wts[:, :, None]).sum(axis=1) + rng.normal(scale=0.005, size=(len(part), 2))
    return init


def build_layout_file(edir: Path | None = None, seed: int = 0) -> dict:
    """Compute and persist the layout from the embedding files. Blocking; run in a thread."""
    edir = edir or emb_dir()
    t0 = time.perf_counter()
    meta = json.loads((edir / "meta.json").read_text())
    ids = list(meta["ids"])
    X = np.load(edir / "emb.npy")
    if X.shape[0] != len(ids):
        raise ValueError(f"emb.npy has {X.shape[0]} rows but meta.json lists {len(ids)} ids")
    prev = _cache["layout"] or _load_layout_file()
    init = seed_init(X, ids, prev, seed)
    xy = compute_layout(X, seed=seed, init=init)
    layout = {"ids": ids, "x": [float(v) for v in xy[:, 0]], "y": [float(v) for v in xy[:, 1]],
              "emb_saved_at": meta.get("saved_at"), "n": len(ids),
              "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "seconds": round(time.perf_counter() - t0, 1), "seed": seed, "seeded": init is not None}
    f = map_dir() / "layout.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(layout, separators=(",", ":")))
    os.replace(tmp, f)
    return layout


def fetch_attrs(driver) -> dict:
    with driver.session() as s:
        papers = [dict(r) for r in s.run(ATTR_QUERY)]
        projects = [dict(r) for r in s.run(PROJECT_QUERY)]
    return {"papers": papers, "projects": projects}


def attrs_hash(attrs: dict) -> str:
    """Content hash of the attributes, independent of list order."""
    h = hashlib.sha1()
    for p in sorted(attrs["papers"], key=lambda r: r["id"]):
        h.update(json.dumps([p["id"], p.get("title"), sorted(p.get("tags") or []), sorted(p.get("topics") or []),
                             sorted(p.get("projects") or [])], ensure_ascii=False).encode())
    for pr in sorted(attrs["projects"], key=lambda r: r["id"]):
        h.update(json.dumps([pr["id"], pr.get("name")], ensure_ascii=False).encode())
    return h.hexdigest()


def _refresh_attrs(driver) -> None:
    if not _attr_lock.acquire(blocking=False):
        return
    try:
        attrs = fetch_attrs(driver)
        h = attrs_hash(attrs)
        with _lock:
            _cache["attrs_ts"] = time.time()
            if h != _cache["attrs_hash"]:        # unchanged content: keep the cached objects, no re-derive
                _cache["attrs"], _cache["attrs_hash"] = attrs, h
    except Exception:  # noqa: BLE001
        log.exception("topic map attribute refresh failed")
    finally:
        _attr_lock.release()


def _get_attrs(driver) -> dict | None:
    if _cache["attrs"] is None:
        _refresh_attrs(driver)            # first load: the one read query on the request path
        return _cache["attrs"]
    if time.time() - _cache["attrs_ts"] > ATTR_TTL and not _attr_lock.locked():
        threading.Thread(target=_refresh_attrs, args=(driver,), name="topic-map-attrs", daemon=True).start()
    return _cache["attrs"]


def hidden_paper_ids(driver) -> tuple[set[str], set[str] | None]:
    """(paper ids the user may not see, visible project ids or None for admins)."""
    from db.queries.visibility import current_user, is_admin, paper_visibility_clause, project_visibility_clause
    if is_admin(current_user()):
        return set(), None
    pc, pp = paper_visibility_clause("p")
    prc, prp = project_visibility_clause("proj")
    with driver.session() as s:
        hidden = {r["id"] for r in s.run(f"MATCH (p:Paper) WHERE NOT ({pc}) RETURN p.id AS id", **pp)}
        vis = {r["id"] for r in s.run(f"MATCH (proj:Project) WHERE {prc} RETURN proj.id AS id", **prp)}
    return hidden, vis


# --------------------------------------------------------------------------- background job (child process)

def min_interval() -> float:
    try:
        return float(os.environ.get("TOPIC_MAP_MIN_INTERVAL", MIN_INTERVAL_DEFAULT))
    except ValueError:
        return MIN_INTERVAL_DEFAULT


def derived_to_json(derived: dict, layout_meta: dict, attrs_h: str) -> dict:
    return {"ids": derived["ids"], "xy": np.asarray(derived["xy"]).tolist(),
            "assign": [int(a) for a in derived["assign"]], "labels": derived["labels"],
            "muted": [bool(m) for m in derived["muted"]], "labels_public": derived["labels_public"],
            "muted_public": [bool(m) for m in derived["muted_public"]],
            "candidates": derived["candidates"], "k": int(derived["k"]), "rec": derived["rec"],
            "layout_meta": layout_meta, "attrs_hash": attrs_h}


def derived_from_json(raw: dict) -> dict:
    d = dict(raw)
    d["xy"] = np.array(raw["xy"], dtype=np.float64).reshape(-1, 2)
    d["assign"] = np.array(raw["assign"], dtype=np.int32)
    return d


def _layout_meta(layout: dict) -> dict:
    return {k: layout.get(k) for k in ("computed_at", "seconds", "n")}


def _save_json(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")))
    os.replace(tmp, path)


def _job(mdir: str, edir: str, layout: dict | None, build: bool, attrs: dict, attrs_h: str) -> dict:
    """Runs in a child process (or a thread as fallback): optional layout build, then derive.
    Takes and returns plain data; persists layout.json and derived.json."""
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass
    os.environ["TOPIC_MAP_DIR"] = mdir
    t0 = time.perf_counter()
    if build:
        _cache["layout"] = layout        # previous layout seeds the new one (a child's cache starts empty)
        layout = build_layout_file(Path(edir))
    derived = derive(layout, attrs)
    _save_json(Path(mdir) / "derived.json", derived_to_json(derived, _layout_meta(layout), attrs_h))
    return {"layout": layout if build else None, "derived": derived, "attrs_hash": attrs_h,
            "layout_key": layout["computed_at"], "built": build, "seconds": round(time.perf_counter() - t0, 1)}


def _job_k(layout: dict, attrs: dict, k: int, attrs_h: str) -> dict:
    """Child-process job: re-run k-means on the cached layout with `k` clusters and re-derive labels."""
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass
    t0 = time.perf_counter()
    derived = derive(layout, attrs, k)
    return {"k": k, "derived": derived, "attrs_hash": attrs_h, "layout_key": layout["computed_at"],
            "seconds": round(time.perf_counter() - t0, 1)}


def _submit(fn, *args) -> Future:
    """One-worker spawn process pool, created lazily; an in-process thread when no pool can start."""
    global _executor, _use_pool
    if _use_pool:
        try:
            if _executor is None:
                _executor = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
            return _executor.submit(fn, *args)
        except Exception:  # noqa: BLE001
            log.warning("topic map: process pool unavailable, falling back to a thread", exc_info=True)
            _use_pool, _executor = False, None
    fut: Future = Future()

    def run():
        try:
            fut.set_result(fn(*args))
        except BaseException as e:  # noqa: BLE001
            fut.set_exception(e)
    threading.Thread(target=run, name="topic-map-job", daemon=True).start()
    return fut


def _on_job_done(fut: Future) -> None:
    global _executor
    try:
        res = fut.result()
    except BaseException as e:  # noqa: BLE001
        log.error("topic map job failed: %r", e)
        if e.__class__.__name__ == "BrokenProcessPool":
            _executor = None
        with _lock:
            _cache["error"], _cache["job"], _cache["job_fail_ts"] = str(e), None, time.time()
        return
    with _lock:
        if res["built"]:
            _cache["layout"] = res["layout"]
        _cache["derived"] = res["derived"]
        _cache["derived_key"] = (res["layout_key"], res["attrs_hash"])
        _cache["error"], _cache["job"] = None, None


def _on_kjob_done(k: int, fut: Future) -> None:
    global _executor
    try:
        res = fut.result()
    except BaseException as e:  # noqa: BLE001
        log.error("topic map clusters=%s job failed: %r", k, e)
        if e.__class__.__name__ == "BrokenProcessPool":
            _executor = None
        with _lock:
            _cache["kjobs"].pop(k, None)
            _cache.setdefault("kfail", {})[k] = time.time()
        return
    with _lock:
        _cache.setdefault("variants", {})[k] = {"key": (res["layout_key"], res["attrs_hash"]), "derived": res["derived"]}
        _cache["kjobs"].pop(k, None)


def _variant(layout: dict | None, attrs: dict, k: int) -> tuple[dict | None, bool]:
    """Cached derive for k clusters: (derived or None, current). Starts the background job when out of date; never blocks."""
    with _lock:
        v = _cache.setdefault("variants", {}).get(k)
        key = (layout and layout.get("computed_at"), _cache["attrs_hash"])
        if v is not None and v["key"] == key:
            return v["derived"], True
        if layout is not None and k not in _cache.setdefault("kjobs", {}) \
                and time.time() - _cache.get("kfail", {}).get(k, 0.0) >= FAIL_BACKOFF:
            try:
                fut = _submit(_job_k, layout, attrs, k, _cache["attrs_hash"])
            except Exception:  # noqa: BLE001
                log.exception("topic map: could not start clusters job")
                _cache.setdefault("kfail", {})[k] = time.time()
            else:
                _cache.setdefault("kjobs", {})[k] = fut
                fut.add_done_callback(lambda f, k=k: _on_kjob_done(k, f))
        return (v["derived"] if v else None), False


def _needs_layout(layout: dict | None, meta: dict | None) -> bool:
    """Rebuild only when none exists, the library size moved by more than 5 %, or the interval has passed."""
    if meta is None:
        return False
    if layout is None:
        return True
    if not _is_stale(layout, meta):
        return False
    n_old = max(1, int(layout.get("n") or 0))
    if abs(meta["n"] - n_old) / n_old > BIG_CHANGE:
        return True
    at = parse_ts(layout.get("computed_at"))
    return at is None or (datetime.now(timezone.utc) - at).total_seconds() >= min_interval()


def _load_derived_file() -> None:
    """Cold start: serve labels from the last derived.json at once."""
    with _lock:
        if _cache["derived_loaded"]:
            return
        _cache["derived_loaded"] = True
        if _cache["derived"] is not None:
            return
        try:
            raw = json.loads((map_dir() / "derived.json").read_text())
            _cache["derived"] = derived_from_json(raw)
            _cache["derived_key"] = (raw["layout_meta"].get("computed_at"), raw.get("attrs_hash"))
        except (OSError, ValueError, KeyError):
            pass


def _schedule(layout: dict | None, attrs: dict, need_layout: bool, edir: Path) -> bool:
    """Start the one background job if layout or derived is out of date. Never blocks. Returns whether derived is current."""
    with _lock:
        current = (layout and layout.get("computed_at"), _cache["attrs_hash"]) == _cache["derived_key"] \
            and _cache["derived"] is not None
        if _cache["job"] is not None or (current and not need_layout):
            return current
        if time.time() - _cache["job_fail_ts"] < FAIL_BACKOFF:
            return current
        build = need_layout or layout is None
        try:
            _cache["job"] = _submit(_job, str(map_dir()), str(edir), layout, build, attrs, _cache["attrs_hash"])
        except Exception:  # noqa: BLE001
            log.exception("topic map: could not start job")
            _cache["job_fail_ts"] = time.time()
            return current
        fut = _cache["job"]
    fut.add_done_callback(_on_job_done)
    return current


def get_topic_map(driver, refs: bool = True, clusters: int | None = None) -> dict:
    """Cached, visibility-filtered topic map. The request path does no layout or labelling work:
    those run in a background job and the last derived result is served meanwhile."""
    edir = emb_dir()
    meta = _read_meta(edir)
    if _cache["layout"] is None:
        _cache["layout"] = _load_layout_file()
    _load_derived_file()
    layout = _cache["layout"]
    if meta is not None and meta["n"] == 0 and layout is None and _cache["derived"] is None:
        return empty_payload("empty")
    if layout is None and meta is None and _cache["derived"] is None:
        return empty_payload("empty")
    attrs = _get_attrs(driver)
    if attrs is None:
        return empty_payload("building")
    need_layout = _needs_layout(layout, meta)
    current = _schedule(layout, attrs, need_layout, edir)
    with _lock:
        derived = _cache["derived"]
        job = _cache["job"]
    if derived is None:
        return empty_payload("building")
    if clusters is not None and clamp_clusters(clusters) != derived["k"]:
        k = clamp_clusters(clusters)
        vd, v_current = _variant(layout, attrs, k)
        if vd is None:
            return empty_payload("building")
        derived, current = vd, current and v_current
        job = job or (None if v_current else True)
    hidden, vis = hidden_paper_ids(driver)
    view = attrs if vis is None else {**attrs, "visible_project_ids": vis}
    stale = (not current) or _is_stale(layout, meta) or job is not None
    return build_payload(derived.get("layout_meta") or layout, view, derived, hidden, refs, stale=stale)
