"""The embedding model on CPU: unit vectors for papers and queries (default BAAI/bge-small-en-v1.5, 384-dim).

Runs through ``transformers`` + ``torch``, which the backend already has for Docling, so
the explorer needs no new dependency and no API key. The model (~130 MB) is downloaded
once into ``<data dir>/models``. Model, dimension, pooling and prefixes come from
``services.vectorstore.model_config`` (``EMBED_MODEL`` and friends). Short queries get the
model's retrieval instruction (bge: "Represent this sentence ..."), as the model card
recommends; documents and long queries (a pasted abstract) do not.

Two roles share this module. The *library* role (``embed``, ``embed_query``, ``embed_document``,
``ready``) is the library search, the feed and similar-paper search: ``EMBED_MODEL``. The
*conference* role (``conference_embed``, ``conference_embed_query``, ``conference_ready``) is the
conference explorer, whose saved vectors keep their own model: ``CONFERENCE_EMBED_MODEL`` first,
``EMBED_MODEL`` only if that is unset. Loaded models are cached per model id, so two roles with
one model share it and two models are both held. Models load without ``trust_remote_code``.
"""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

from services.vectorstore import model_config

log = logging.getLogger(__name__)

ROLE_LIBRARY = "library"
ROLE_CONFERENCE = "conference"

# Import-time snapshot of the library role's model (kept for callers that read the constants).
_SPEC = model_config.current()
MODEL = _SPEC.model
DIM = _SPEC.dim
_POOLING = _SPEC.pooling
_QUERY_PREFIX = _SPEC.query_prefix
_DOC_PREFIX = _SPEC.doc_prefix

_lock = threading.Lock()
# Fast (Rust) tokenizers refuse concurrent use from two threads ("Already borrowed");
# a build and a query can tokenise at the same time, so tokenising is serialised.
_tok_lock = threading.Lock()
_models: dict[str, tuple] = {}      # model id -> (tokenizer, model): one per id, however many roles use it


def spec(role: str = ROLE_LIBRARY) -> model_config.ModelSpec:
    """The model of ``role`` as the environment configures it now."""
    return model_config.current_conference() if role == ROLE_CONFERENCE else model_config.current()


def _load(sp: model_config.ModelSpec | None = None):
    """``(tokenizer, model)`` of ``sp`` (default: the library role's model), loaded once per model id."""
    sp = sp or spec()
    hit = _models.get(sp.model)
    if hit is not None:
        return hit
    with _lock:
        if sp.model not in _models:
            import torch
            from transformers import AutoModel, AutoTokenizer

            from services.conferences.store import data_dir

            cache = str(data_dir() / "models")
            threads = int(os.environ.get("CONFERENCE_EMBED_THREADS", "4"))
            torch.set_num_threads(max(1, threads))
            log.info("Loading %s (cache %s, %d threads)", sp.model, cache, threads)
            # The cached copy first: a load that asks huggingface.co costs four round trips
            # and hangs when the hub is unreachable. Online only for the first download.
            try:
                tok = AutoTokenizer.from_pretrained(sp.model, cache_dir=cache, local_files_only=True,
                                                    trust_remote_code=False)
                model = AutoModel.from_pretrained(sp.model, cache_dir=cache, local_files_only=True,
                                                  trust_remote_code=False).eval()
            except OSError:
                tok = AutoTokenizer.from_pretrained(sp.model, cache_dir=cache, trust_remote_code=False)
                model = AutoModel.from_pretrained(sp.model, cache_dir=cache, trust_remote_code=False).eval()
            _models[sp.model] = (tok, model)
    return _models[sp.model]


def ready(role: str = ROLE_LIBRARY) -> bool:
    return spec(role).model in _models


def conference_ready() -> bool:
    return ready(ROLE_CONFERENCE)


def _embed(role: str, texts: list[str], max_length: int, batch: int, progress, doc: bool) -> np.ndarray:
    import torch

    sp = spec(role)
    tok, model = _load(sp)
    if doc and sp.doc_prefix:
        texts = [sp.doc_prefix + t for t in texts]
    out = np.zeros((len(texts), sp.dim), dtype=np.float32)
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    done = 0
    with torch.inference_mode():
        for s in range(0, len(order), batch):
            idx = order[s:s + batch]
            with _tok_lock:
                enc = tok([texts[i] or " " for i in idx], padding=True, truncation=True,
                          max_length=max_length, return_tensors="pt")
            hidden = model(**enc).last_hidden_state
            if sp.pooling == "mean":
                mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            else:
                pooled = hidden[:, 0]
            if pooled.shape[1] != sp.dim:
                raise RuntimeError(f"{sp.model} produces {pooled.shape[1]}-dim vectors but EMBED_DIM is {sp.dim}")
            out[idx] = torch.nn.functional.normalize(pooled, dim=-1).numpy()
            done += len(idx)
            if progress:
                progress(done, len(texts))
    return out


def embed(texts: list[str], max_length: int = 256, batch: int = 64, progress=None, doc: bool = True) -> np.ndarray:
    """Unit-length embeddings (CLS or mean pooled, per the model), shape (len(texts), dim), float32.
    ``doc=False`` skips the document prefix (queries carry their own).

    Texts are processed shortest first so a batch pads to similar lengths, which on
    CPU is several times faster than the original order. ``scripts/embed_bulk.py`` reproduces
    this function (tokenisation, truncation, pooling, normalisation) for a GPU machine; a test
    keeps the two equal."""
    return _embed(ROLE_LIBRARY, texts, max_length, batch, progress, doc)


