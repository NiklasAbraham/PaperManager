"""Synthetic data for the vector store tests: random unit vectors, metadata and a brute-force reference."""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

from services.vectorstore import ExactStore, LanceStore, ModelSpec

# pip install --target <dir> lancedb  ->  PM_VEC_LANCE_PATH=<dir>: lets the lance tests run without
# installing the optional package into the test environment.
_extra = os.environ.get("PM_VEC_LANCE_PATH", "")
if _extra and _extra not in sys.path:
    sys.path.append(_extra)
LANCE_AVAILABLE = importlib.util.find_spec("lancedb") is not None and importlib.util.find_spec("pyarrow") is not None
LANCE_SKIP = "the optional 'lancedb' package is not installed (pip install lancedb)"

DIM = 24
KINDS = ["paper", "candidate", "book"]
SOURCES = ["library", "arxiv", "biorxiv"]
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def spec(dim: int = DIM, model: str = "test/model-a", **kw) -> ModelSpec:
    return ModelSpec(model=model, dim=dim, **kw)


def unit(rng: np.random.Generator, n: int, dim: int = DIM) -> np.ndarray:
    v = rng.normal(size=(n, dim)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def make_meta(rng: np.random.Generator, n: int, prefix: str = "id") -> tuple[list[str], list[dict]]:
    ids = [f"{prefix}{i}" for i in range(n)]
    metas = []
    for i in range(n):
        day = BASE + timedelta(days=int(rng.integers(0, 700)))
        metas.append({"kind": KINDS[int(rng.integers(3))], "source": SOURCES[int(rng.integers(3))],
                      "published": day.date().isoformat(), "year": day.year,
                      "added_at": (day + timedelta(hours=int(rng.integers(0, 24)))).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "n": i})
    return ids, metas


def reference(V: np.ndarray, ids: list[str], q: np.ndarray, k: int, keep: np.ndarray | None = None):
    """Brute force: ids and scores of the k best rows of V (restricted to ``keep``), best first."""
    sims = V @ q
    order = np.argsort(-sims, kind="stable")
    if keep is not None:
        order = order[keep[order]]
    return [(ids[i], float(sims[i])) for i in order[:k]]


def make_store(root, backend: str, namespace: str = "ns", dim: int = DIM, **kw):
    cls = LanceStore if backend == "lance" else ExactStore
    return cls(root, namespace, spec=kw.pop("spec", None) or spec(dim), **kw)
