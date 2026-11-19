"""The embedding model, its dimension and how texts are fed to it: one place.

Everything that embeds text (library search, the paper feed, the conference explorer) reads
the model from ``current()``. A vector store records the :class:`ModelSpec` it was built with
in its manifest and is *stale* when the configured spec has another space key, so vectors of
two models are never mixed.

Environment (all optional; the defaults are the long-standing bge-small setup):

    EMBED_MODEL          Hugging Face model id (legacy name CONFERENCE_EMBED_MODEL still works)
    EMBED_DIM            output dimension; only needed for a model not in ``KNOWN``
    EMBED_POOLING        ``cls`` or ``mean``; defaults per known model, else ``mean``
    EMBED_QUERY_PREFIX   text put in front of a short query
    EMBED_DOC_PREFIX     text put in front of every embedded document

    CONFERENCE_EMBED_MODEL   the conference explorer's model. When set it is read *first* by the
                             explorer (``current_conference()``) and EMBED_MODEL is used only if it
                             is unset, so the library can move to another model while the
                             explorer's saved vectors stay valid. If it names a model other than
                             EMBED_MODEL, dimension, pooling and prefixes come from ``KNOWN`` or
                             from CONFERENCE_EMBED_DIM / _POOLING / _QUERY_PREFIX / _DOC_PREFIX.

An empty variable counts as unset (compose files pass empty strings through).
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# Version of how a paper's text is built before embedding (services.library_search.semantic.
# paper_text: title, newline, abstract or summary cut to 1,500 characters). Bump it when that
# recipe changes so stores built with the old one report stale.
TEXT_FORMAT = "title-abstract-1"

_BGE_QUERY = "Represent this sentence for searching relevant passages: "

# model id -> (dimension, pooling, query prefix, document prefix). Starting points taken from the
# model cards; override any of them with the EMBED_* variables.
KNOWN: dict[str, tuple[int, str, str, str]] = {
    "BAAI/bge-small-en-v1.5": (384, "cls", _BGE_QUERY, ""),
    "BAAI/bge-base-en-v1.5": (768, "cls", _BGE_QUERY, ""),
    "BAAI/bge-large-en-v1.5": (1024, "cls", _BGE_QUERY, ""),
    "intfloat/e5-base-v2": (768, "mean", "query: ", "passage: "),
    "intfloat/e5-large-v2": (1024, "mean", "query: ", "passage: "),
    "sentence-transformers/all-MiniLM-L6-v2": (384, "mean", "", ""),
    "sentence-transformers/all-mpnet-base-v2": (768, "mean", "", ""),
    "allenai/specter2_base": (768, "cls", "", ""),
    # ModernBERT-base fine-tuned for scientific text (MIT); loads without trust_remote_code.
    "J0nasW/sciembed-full": (768, "mean", "", ""),
}


class ModelConfigError(ValueError):
    """The embedding settings do not describe a usable model."""


@dataclass(frozen=True)
class ModelSpec:
    model: str
    dim: int
    pooling: str = "cls"
    query_prefix: str = ""
    doc_prefix: str = ""
    text_format: str = TEXT_FORMAT

    def space_key(self) -> tuple:
        """What decides whether two sets of vectors live in the same space. The query prefix is
        not part of it: it changes how a query is phrased, not where documents sit."""
        return (self.model, self.dim, self.pooling, self.doc_prefix, self.text_format)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelSpec":
        return cls(model=str(d["model"]), dim=int(d["dim"]), pooling=str(d.get("pooling", "cls")),
                   query_prefix=str(d.get("query_prefix", "")), doc_prefix=str(d.get("doc_prefix", "")),
                   text_format=str(d.get("text_format", TEXT_FORMAT)))


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _spec_for(model: str, prefix: str) -> ModelSpec:
    """The spec of ``model`` with its settings read from ``<prefix>DIM``, ``<prefix>POOLING``,
    ``<prefix>QUERY_PREFIX`` and ``<prefix>DOC_PREFIX`` (``EMBED_`` for the main model)."""
    known = KNOWN.get(model)
    raw_dim = _env(prefix + "DIM")
    try:
        dim = int(raw_dim) if raw_dim else (known[0] if known else 0)
    except ValueError as exc:
        raise ModelConfigError(f"{prefix}DIM must be an integer, got {raw_dim!r}") from exc
    if dim <= 0:
        raise ModelConfigError(f"{prefix}DIM is required for the embedding model {model!r} (not in the known list)")
    pooling = (_env(prefix + "POOLING") or (known[1] if known else "mean")).lower()
    if pooling not in ("cls", "mean"):
        raise ModelConfigError(f"{prefix}POOLING must be 'cls' or 'mean', got {pooling!r}")
    return ModelSpec(
        model=model, dim=dim, pooling=pooling,
        query_prefix=os.environ.get(prefix + "QUERY_PREFIX") or (known[2] if known else ""),
        doc_prefix=os.environ.get(prefix + "DOC_PREFIX") or (known[3] if known else ""),
    )


def current() -> ModelSpec:
    """The configured model, read from the environment on every call (cheap)."""
    model = _env("EMBED_MODEL") or _env("CONFERENCE_EMBED_MODEL") or DEFAULT_MODEL
    return _spec_for(model, "EMBED_")


def current_conference() -> ModelSpec:
    """The conference explorer's model: ``CONFERENCE_EMBED_MODEL`` first, ``EMBED_MODEL`` only if it
    is unset, else the default. With neither set (or both naming one model) it equals ``current()``."""
    main = current()
    model = _env("CONFERENCE_EMBED_MODEL") or main.model
    return main if model == main.model else _spec_for(model, "CONFERENCE_EMBED_")


def dim() -> int:
    return current().dim


def conference_dim() -> int:
    return current_conference().dim


def legacy_model() -> str:
    """The model that produced vectors stored *before* the vector store existed (raw blobs in the
    feed database): the one the embedder used then, i.e. CONFERENCE_EMBED_MODEL or the default."""
    return _env("CONFERENCE_EMBED_MODEL") or DEFAULT_MODEL
