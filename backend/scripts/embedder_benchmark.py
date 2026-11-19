"""Compare text-embedding models on a PaperManager library (offline, GPU optional).

Two stages (``--stage``, default ``all``):

  embed  Embed every library paper and every feed candidate with each model and save the unit
         vectors as .npy, with throughput and peak GPU memory per model.
  eval   Score the saved vectors (CPU only, needs numpy; M3 also needs the backend code).

usage:
  python embedder_benchmark.py --data DIR --models bge-small,... --out DIR [--device cuda]
         [--stage embed|eval|all] [--batch 32] [--max-length 512] [--trust-remote-code]
         [--feed-code BACKEND_DIR] [--seeds 0,1,2] [--resume] [--legacy-transformers DIR]

Models are Hugging Face ids; the reference ``BAAI/bge-small-en-v1.5`` is always run first and
through the same code path. Per-model pooling, prefixes and text layout follow the model card
(see ``SPECS``); a model that is not listed gets mean pooling and no prefix, with a warning.
Models that need custom code (``remote_code`` in ``SPECS``) are only run with
``--trust-remote-code``, which executes code from the model repository: pass it deliberately.
Each model runs in its own subprocess. ``--legacy-transformers DIR`` (a directory holding
transformers 4.x, e.g. ``pip install --target DIR``) is put on PYTHONPATH for models flagged
``legacy_tf`` whose custom code does not work with transformers 5. Nothing is written outside ``--out``; Hugging Face downloads go to ``HF_HOME`` as usual.

DATA directory (all read-only, written by an export of the library):
  library.jsonl     one paper per line: id, title, abstract, summary, created_at, rating,
                    bookmarked, status, highlights, mine, in_project, has_text,
                    visible_to_feed_user (bool: part of the feed user's view)
  candidates.jsonl  feed candidates: id, title, abstract, published, source
  cites.json        [[citing_id, cited_id], ...] between library papers
  topics.jsonl      {"id": paper id, "topics": [topic name, ...]}
  meta.json         optional: {"single_user": bool} (how the feed treats ratings; default false)

Embedded text is ``title + "\\n" + abstract[:1500]`` (abstract, else the AI summary), exactly
what services/library_search/semantic.py ``paper_text`` produces; ``paper_parts`` below is a
copy of that function, split in two so models with a [SEP] layout can use title and body.

Metrics (library papers only; "all" = every paper, "text" = only papers with an abstract or
summary, the others have just a title):
  M1  citation-neighbour recall: for each paper with >= 1 CITES edge inside the library, its
      top-10 cosine neighbours (itself excluded); recall@10 = share of its cited and citing
      papers found, hit@10, and MRR of the first cited or citing paper in the full ranking.
      Baseline: 10 random neighbours (seeded).
  M2  topic agreement: mean Jaccard overlap of the topic sets between a paper and its top-10
      neighbours, among papers that have topics. Baseline: 10 random papers (seeded).
  M3  the feed classifier's held-out AUC, with the feed's own code (services.feed.ranking
      ``_entries`` / ``build_training_set`` and services.feed.model ``fit_model``,
      ``fit_logreg``, ``predict``, ``auc``) imported from ``--feed-code``, nothing
      reimplemented: the training set is built from the feed user's visible papers and the
      candidates as random negatives.
        auc_feed   the live feed's number: the 20 % most recently added positives held out
                   (deterministic: the candidate sample is the same every time).
        auc_random the same fit with a random 20 % of the positives held out (``--seeds``).
        auc_clean  random 20 % of positives AND of the random negatives held out (``--seeds``);
                   the feed scores the negatives it trained on, this does not.
  M4  throughput (papers/s over library + candidates, model load excluded, GPU shared with
      whatever else runs) and peak GPU memory (torch allocated / reserved).
"""
from __future__ import annotations

import argparse
import gc
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BASELINE = "BAAI/bge-small-en-v1.5"
TEXT_MAX = 1500          # same cut as semantic.py _TEXT_MAX


# ── text ──────────────────────────────────────────────────────────────────────

_MD = re.compile(r"(^|\s)#{1,6}\s+|\*\*|__|`")
_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    """Collapse whitespace and drop markdown heading/bold/code markers (library_search.query.clean)."""
    return _WS.sub(" ", _MD.sub(r"\1", text or "")).strip()