def conference_embed(texts: list[str], max_length: int = 256, batch: int = 64, progress=None,
                     doc: bool = True) -> np.ndarray:
    """``embed`` with the conference explorer's model (``CONFERENCE_EMBED_MODEL`` first)."""
    return _embed(ROLE_CONFERENCE, texts, max_length, batch, progress, doc)


def _embed_fn(role: str):
    return conference_embed if role == ROLE_CONFERENCE else embed


def _query_text(role: str, text: str) -> str:
    text = text.strip()
    prefix = spec(role).query_prefix
    return prefix + text if prefix and is_short_query(text) else text


def query_text(text: str) -> str:
    """The text a query is embedded as: short queries get the model's retrieval instruction."""
    return _query_text(ROLE_LIBRARY, text)


def conference_query_text(text: str) -> str:
    return _query_text(ROLE_CONFERENCE, text)


def remote_url() -> str:
    """``PM_EMBED_URL``: where a process without the model asks for query vectors (the
    backend's POST /conferences/embed). Set by mcp_server.py; empty in the backend itself."""
    return os.environ.get("PM_EMBED_URL", "").strip()


def _remote_embed(payload: dict, role: str = ROLE_LIBRARY) -> np.ndarray | None:
    """The backend's embedding for ``payload`` (``{"text": ..., "document": ...}``), or None if
    it cannot give one (an older backend without the route, not started, model still loading,
    timeout, other model). The conference role adds ``"role": "conference"`` to the request; a
    backend that does not know it answers with its library model, which the check below refuses."""
    url = remote_url()
    if not url:
        return None
    sp = spec(role)
    try:
        import httpx

        from services.pdf_import import api_headers

        body = payload if role == ROLE_LIBRARY else {**payload, "role": role}
        r = httpx.post(url, json=body, headers=api_headers(), timeout=2.0)
        if r.status_code != 200:
            log.info("Remote query embedding unavailable (HTTP %s); loading the model here", r.status_code)
            return None
        d = r.json()
        if d.get("model") != sp.model or d.get("dim") != sp.dim or len(d.get("vector") or []) != sp.dim:
            log.warning("Remote query embedding is for %s/%s, not %s; loading the model here",
                        d.get("model"), d.get("dim"), sp.model)
            return None
        return np.asarray(d["vector"], dtype=np.float32)
    except Exception as exc:  # noqa: BLE001 — any failure: embed locally as before
        log.info("Remote query embedding failed (%s); loading the model here", exc)
        return None


def _remote_query(q: str) -> np.ndarray | None:
    """The backend's embedding of the (already prefixed) query ``q``, or None."""
    return _remote_embed({"text": q})


def _embed_query(role: str, text: str) -> np.ndarray:
    q = _query_text(role, text)
    if not ready(role):
        v = _remote_embed({"text": q}, role)
        if v is not None:
            return v
    fn = _embed_fn(role)
    if spec(role).doc_prefix:   # the query's own prefix is already in ``q``; a document prefix must not be added
        return fn([q], max_length=512, doc=False)[0]
    return fn([q], max_length=512)[0]


def embed_query(text: str) -> np.ndarray:
    """Unit vector of a query. A process that has not loaded the model and has
    ``PM_EMBED_URL`` (the MCP server) asks the backend first; if that fails it loads the
    model and embeds locally, after which every query stays local."""
    return _embed_query(ROLE_LIBRARY, text)


def conference_embed_query(text: str) -> np.ndarray:
    """``embed_query`` with the conference explorer's model."""
    return _embed_query(ROLE_CONFERENCE, text)


# Texts of this many words or fewer are embedded as queries (with the model's retrieval
# instruction); longer ones, such as a pasted abstract, are embedded like a stored document.
QUERY_MAX_WORDS = 24
# The index embeds title + abstract cut at this many tokens (``embed``'s default); a pasted
# abstract is cut the same way so that it lands in the same place as the papers it resembles.
DOC_MAX_LENGTH = 256


def is_short_query(text: str) -> bool:
    return len(text.split()) <= QUERY_MAX_WORDS


def embed_document(text: str) -> np.ndarray:
    """Unit vector of ``text`` embedded the way stored papers are: the model's document prefix (if
    any), no retrieval instruction, the same token limit as the index. A process without the model
    that has ``PM_EMBED_URL`` asks the backend first (``{"document": true}``) and loads the model
    itself only if that fails."""
    text = text.strip()
    if not ready():
        v = _remote_embed({"text": text, "document": True})
        if v is not None:
            return v
    return embed([text], max_length=DOC_MAX_LENGTH, doc=True)[0]


def embed_search_text(text: str) -> tuple[np.ndarray, str]:
    """(vector, mode) of a text typed into a "find similar" search. ``mode`` is ``"query"`` for a
    short phrase (keywords; the retrieval instruction is added) and ``"document"`` for an
    abstract-sized text (embedded like a stored paper)."""
    if is_short_query(text):
        return embed_query(text), "query"
    return embed_document(text), "document"
