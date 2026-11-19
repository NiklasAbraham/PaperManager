#!/usr/bin/env python
"""Import vectors made by ``embed_bulk.py`` into the vector store as a prepared generation.

Run inside the backend environment, with the same ``VECTOR_STORE_DIR`` (and ``VECTOR_STORE``) as the
backend, after copying ``<namespace>.npy`` and ``<namespace>.ids.json`` back next to the export
(``spec.json`` and ``<namespace>.jsonl`` from ``vectors_export.py`` are still needed there):

    python scripts/vectors_import.py /data/vector_export

For each namespace (``library``, ``feed``, ``feed_library``) it

  1. checks the files: dimension = spec.dim, one vector per id, no NaN, unit length, ids unique and all
     of them in the export, and (when ``<namespace>.done.json`` is there) that the vectors were made
     from exactly the exported texts;
  2. re-embeds N random texts (default 20) on this machine's CPU with the backend's own embedder and
     requires a mean cosine >= 0.98 to the imported vectors (float16 on a GPU against float32 here).
     ``--skip-check`` skips it; so does a model that cannot be loaded here (said loudly, nothing is
     verified then);
  3. stores the vectors as a *prepared* generation of the namespace for the target model: not live, no
     writer lock, the live generation and every reader are untouched. The text hashes and metadata
     of the export ride along, so after the switch the normal sync embeds only papers that are new
     or whose text changed;
  4. reports ids the live generation holds that the import lacks (papers added since the export: the
     sync embeds them) and ids only the import has.

Nothing changes until the backend is started with ``EMBED_MODEL`` (and the other settings printed at the
end) set to the target model: it then adopts the prepared generation instead of re-embedding everything
on the CPU. The generation it replaces is kept for a rollback (``VECTOR_STORE_KEEP_GENERATIONS``,
``scripts/vectors_rollback.py``). ``--discard`` throws prepared generations away. Running the import
again replaces the prepared generation of a namespace.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

NAMESPACES = ("library", "feed", "feed_library")
UNIT_TOLERANCE = 1e-3
MIN_COSINE = 0.98
BATCH = 4096


class ImportCheckError(Exception):
    """The files cannot be imported; the message says why."""


def load_spec(src: Path):
    from services.vectorstore import model_config
    from services.vectorstore.model_config import ModelSpec

    try:
        doc = json.loads((src / "spec.json").read_text(encoding="utf-8"))
        spec = ModelSpec.from_dict(doc)
    except (OSError, ValueError, KeyError) as exc:
        raise ImportCheckError(f"{src}/spec.json is missing or unreadable ({exc!r})") from exc
    if spec.text_format != model_config.TEXT_FORMAT:
        raise ImportCheckError(
            f"the export was made with text format {spec.text_format!r}, this code builds {model_config.TEXT_FORMAT!r}; "
            "export again")
    return spec, doc


def read_export(src: Path, ns: str) -> list[dict]:
    path = src / f"{ns}.jsonl"
    if not path.exists():
        raise ImportCheckError(f"{path} is missing")
    recs = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    recs.append(json.loads(line))
                except ValueError as exc:
                    raise ImportCheckError(f"{path}:{n}: not JSON ({exc})") from exc
    return recs


def load_vectors(src: Path, ns: str, spec, recs: list[dict]) -> tuple[list[str], np.ndarray]:
    """The vectors of ``ns`` after the checks of step 1: ``(ids, matrix)`` in the order of ``ids.json``."""
    npy, ids_path = src / f"{ns}.npy", src / f"{ns}.ids.json"
    if not npy.exists() or not ids_path.exists():
        raise ImportCheckError(f"{npy.name} / {ids_path.name} not found in {src}: run embed_bulk.py and copy "
                               "its output there")
    try:
        ids = [str(i) for i in json.loads(ids_path.read_text(encoding="utf-8"))]
        mat = np.load(npy, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ImportCheckError(f"{ns}: unreadable vectors or ids ({exc})") from exc
    if mat.ndim != 2 or mat.shape[1] != spec.dim:
        raise ImportCheckError(f"{ns}: the vectors have shape {tuple(mat.shape)}, spec.json says dimension {spec.dim}")
    if mat.shape[0] != len(ids):
        raise ImportCheckError(f"{ns}: {mat.shape[0]} vectors for {len(ids)} ids")
    if len(set(ids)) != len(ids):
        raise ImportCheckError(f"{ns}: duplicate ids")
    if not np.isfinite(mat).all():
        raise ImportCheckError(f"{ns}: the vectors contain NaN or infinity")
    norms = np.linalg.norm(mat.astype(np.float64), axis=1)
    if len(norms) and float(np.abs(norms - 1.0).max()) > UNIT_TOLERANCE:
        raise ImportCheckError(f"{ns}: the vectors are not unit length (largest deviation "
                               f"{float(np.abs(norms - 1.0).max()):.4f})")
    exported = {r["id"] for r in recs}
    unknown = [i for i in ids if i not in exported]
    if unknown:
        raise ImportCheckError(f"{ns}: {len(unknown)} ids are not in {ns}.jsonl (first: {unknown[0]!r}); "
                               "the vectors belong to another export")
    return ids, mat.astype(np.float32, copy=False)


def check_made_from_export(src: Path, ns: str, spec, doc: dict, recs: list[dict]) -> str:
    """Compare ``<ns>.done.json`` with a fingerprint of the exported texts. Returns a note ('' = verified)."""
    from embed_bulk import fingerprint

    try:
        done = json.loads((src / f"{ns}.done.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "no done.json next to the vectors: could not verify that they belong to this export"
    fp = fingerprint([r["id"] for r in recs], [r.get("text") or "" for r in recs], spec.to_dict(),
                     int(done.get("max_length") or doc.get("max_length") or 256))
    if done.get("fingerprint") != fp:
        raise ImportCheckError(f"{ns}: the vectors were not made from the texts of this export (fingerprint "
                               "differs); embed again")
    return ""


@contextlib.contextmanager
def spec_environment(spec):
    """The model settings of ``spec`` in the environment, so the backend's embedder is the target model."""
    names = {"EMBED_MODEL": spec.model, "EMBED_DIM": str(spec.dim), "EMBED_POOLING": spec.pooling,
             "EMBED_QUERY_PREFIX": spec.query_prefix, "EMBED_DOC_PREFIX": spec.doc_prefix}
    old = {k: os.environ.get(k) for k in names}
    os.environ.update(names)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def sanity_check(ns: str, spec, recs: list[dict], ids: list[str], mat: np.ndarray, n: int, min_cosine: float,
                 embed_fn=None, seed: int = 0, max_length: int = 256) -> dict:
    """Re-embed ``n`` random texts on the CPU and compare with the imported vectors. Returns
    ``{"checked": k, "mean_cosine": c}``; raises ImportCheckError below ``min_cosine``."""
    if not ids or n <= 0:
        return {"checked": 0}
    text = {r["id"]: r.get("text") or "" for r in recs}
    pick = sorted(np.random.default_rng(seed).choice(len(ids), size=min(n, len(ids)), replace=False).tolist())
    with spec_environment(spec):
        if embed_fn is None:
            from services.conferences import embedder
            from services.vectorstore import model_config

            if model_config.current().space_key() != spec.space_key():
                raise ImportCheckError("this machine's embedder is not configured as spec.json says")
            embed_fn = lambda texts: embedder.embed(texts, max_length=max_length)  # noqa: E731
        local = embed_fn([text[ids[i]] for i in pick])
    cos = np.einsum("ij,ij->i", np.asarray(local, dtype=np.float32), mat[pick])
    mean = float(cos.mean())
    if mean < min_cosine:
        raise ImportCheckError(f"{ns}: the imported vectors differ from this machine's embedding of the same texts "
                               f"(mean cosine {mean:.4f} over {len(pick)} texts, required {min_cosine}); "
                               "wrong model, pooling, prefix or text? Nothing of this namespace was imported")
    return {"checked": len(pick), "mean_cosine": round(mean, 5), "min_cosine": round(float(cos.min()), 5)}