def paper_parts(title: str | None, abstract: str | None, summary: str | None) -> tuple[str, str]:
    """(title, body): the body is the abstract or, failing that, the cleaned summary, cut to 1500."""
    body = (abstract or "").strip() or clean(summary or "")
    return (title or "").strip(), body[:TEXT_MAX]


def paper_text(title: str | None, abstract: str | None, summary: str | None) -> str:
    """The text a paper is embedded by (copy of library_search.semantic.paper_text)."""
    t, body = paper_parts(title, abstract, summary)
    return (t + "\n" + body).strip()


# ── model table ───────────────────────────────────────────────────────────────

@dataclass
class Spec:
    pooling: str = "mean"            # cls | mean | last
    prefix: str = ""                 # prepended to every document
    layout: str = "newline"          # newline: title\nbody | sep: title [SEP] body | pair: tokenizer(title, body)
    remote_code: bool = False
    legacy_tf: bool = False          # custom code written for transformers 4: run with --legacy-transformers
    padding_side: str | None = None
    licence: str = ""
    note: str = ""


SPECS: dict[str, Spec] = {
    "BAAI/bge-small-en-v1.5": Spec("cls", licence="MIT", note="no query instruction for documents"),
    "BAAI/bge-base-en-v1.5": Spec("cls", licence="MIT"),
    "BAAI/bge-large-en-v1.5": Spec("cls", licence="MIT"),
    "BAAI/bge-m3": Spec("cls", licence="MIT", note="dense head only"),
    "Alibaba-NLP/gte-large-en-v1.5": Spec("cls", remote_code=True, legacy_tf=True, licence="Apache-2.0"),
    "nomic-ai/nomic-embed-text-v1.5": Spec("mean", prefix="search_document: ", remote_code=True, legacy_tf=True,
                                           licence="Apache-2.0", note="search_document: prefix on all texts"),
    "allenai/specter2_base": Spec("cls", layout="sep", licence="Apache-2.0",
                                  note="base model, no adapters; title [SEP] abstract"),
    "malteos/scincl": Spec("cls", layout="sep", licence="MIT", note="title [SEP] abstract"),
    "ncbi/MedCPT-Article-Encoder": Spec("cls", layout="pair", licence="public domain (license: other)",
                                        note="biomedical; (title, abstract) pair"),
    "google/embeddinggemma-300m": Spec("mean", prefix="title: none | text: ", licence="Gemma terms (gated)",
                                       note="document prompt of the model card"),
    "Qwen/Qwen3-Embedding-0.6B": Spec("last", padding_side="left", licence="Apache-2.0",
                                      note="last-token pooling, no instruction for documents"),
    "Qwen/Qwen3-Embedding-4B": Spec("last", padding_side="left", licence="Apache-2.0"),
    "J0nasW/sciembed-full": Spec("mean", licence="MIT", note="SciEmbed headline model (ModernBERT-base)"),
    "J0nasW/sciembed-ctx": Spec("mean", licence="MIT"),
    "J0nasW/sciembed-ctx-2048": Spec("mean", licence="MIT", note="SciEmbed, 2048-token variant"),
    "J0nasW/sciembed-ctx-8192": Spec("mean", licence="MIT", note="SciEmbed, 8192-token variant"),
}


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", model)


def model_text(spec: Spec, title: str, body: str, sep_token: str) -> str | tuple[str, str]:
    if spec.layout == "pair":
        return (title, body) if body else title
    if spec.layout == "sep":
        return f"{title}{sep_token}{body}" if body else title
    return spec.prefix + (title + "\n" + body).strip()


# ── data ──────────────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_data(d: Path) -> dict:
    lib = read_jsonl(d / "library.jsonl")
    cands = read_jsonl(d / "candidates.jsonl")
    cites = json.loads((d / "cites.json").read_text())
    topics = {r["id"]: r["topics"] for r in read_jsonl(d / "topics.jsonl")}
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    return {"lib": lib, "cands": cands, "cites": cites, "topics": topics, "meta": meta}


# ── embedding ─────────────────────────────────────────────────────────────────

