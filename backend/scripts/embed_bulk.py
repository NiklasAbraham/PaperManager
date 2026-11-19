#!/usr/bin/env python
"""Embed the texts of a ``vectors_export.py`` directory on any machine that has torch + transformers.

Self-contained on purpose: this one file and the export directory are all a GPU machine needs, no
PaperManager code and no database. It reproduces what the backend's CPU embedder
(``services/conferences/embedder.py``, function ``embed``) does, so the vectors made here sit in the
same space as the ones the backend makes later for new papers (``test_bulk_embed_embed.py`` keeps the
two equal):

  * the document prefix of ``spec.json`` is put in front of every text, then an empty text becomes " "
  * tokenised with padding and truncation to ``max_length`` tokens (default 256, as the backend)
  * last hidden state pooled as ``spec.json`` says (``cls`` or ``mean`` over the attention mask)
  * L2-normalised, stored as float32

Differences that do not change the result beyond rounding: texts are processed longest first, in
batches whose size halves when the GPU runs out of memory, and the model runs in float16 on a CUDA
device (pooling and normalisation in float32). Vectors with NaN in float16 are recomputed in float32.
``scripts/vectors_import.py`` checks a sample against the CPU embedder (mean cosine >= 0.98).

usage:
  python embed_bulk.py DIR [--out DIR2] [--namespaces library,feed,feed_library]
                       [--device auto|cuda|cuda:1|cpu] [--dtype auto|fp16|fp32] [--batch 64]
                       [--max-length N] [--model PATH_OR_ID] [--cache-dir DIR] [--offline] [--force]

DIR holds ``spec.json`` and ``<namespace>.jsonl`` (one ``{"id": ..., "text": ...}`` per line). For each
namespace this writes ``<namespace>.npy`` (float32, ``(count, dim)``, rows in file order) and
``<namespace>.ids.json`` (the ids, same order) into ``--out`` (default DIR), plus
``<namespace>.done.json``. A namespace whose three files exist and match the current texts and spec is
skipped, so an interrupted run continues where it stopped; ``--force`` embeds again. Files are written
to a temporary name and renamed, so a killed run leaves nothing half written.

Needs: torch, transformers (>= 4.48 for ModernBERT models), numpy. Models load without
``trust_remote_code``. ``--model`` loads from a local directory or another id than ``spec.json`` names
(the spec's pooling, prefix and dimension still apply), ``--offline`` never contacts the model hub.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

DEFAULT_MAX_LENGTH = 256
NAMESPACES = ("library", "feed", "feed_library")


# ── the embedding function (keep equal to services/conferences/embedder.py: ``embed``) ────────────

def pool(hidden, mask, how: str):
    """CLS or mean pooling over the attention mask, in float32."""
    hidden = hidden.float()
    if how == "mean":
        m = mask.unsqueeze(-1).to(hidden.dtype)
        return (hidden * m).sum(dim=1) / m.sum(dim=1).clamp(min=1e-9)
    return hidden[:, 0]


def _is_oom(exc: BaseException, torch) -> bool:
    oom = getattr(torch.cuda, "OutOfMemoryError", None)
    return (oom is not None and isinstance(exc, oom)) or "out of memory" in str(exc).lower()


def embed_texts(texts: list[str], tok, model, *, pooling: str, dim: int, doc_prefix: str = "",
                max_length: int = DEFAULT_MAX_LENGTH, batch: int = 64, device: str = "cpu",
                progress=None, log=print) -> np.ndarray:
    """Unit-length float32 vectors, shape ``(len(texts), dim)``, rows in the order of ``texts``.
    Longest texts first; the batch size halves on a CUDA out-of-memory error and stays smaller."""
    import torch

    if doc_prefix:
        texts = [doc_prefix + t for t in texts]
    out = np.zeros((len(texts), dim), dtype=np.float32)
    order = sorted(range(len(texts)), key=lambda i: -len(texts[i]))
    pos, bs, done = 0, max(1, batch), 0
    while pos < len(order):
        idx = order[pos:pos + bs]
        try:
            enc = tok([texts[i] or " " for i in idx], padding=True, truncation=True,
                      max_length=max_length, return_tensors="pt")
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.inference_mode():
                hidden = model(**enc).last_hidden_state
                pooled = pool(hidden, enc["attention_mask"], pooling)
                if pooled.shape[1] != dim:
                    raise RuntimeError(f"the model produces {pooled.shape[1]}-dim vectors but spec.json says {dim}")
                vec = torch.nn.functional.normalize(pooled, dim=-1).cpu().numpy()
        except Exception as exc:  # noqa: BLE001 — only a CUDA OOM is retried
            if not _is_oom(exc, torch) or bs == 1:
                raise
            if device.startswith("cuda"):
                torch.cuda.empty_cache()
            bs = max(1, bs // 2)
            log(f"    out of memory: batch size now {bs}")
            continue
        out[idx] = vec
        pos += len(idx)
        done += len(idx)
        if progress:
            progress(done, len(texts))
    return out


# ── files ──────────────────────────────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> tuple[list[str], list[str]]:
    ids, texts = [], []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                ids.append(str(rec["id"]))
                texts.append(str(rec.get("text") or ""))
            except (ValueError, KeyError, TypeError) as exc:
                raise SystemExit(f"{path}:{n}: not a {{\"id\": ..., \"text\": ...}} line ({exc})") from exc
    if len(set(ids)) != len(ids):
        raise SystemExit(f"{path}: duplicate ids")
    return ids, texts


def fingerprint(ids: list[str], texts: list[str], spec: dict, max_length: int) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([spec.get("model"), spec.get("dim"), spec.get("pooling"), spec.get("doc_prefix", ""),
                         max_length], sort_keys=True).encode())
    for i, t in zip(ids, texts):
        h.update(b"\0" + i.encode() + b"\0" + t.encode())
    return h.hexdigest()


def _write_atomic(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        write(f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def is_done(out_dir: Path, ns: str, fp: str) -> bool:
    try:
        done = json.loads((out_dir / f"{ns}.done.json").read_text(encoding="utf-8"))
        return done.get("fingerprint") == fp and (out_dir / f"{ns}.npy").exists() \
            and (out_dir / f"{ns}.ids.json").exists()
    except (OSError, ValueError):
        return False


def save_namespace(out_dir: Path, ns: str, ids: list[str], vectors: np.ndarray, fp: str, info: dict) -> None:
    _write_atomic(out_dir / f"{ns}.npy", lambda f: np.save(f, vectors.astype(np.float32)))
    _write_atomic(out_dir / f"{ns}.ids.json", lambda f: f.write(json.dumps(ids).encode()))
    _write_atomic(out_dir / f"{ns}.done.json", lambda f: f.write(json.dumps(
        {"fingerprint": fp, "count": len(ids), **info}, indent=1).encode()))


# ── model ──────────────────────────────────────────────────────────────────────────────────────

def load_model(name: str, device: str, dtype: str, cache_dir: str | None, offline: bool):
    """``(tokenizer, model, dtype name)``; the model on ``device`` in eval mode."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    kw = {"trust_remote_code": False}
    if cache_dir:
        kw["cache_dir"] = cache_dir
    if offline:
        kw["local_files_only"] = True
    tok = AutoTokenizer.from_pretrained(name, **kw)
    use16 = dtype == "fp16" or (dtype == "auto" and device.startswith("cuda"))
    want = torch.float16 if use16 else torch.float32
    try:
        model = AutoModel.from_pretrained(name, dtype=want, **kw)
    except TypeError:               # older transformers call it torch_dtype
        model = AutoModel.from_pretrained(name, torch_dtype=want, **kw)
    return tok, model.to(device).eval(), ("fp16" if use16 else "fp32")