def import_namespace(src: Path, ns: str, spec, doc: dict, *, check_n: int = 20, min_cosine: float = MIN_COSINE,
                     embed_fn=None, skip_check: bool = False, log=print) -> dict:
    from services.vectorstore import registry
    from services.vectorstore.base import now_iso

    recs = read_export(src, ns)
    result: dict = {"namespace": ns, "exported": len(recs)}
    if not recs:
        ids, mat = [], np.zeros((0, spec.dim), dtype=np.float32)
    else:
        ids, mat = load_vectors(src, ns, spec, recs)
        note = check_made_from_export(src, ns, spec, doc, recs)
        if note:
            log(f"[{ns}] WARNING: {note}")
            result["warning"] = note
    if len(ids) < len(recs):
        missing = len(recs) - len(ids)
        raise ImportCheckError(f"{ns}: {missing} exported texts have no vector; embed_bulk.py did not finish")
    if skip_check:
        result["check"] = "skipped (--skip-check)"
        log(f"[{ns}] sanity check skipped (--skip-check)")
    else:
        try:
            result["check"] = sanity_check(ns, spec, recs, ids, mat, check_n, min_cosine, embed_fn,
                                             max_length=int(doc.get("max_length") or 256))
            log(f"[{ns}] sanity check: {result['check']}")
        except ImportCheckError:
            raise
        except Exception as exc:  # noqa: BLE001 — the model cannot run here (not downloaded, no memory ...)
            result["check"] = f"SKIPPED, the model could not be loaded or run here: {type(exc).__name__}: {str(exc)[:200]}"
            log(f"[{ns}] WARNING: {result['check']} -- the vectors are NOT verified against the CPU embedder")
    meta_of = {r["id"]: r for r in recs}
    stamp = now_iso()
    store = registry._make(registry.vector_dir(), ns, True, spec)     # read-only handle: no writer lock
    try:
        live = store.ids()
        pr = store.begin_prepare(spec)
        try:
            for s in range(0, len(ids), BATCH):
                part = ids[s:s + BATCH]
                metas = []
                for i in part:
                    r = meta_of[i]
                    m = dict(r.get("meta") or {})
                    if r.get("hash"):
                        m["hash"] = r["hash"]
                    m.setdefault("added_at", stamp)
                    metas.append(m)
                pr.upsert(part, mat[s:s + BATCH], metas)
            pr.commit()
        except BaseException:
            pr.abort()
            raise
        prepared = store.prepared()
        have = set(ids)
        missing_ids = [i for i in live if i not in have]
        result.update(imported=len(ids), dim=spec.dim, generation=prepared[0].generation if prepared else None,
                      live_vectors=len(live), missing_from_import=len(missing_ids),
                      missing_sample=missing_ids[:10], only_in_import=len(have - set(live)))
    finally:
        store.close()
    log(f"[{ns}] imported {len(ids)} vectors as prepared generation {result['generation']}; "
        f"{len(missing_ids)} ids of the live generation are not in the import (embedded by the sync later)")
    return result


