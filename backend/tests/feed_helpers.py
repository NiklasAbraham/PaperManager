"""Synthetic data for the paper feed tests: topic clusters, a fake embedder, Atom and JSON pages."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import numpy as np

DIM = 384
N_TOPICS = 8
_centres = np.random.default_rng(7).normal(size=(N_TOPICS, DIM))
CENTRES = (_centres / np.linalg.norm(_centres, axis=1, keepdims=True)).astype(np.float32)


def topic_vec(topic: int, key: str, spread: float = 0.35) -> np.ndarray:
    seed = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)
    noise = np.random.default_rng(seed).normal(size=DIM) / np.sqrt(DIM)
    v = CENTRES[topic] + spread * noise
    return (v / np.linalg.norm(v)).astype(np.float32)


def fake_embed(texts: list[str], **_) -> np.ndarray:
    """Vectors by the ``topic-N`` tag inside each text (no tag: topic 0), stable per text."""
    out = []
    for t in texts:
        m = re.search(r"topic-(\d+)", t)
        out.append(topic_vec(int(m.group(1)) if m else 0, t))
    return np.vstack(out) if out else np.zeros((0, DIM), dtype=np.float32)


def atom_page(entries: list[dict]) -> str:
    """An arXiv Atom response. Entry keys: id, title, summary, published, authors, categories, doi."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">']
    for e in entries:
        parts.append("<entry>")
        parts.append(f"<id>http://arxiv.org/abs/{e['id']}v1</id>")
        parts.append(f"<published>{e['published']}</published>")
        parts.append(f"<title>{e.get('title', 'T')}</title>")
        parts.append(f"<summary>{e.get('summary', 'S')}</summary>")
        for a in e.get("authors", ["Ada Example"]):
            parts.append(f"<author><name>{a}</name></author>")
        for c in e.get("categories", ["cs.LG"]):
            parts.append(f'<category term="{c}"/>')
        if e.get("doi"):
            parts.append(f'<link title="doi" href="https://doi.org/{e["doi"]}"/>')
        parts.append("</entry>")
    parts.append("</feed>")
    return "\n".join(parts)


def biorxiv_page(items: list[dict], total: int | None = None, cursor: int = 0) -> dict:
    return {"messages": [{"status": "ok", "count": len(items), "cursor": cursor,
                          "total": total if total is not None else len(items)}],
            "collection": items}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Resp:
    """Stands in for an httpx response."""

    def __init__(self, text: str | None = None, data: dict | None = None):
        self.content = (text or "").encode()
        self._data = data

    def json(self):
        return self._data