# ── main ───────────────────────────────────────────────────────────────────────────────────────

def pick_device(wanted: str) -> str:
    if wanted != "auto":
        return wanted
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def run(args) -> int:
    src = Path(args.dir)
    out_dir = Path(args.out) if args.out else src
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        spec = json.loads((src / "spec.json").read_text(encoding="utf-8"))
        for key in ("model", "dim", "pooling"):
            spec[key]
    except (OSError, ValueError, KeyError) as exc:
        print(f"{src}/spec.json is missing or incomplete ({exc!r}); run vectors_export.py first", file=sys.stderr)
        return 2
    if spec["pooling"] not in ("cls", "mean"):
        print(f"unknown pooling {spec['pooling']!r} in spec.json", file=sys.stderr)
        return 2
    max_length = args.max_length or int(spec.get("max_length") or DEFAULT_MAX_LENGTH)
    wanted = [n.strip() for n in args.namespaces.split(",") if n.strip()]
    todo: list[tuple[str, list[str], list[str], str]] = []
    for ns in wanted:
        path = src / f"{ns}.jsonl"
        if not path.exists():
            print(f"[{ns}] no {path.name}, skipped")
            continue
        ids, texts = read_jsonl(path)
        fp = fingerprint(ids, texts, spec, max_length)
        if not args.force and is_done(out_dir, ns, fp):
            print(f"[{ns}] already embedded ({len(ids)} vectors), skipped (use --force to redo)")
            continue
        todo.append((ns, ids, texts, fp))
    if not todo:
        print("nothing to do")
        return 0
    device = pick_device(args.device)
    model_name = args.model or spec["model"]
    print(f"model {model_name}  dim {spec['dim']}  pooling {spec['pooling']}  max_length {max_length}  device {device}",
          flush=True)
    t0 = time.time()
    tok, model, dtype = load_model(model_name, device, args.dtype, args.cache_dir, args.offline)
    print(f"loaded in {time.time() - t0:.1f}s as {dtype}", flush=True)
    for ns, ids, texts, fp in todo:
        t1 = time.time()
        last = [0.0]

        def progress(done, total, ns=ns, last=last):
            if time.time() - last[0] > 5 or done == total:
                last[0] = time.time()
                print(f"[{ns}] {done}/{total}", flush=True)

        kw = dict(pooling=spec["pooling"], dim=int(spec["dim"]), doc_prefix=spec.get("doc_prefix", ""),
                  max_length=max_length, batch=args.batch, device=device, progress=progress)
        vecs = embed_texts(texts, tok, model, **kw) if texts else np.zeros((0, int(spec["dim"])), np.float32)
        used = dtype
        if not np.isfinite(vecs).all():
            if dtype == "fp32":
                print(f"[{ns}] NaN or infinity in the vectors", file=sys.stderr)
                return 1
            print(f"[{ns}] non-finite values in {dtype}: embedding again in fp32", flush=True)
            tok, model, dtype = load_model(model_name, device, "fp32", args.cache_dir, args.offline)
            used = dtype                # the remaining namespaces stay in fp32
            vecs = embed_texts(texts, tok, model, **kw)
            if not np.isfinite(vecs).all():
                print(f"[{ns}] NaN or infinity in the vectors even in fp32", file=sys.stderr)
                return 1
        secs = time.time() - t1
        save_namespace(out_dir, ns, ids, vecs, fp, {"model": spec["model"], "dim": int(spec["dim"]),
                                                   "dtype": used, "device": device, "max_length": max_length,
                                                   "seconds": round(secs, 1)})
        rate = len(ids) / secs if secs > 0 else 0
        print(f"[{ns}] done: {len(ids)} vectors in {secs:.1f}s ({rate:.0f}/s) -> {out_dir}/{ns}.npy", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Embed a vectors_export.py directory (torch + transformers only).")
    ap.add_argument("dir", help="directory with spec.json and <namespace>.jsonl")
    ap.add_argument("--out", help="where to write <namespace>.npy and .ids.json (default: DIR)")
    ap.add_argument("--namespaces", default=",".join(NAMESPACES))
    ap.add_argument("--device", default="auto", help="auto, cpu, cuda, cuda:1 ... (default auto)")
    ap.add_argument("--dtype", default="auto", choices=("auto", "fp16", "fp32"),
                    help="auto: fp16 on CUDA, fp32 on CPU")
    ap.add_argument("--batch", type=int, default=64, help="starting batch size; halves on out-of-memory")
    ap.add_argument("--max-length", type=int, default=0, help="tokens per text (default: spec.json, else 256)")
    ap.add_argument("--model", help="load this local directory or model id instead of spec.json's model")
    ap.add_argument("--cache-dir", help="Hugging Face cache directory")
    ap.add_argument("--offline", action="store_true", help="never contact the model hub")
    ap.add_argument("--force", action="store_true", help="embed again even if the outputs are current")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