def env_lines(spec) -> list[str]:
    lines = [f"EMBED_MODEL={spec.model}"]
    from services.vectorstore.model_config import KNOWN
    known = KNOWN.get(spec.model)
    if known is None or known[0] != spec.dim:
        lines.append(f"EMBED_DIM={spec.dim}")
    if known is None or known[1] != spec.pooling:
        lines.append(f"EMBED_POOLING={spec.pooling}")
    if known is None or known[2] != spec.query_prefix:
        lines.append(f"EMBED_QUERY_PREFIX={spec.query_prefix}")
    if known is None or known[3] != spec.doc_prefix:
        lines.append(f"EMBED_DOC_PREFIX={spec.doc_prefix}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import embed_bulk.py output as a prepared vector store generation.")
    ap.add_argument("dir", help="the export directory, with <namespace>.npy and .ids.json copied back into it")
    ap.add_argument("--namespaces", default=",".join(NAMESPACES))
    ap.add_argument("--check", type=int, default=20, help="texts re-embedded on the CPU for the sanity check (default 20)")
    ap.add_argument("--min-cosine", type=float, default=MIN_COSINE)
    ap.add_argument("--skip-check", action="store_true", help="do not re-embed a sample on this machine")
    ap.add_argument("--discard", action="store_true", help="delete the prepared generations instead of importing")
    args = ap.parse_args(argv)

    src = Path(args.dir)
    wanted = [n.strip() for n in args.namespaces.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in NAMESPACES]
    if unknown:
        ap.error(f"unknown namespace {unknown}; choose from {', '.join(NAMESPACES)}")
    from services.vectorstore import registry

    if args.discard:
        for ns in wanted:
            store = registry._make(registry.vector_dir(), ns, True, None)
            try:
                print(f"[{ns}] discarded {store.discard_prepared()} prepared generation(s)")
            finally:
                store.close()
        return 0
    try:
        spec, doc = load_spec(src)
        results = []
        for ns in wanted:
            if not (src / f"{ns}.jsonl").exists():
                print(f"[{ns}] not in the export, skipped")
                continue
            results.append(import_namespace(src, ns, spec, doc, check_n=args.check, min_cosine=args.min_cosine,
                                            skip_check=args.skip_check))
    except ImportCheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not results:
        print("nothing imported")
        return 1
    print("\nImported. The live generations are untouched. To switch, set in the backend's environment:\n")
    for line in env_lines(spec):
        print("  " + line)
    print("\nand restart the backend: it adopts the prepared generations instead of re-embedding, then embeds "
          "only the papers that are missing or changed. To keep the conference explorer on its current model "
          "also set CONFERENCE_EMBED_MODEL to that model.")
    print(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