def pool(hidden, mask, how: str, torch):
    if how == "cls":
        return hidden[:, 0]
    if how == "mean":
        m = mask.unsqueeze(-1).to(hidden.dtype)
        return (hidden * m).sum(1) / m.sum(1).clamp(min=1)
    left = bool((mask[:, -1] == 1).all())
    if left:
        return hidden[:, -1]
    idx = mask.sum(1) - 1
    return hidden[torch.arange(hidden.shape[0], device=hidden.device), idx]


def embed_texts(model, tok, texts: list, spec: Spec, device: str, batch: int, max_length: int, torch):
    """Unit vectors (float32, original order). Length-sorted batches; the batch size halves on OOM."""
    sizes = [len(t) if isinstance(t, str) else len(t[0]) + len(t[1]) for t in texts]
    order = sorted(range(len(texts)), key=lambda i: -sizes[i])
    out = [None] * len(texts)
    i, bs = 0, batch
    while i < len(order):
        idx = order[i:i + bs]
        chunk = [texts[j] for j in idx]
        try:
            if chunk and isinstance(chunk[0], tuple):
                enc = tok([c[0] for c in chunk], [c[1] for c in chunk], truncation=True, padding=True,
                          max_length=max_length, return_tensors="pt")
            else:
                enc = tok(chunk, truncation=True, padding=True, max_length=max_length, return_tensors="pt")
            enc = {k: v.to(device) for k, v in enc.items() if k in ("input_ids", "attention_mask", "token_type_ids")}
            with torch.no_grad():
                h = model(**enc).last_hidden_state
                v = pool(h, enc["attention_mask"], spec.pooling, torch).float()
                v = torch.nn.functional.normalize(v, p=2, dim=1).cpu().numpy()
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if bs == 1:
                raise
            bs = max(1, bs // 2)
            print(f"    OOM: batch size now {bs}", flush=True)
            continue
        for j, row in zip(idx, v):
            out[j] = row
        i += len(idx)
    return np.vstack(out).astype(np.float32), bs


def run_embed(args, data: dict, out: Path) -> dict:
    import torch
    from transformers import AutoModel, AutoTokenizer

    lib_parts = [paper_parts(r.get("title"), r.get("abstract"), r.get("summary")) for r in data["lib"]]
    cand_parts = [paper_parts(r.get("title"), r.get("abstract"), None) for r in data["cands"]]
    all_parts = lib_parts + cand_parts
    n_lib = len(lib_parts)
    infos: dict = {}
    for name in args.models:
        sl = slug(name)
        vdir = out / "vectors" / sl
        info_p = out / f"embed_{sl}.json"
        if args.resume and (vdir / "library.npy").exists() and info_p.exists():
            infos[name] = json.loads(info_p.read_text())
            print(f"[{name}] resume: vectors exist", flush=True)
            continue
        spec = SPECS.get(name)
        if spec is None:
            print(f"[{name}] not in SPECS: mean pooling, no prefix", flush=True)
            spec = Spec()
        info: dict = {"model": name, "licence": spec.licence, "note": spec.note, "pooling": spec.pooling,
                      "prefix": spec.prefix, "layout": spec.layout, "max_length": args.max_length}
        if spec.remote_code and not args.trust_remote_code:
            info["skipped"] = "needs trust_remote_code; run with --trust-remote-code to allow it"
            infos[name] = info
            info_p.write_text(json.dumps(info, indent=1))
            print(f"[{name}] skipped: {info['skipped']}", flush=True)
            continue
        info["trust_remote_code"] = spec.remote_code
        model = tok = None
        try:
            t0 = time.time()
            tok = AutoTokenizer.from_pretrained(name, trust_remote_code=spec.remote_code)
            if spec.padding_side:
                tok.padding_side = spec.padding_side
            sep = f" {tok.sep_token} " if tok.sep_token else "\n"
            texts = [model_text(spec, t, b, sep) for t, b in all_parts]
            used = None
            for dtype_name in ("float16", "bfloat16"):
                if model is not None:
                    del model
                    gc.collect()
                    torch.cuda.empty_cache()
                dt = getattr(torch, dtype_name) if args.device.startswith("cuda") else torch.float32
                try:
                    model = AutoModel.from_pretrained(name, trust_remote_code=spec.remote_code, dtype=dt)
                except TypeError:
                    model = AutoModel.from_pretrained(name, trust_remote_code=spec.remote_code, torch_dtype=dt)
                model = model.to(args.device).eval()
                info["params"] = int(sum(p.numel() for p in model.parameters()))
                info["load_seconds"] = round(time.time() - t0, 1)
                if args.device.startswith("cuda"):
                    torch.cuda.reset_peak_memory_stats()
                # warm-up, then the timed pass over everything
                embed_texts(model, tok, texts[:16], spec, args.device, args.batch, args.max_length, torch)
                if args.device.startswith("cuda"):
                    torch.cuda.synchronize()
                t1 = time.time()
                vecs, bs = embed_texts(model, tok, texts, spec, args.device, args.batch, args.max_length, torch)
                if args.device.startswith("cuda"):
                    torch.cuda.synchronize()
                secs = time.time() - t1
                used = dtype_name if args.device.startswith("cuda") else "float32"
                if np.isfinite(vecs).all():
                    break
                print(f"    non-finite vectors in {dtype_name}", flush=True)
                if not args.device.startswith("cuda"):
                    raise RuntimeError("non-finite vectors")
            else:
                raise RuntimeError("non-finite vectors in fp16 and bf16")
            info.update(dtype=used, dim=int(vecs.shape[1]), seconds=round(secs, 2), final_batch=bs,
                        papers_per_s=round(len(texts) / secs, 1), n_embedded=len(texts))
            if args.device.startswith("cuda"):
                info["peak_alloc_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
                info["peak_reserved_mb"] = round(torch.cuda.max_memory_reserved() / 2**20)
            vdir.mkdir(parents=True, exist_ok=True)
            np.save(vdir / "library.npy", vecs[:n_lib])
            np.save(vdir / "candidates.npy", vecs[n_lib:])
            print(f"[{name}] dim {info['dim']} {info['papers_per_s']} papers/s "
                  f"peak {info.get('peak_alloc_mb')} MB ({used})", flush=True)
        except Exception as exc:  # noqa: BLE001 — a model that fails is skipped with the reason
            info["skipped"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            print(f"[{name}] FAILED: {info['skipped']}", flush=True)
        finally:
            del model, tok
            gc.collect()
            if args.device.startswith("cuda"):
                torch.cuda.empty_cache()
        infos[name] = info
        info_p.write_text(json.dumps(info, indent=1))
    return infos


# ── metrics ───────────────────────────────────────────────────────────────────

def topk(sim: np.ndarray, k: int = 10) -> np.ndarray:
    """Indices of the k largest per row (diagonal must already be -inf)."""
    part = np.argpartition(-sim, k, axis=1)[:, :k]
    rows = np.arange(sim.shape[0])[:, None]
    return part[rows, np.argsort(-sim[rows, part], axis=1)]


def metric_m1(X: np.ndarray, ids: list[str], cites: list, seeds: list[int], k: int = 10) -> dict:
    pos = {p: i for i, p in enumerate(ids)}
    nb: dict[int, set[int]] = {}
    for a, b in cites:
        if a in pos and b in pos and a != b:
            nb.setdefault(pos[a], set()).add(pos[b])
            nb.setdefault(pos[b], set()).add(pos[a])
    q = sorted(nb)
    if not q:
        return {"n": 0}
    sim = X @ X.T
    np.fill_diagonal(sim, -np.inf)
    top = topk(sim, k)
    rec, hit, rr = [], [], []
    for i in q:
        found = len(nb[i] & set(top[i].tolist()))
        rec.append(found / len(nb[i]))
        hit.append(found > 0)
        # rank of the first neighbour in the full ranking
        s = sim[i]
        best = max(s[j] for j in nb[i])
        rr.append(1.0 / (1 + int((s > best).sum())))
    n = X.shape[0]
    rand = []
    for sd in seeds:
        rng = np.random.default_rng(sd)
        r = []
        for i in q:
            cand = rng.choice(n - 1, size=k, replace=False)
            cand = cand + (cand >= i)            # skip the paper itself
            r.append(len(nb[i] & set(cand.tolist())) / len(nb[i]))
        rand.append(float(np.mean(r)))
    return {"n": len(q), "recall10": float(np.mean(rec)), "hit10": float(np.mean(hit)), "mrr": float(np.mean(rr)),
            "random_recall10": float(np.mean(rand)), "random_recall10_sd": float(np.std(rand))}


def jaccard(a: set, b: set) -> float:
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def metric_m2(X: np.ndarray, ids: list[str], topics: dict, seeds: list[int], k: int = 10) -> dict:
    keep = [i for i, p in enumerate(ids) if topics.get(p)]
    if len(keep) <= k + 1:
        return {"n": 0}
    Y = X[keep]
    sets = [set(topics[ids[i]]) for i in keep]
    sim = Y @ Y.T
    np.fill_diagonal(sim, -np.inf)
    top = topk(sim, k)
    got = float(np.mean([np.mean([jaccard(sets[i], sets[j]) for j in top[i]]) for i in range(len(keep))]))
    n = len(keep)
    rand = []
    for sd in seeds:
        rng = np.random.default_rng(sd)
        r = []
        for i in range(n):
            c = rng.choice(n - 1, size=k, replace=False)
            c = c + (c >= i)
            r.append(np.mean([jaccard(sets[i], sets[j]) for j in c]))
        rand.append(float(np.mean(r)))
    return {"n": n, "jaccard": got, "random_jaccard": float(np.mean(rand)), "random_jaccard_sd": float(np.std(rand))}


def m3_setup(feed_code: Path, data: dict):
    """The feed's own training set for the feed user, with embeddings supplied from memory."""
    sys.path.insert(0, str(feed_code))
    from services.feed import model as fm            # noqa: E402
    from services.feed import ranking                # noqa: E402

    rows = [{"id": r["id"], "rating": r.get("rating"), "bookmarked": r.get("bookmarked"),
             "status": r.get("status"), "highlights": r.get("highlights"), "mine": r.get("mine"),
             "in_project": r.get("in_project"), "stub": False, "has_text": r.get("has_text"),
             "created_at": r.get("created_at")}
            for r in data["lib"] if r.get("visible_to_feed_user")]
    single = bool(data["meta"].get("single_user", False))
    pos, neg = ranking._entries(rows, single, {})
    return fm, ranking, pos, neg


class MemStore:
    """The three FeedStore methods build_training_set calls, over in-memory candidate vectors."""

    def __init__(self, cand_ids: list[str], cand_vecs: np.ndarray):
        self.order = sorted(range(len(cand_ids)), key=lambda i: cand_ids[i])
        self.ids, self.vecs = cand_ids, cand_vecs

    def get_embeddings(self, ids):
        return {}

    def labels(self, user):
        return {}

    def sample_embeddings(self, exclude, n, seed=0):            # same rule as FeedStore.sample_embeddings
        vecs = [self.vecs[i] for i in self.order if self.ids[i] not in exclude]
        if len(vecs) > n:
            idx = np.random.default_rng(seed).choice(len(vecs), size=n, replace=False)
            vecs = [vecs[i] for i in sorted(idx)]
        return np.vstack(vecs).astype(np.float32)


def metric_m3(feed_code: Path, data: dict, lib_vecs: np.ndarray, cand_vecs: np.ndarray, seeds: list[int]) -> dict:
    fm, ranking, pos, neg = m3_setup(feed_code, data)
    # model.stack() builds an empty (0, 384) block when a list is empty (no explicit negatives);
    # pass this model's width without touching the feed code.
    orig_stack = fm.stack
    fm.stack = lambda rows, dim=lib_vecs.shape[1]: orig_stack(rows, dim)
    try:
        return _metric_m3(fm, ranking, pos, neg, data, lib_vecs, cand_vecs, seeds)
    finally:
        fm.stack = orig_stack


def _metric_m3(fm, ranking, pos, neg, data, lib_vecs, cand_vecs, seeds) -> dict:
    lib_vec = {r["id"]: lib_vecs[i] for i, r in enumerate(data["lib"])}
    store = MemStore([r["id"] for r in data["cands"]], cand_vecs)
    ts = ranking.build_training_set(store, pos, neg, lib_vec, "", "user")
    res: dict = {"positives": len(ts.pos), "negatives": len(ts.neg), "random_negatives": len(ts.random_neg)}
    if len(ts.pos) < fm.EVAL_MIN_POSITIVES or len(ts.random_neg) < 10:
        res["note"] = "too few positives for a held-out AUC"
        return res
    m = fm.fit_model(ts)                                          # the live feed's number
    res["auc_feed"] = m.quality["auc"] if m.quality else None
    res["held_out_feed"] = m.quality["held_out"] if m.quality else None
    rand, clean_ = [], []
    P, R = len(ts.pos), len(ts.random_neg)
    for sd in seeds:
        rng = np.random.default_rng(sd)
        perm = rng.permutation(P)
        k = max(1, int(round(fm.HOLD_OUT * P)))
        held, kept = perm[:k], perm[k:]
        # (a) random positive hold-out, negatives as the feed trains and scores them
        sub = fm.TrainingSet(ts.pos[kept], ts.pos_weight[kept], [ts.pos_time[i] for i in kept],
                             ts.neg, ts.neg_weight, ts.random_neg)
        X, y, w = fm.design_matrix(sub)
        th, b = fm.fit_logreg(X, y, w)
        rand.append(fm.auc(fm.predict(th, b, ts.pos[held]), fm.predict(th, b, ts.random_neg)))
        # (b) positives and random negatives both split
        rp = rng.permutation(R)
        kr = max(1, int(round(fm.HOLD_OUT * R)))
        rh, rk = rp[:kr], rp[kr:]
        sub = fm.TrainingSet(ts.pos[kept], ts.pos_weight[kept], [ts.pos_time[i] for i in kept],
                             ts.neg, ts.neg_weight, ts.random_neg[rk])
        X, y, w = fm.design_matrix(sub)
        th, b = fm.fit_logreg(X, y, w)
        clean_.append(fm.auc(fm.predict(th, b, ts.pos[held]), fm.predict(th, b, ts.random_neg[rh])))
    res["auc_random"] = float(np.mean(rand))
    res["auc_random_sd"] = float(np.std(rand))
    res["auc_clean"] = float(np.mean(clean_))
    res["auc_clean_sd"] = float(np.std(clean_))
    return res


def run_eval(args, data: dict, out: Path, infos: dict) -> dict:
    seeds = [int(s) for s in args.seeds.split(",")]
    ids = [r["id"] for r in data["lib"]]
    text_mask = np.array([bool(r.get("has_text")) for r in data["lib"]])
    text_ids = [p for p, m in zip(ids, text_mask) if m]
    text_set = set(text_ids)
    text_cites = [e for e in data["cites"] if e[0] in text_set and e[1] in text_set]
    results: dict = {}
    for name in args.models:
        vdir = out / "vectors" / slug(name)
        if not (vdir / "library.npy").exists():
            continue
        X = np.load(vdir / "library.npy")
        C = np.load(vdir / "candidates.npy")
        r = {"m1_all": metric_m1(X, ids, data["cites"], seeds),
             "m1_text": metric_m1(X[text_mask], text_ids, text_cites, seeds),
             "m2_all": metric_m2(X, ids, data["topics"], seeds),
             "m2_text": metric_m2(X[text_mask], text_ids, {p: data["topics"].get(p) for p in text_ids}, seeds)}
        if args.feed_code:
            try:
                r["m3"] = metric_m3(Path(args.feed_code), data, X, C, seeds)
            except Exception as exc:  # noqa: BLE001
                r["m3"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        else:
            r["m3"] = {"note": "no --feed-code given"}
        r["info"] = infos.get(name) or (json.loads((out / f"embed_{slug(name)}.json").read_text())
                                        if (out / f"embed_{slug(name)}.json").exists() else {})
        results[name] = r
        print(f"[{name}] M1 all recall@10 {r['m1_all'].get('recall10', float('nan')):.3f} "
              f"M2 all {r['m2_all'].get('jaccard', float('nan')):.3f} "
              f"M3 feed {r['m3'].get('auc_feed')} clean {r['m3'].get('auc_clean')}", flush=True)
    return results


def table(results: dict, model_order: list[str]) -> str:
    def f(x, n=3):
        return "-" if x is None else f"{x:.{n}f}"
    head = ("| model | params (M) | dim | M1 R@10 all / text | M1 MRR all / text | M2 Jaccard all / text "
            "| M3 AUC feed | M3 AUC random (sd) | M3 AUC clean (sd) | papers/s | peak MB |")
    lines = [head, "|" + "---|" * 11]
    for name in model_order:
        if name not in results:
            continue
        r, i = results[name], results[name]["info"]
        m3 = r["m3"]
        lines.append("| " + " | ".join([
            name, f((i.get("params") or 0) / 1e6, 0), str(i.get("dim", "-")),
            f"{f(r['m1_all'].get('recall10'))} / {f(r['m1_text'].get('recall10'))}",
            f"{f(r['m1_all'].get('mrr'))} / {f(r['m1_text'].get('mrr'))}",
            f"{f(r['m2_all'].get('jaccard'))} / {f(r['m2_text'].get('jaccard'))}",
            f(m3.get("auc_feed")),
            f"{f(m3.get('auc_random'))} ({f(m3.get('auc_random_sd'))})",
            f"{f(m3.get('auc_clean'))} ({f(m3.get('auc_clean_sd'))})",
            str(i.get("papers_per_s", "-")), str(i.get("peak_alloc_mb", "-"))]) + " |")
    ref = results.get(BASELINE)
    if ref:
        a, b = ref["m1_all"], ref["m2_all"]
        lines.append(f"\nRandom baselines (all papers): M1 recall@10 {f(a.get('random_recall10'))}, "
                     f"M2 Jaccard {f(b.get('random_jaccard'))}; M1 n={a.get('n')}, M2 n={b.get('n')}.")
    return "\n".join(lines)


def run_isolated(args, out: Path) -> dict:
    """One subprocess per model: a CUDA fault or a hanging custom-code model cannot take the others
    down, and every model gets a fresh allocator (clean peak-memory numbers)."""
    import os
    import subprocess

    for name in args.models:
        cmd = [sys.executable, str(Path(__file__).resolve()), "--data", args.data, "--out", args.out,
               "--device", args.device, "--stage", "embed", "--batch", str(args.batch),
               "--max-length", str(args.max_length), "--child", "--models", name]
        for flag in ("trust_remote_code", "resume"):
            if getattr(args, flag):
                cmd.append("--" + flag.replace("_", "-"))
        env = dict(os.environ)
        spec = SPECS.get(name)
        if spec and spec.legacy_tf and args.legacy_transformers:
            env["PYTHONPATH"] = args.legacy_transformers + os.pathsep + env.get("PYTHONPATH", "")
        rc = subprocess.run(cmd, env=env).returncode
        if rc != 0 and not (out / f"embed_{slug(name)}.json").exists():
            (out / f"embed_{slug(name)}.json").write_text(json.dumps(
                {"model": name, "skipped": f"subprocess exited with code {rc}"}, indent=1))
    infos = {}
    for name in args.models:
        p = out / f"embed_{slug(name)}.json"
        if p.exists():
            infos[name] = json.loads(p.read_text())
    return infos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", required=True, help="comma-separated Hugging Face ids")
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--stage", choices=("embed", "eval", "all"), default="all")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--max-length", type=int, default=512)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--feed-code", help="backend directory holding services/feed (enables M3)")
    ap.add_argument("--trust-remote-code", action="store_true",
                    help="allow models whose repository ships custom code (executes it)")
    ap.add_argument("--resume", action="store_true", help="skip models whose vectors already exist")
    ap.add_argument("--legacy-transformers", help="directory with transformers 4.x (prepended to PYTHONPATH) "
                    "for models whose custom code needs it")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    listed = [m.strip() for m in args.models.split(",") if m.strip()]
    args.models = listed if args.child else list(dict.fromkeys([BASELINE] + listed))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = load_data(Path(args.data))
    print(f"library {len(data['lib'])}, candidates {len(data['cands'])}, cites {len(data['cites'])}", flush=True)
    infos: dict = {}
    if args.stage in ("embed", "all"):
        if args.child:
            infos = run_embed(args, data, out)
        else:
            infos = run_isolated(args, out)
    if args.stage in ("eval", "all"):
        results = run_eval(args, data, out, infos)
        (out / "metrics.json").write_text(json.dumps(results, indent=1))
        md = table(results, args.models)
        (out / "metrics.md").write_text(md + "\n")
        print(md)


if __name__ == "__main__":
    main()
