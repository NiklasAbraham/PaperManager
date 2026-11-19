"""embed_bulk.py: the same vectors as the backend's CPU embedder, adaptive batches, resumable output.
A tiny random ModernBERT written to a temporary directory stands in for the real model; nothing is downloaded."""
from __future__ import annotations

import json

import numpy as np
import pytest

from services.conferences import embedder
from services.vectorstore import model_config
from tests.bulk_embed_helpers import DIM, TEXTS, load_script, use_tiny_model

bulk = load_script("embed_bulk")


def _bulk_vectors(model: str, texts, *, pooling, doc_prefix="", max_length=256, batch=4, device="cpu"):
    tok, m, dtype = bulk.load_model(model, device, "fp32", None, True)
    assert dtype == "fp32"
    return bulk.embed_texts(texts, tok, m, pooling=pooling, dim=DIM, doc_prefix=doc_prefix, max_length=max_length,
                            batch=batch, device=device, log=lambda *_: None)


@pytest.mark.parametrize("pooling, prefix", [("mean", ""), ("cls", ""), ("mean", "passage: ")])
def test_embed_bulk_matches_the_live_embedder(monkeypatch, tmp_path, pooling, prefix):
    model = use_tiny_model(monkeypatch, tmp_path, pooling=pooling, doc_prefix=prefix)
    live = embedder.embed(TEXTS)
    mine = _bulk_vectors(model, TEXTS, pooling=pooling, doc_prefix=prefix)
    assert live.shape == mine.shape == (len(TEXTS), DIM) and mine.dtype == np.float32
    assert np.allclose(np.linalg.norm(mine, axis=1), 1.0, atol=1e-5)
    assert np.abs(live - mine).max() < 1e-5
    assert np.allclose(np.einsum("ij,ij->i", live, mine), 1.0, atol=1e-5)


def test_truncation_and_batch_size_do_not_change_the_result(monkeypatch, tmp_path):
    model = use_tiny_model(monkeypatch, tmp_path)
    live = embedder.embed(TEXTS, max_length=8)
    for batch in (1, 3, 64):
        assert np.abs(live - _bulk_vectors(model, TEXTS, pooling="mean", max_length=8, batch=batch)).max() < 1e-5
    # the cut matters: a longer window gives other vectors for the long texts
    assert np.abs(live - _bulk_vectors(model, TEXTS, pooling="mean", max_length=256)).max() > 1e-3


def test_the_batch_size_halves_on_out_of_memory(monkeypatch, tmp_path):
    import torch

    model = use_tiny_model(monkeypatch, tmp_path)
    tok, m, _ = bulk.load_model(model, "cpu", "fp32", None, True)
    seen = []

    class Flaky:
        def __call__(self, **enc):
            n = enc["input_ids"].shape[0]
            seen.append(n)
            if n > 2:
                raise torch.cuda.OutOfMemoryError("CUDA out of memory (simulated)")
            return m(**enc)

    log = []
    texts = TEXTS * 2
    out = bulk.embed_texts(texts, tok, Flaky(), pooling="mean", dim=DIM, batch=8, device="cpu", log=log.append)
    ref = embedder.embed(texts)
    assert np.abs(out - ref).max() < 1e-5
    assert seen[:3] == [8, 4, 2] and max(seen[3:]) <= 2 and any("batch size now 2" in x for x in log)


def test_an_error_that_is_not_out_of_memory_is_raised(monkeypatch, tmp_path):
    model = use_tiny_model(monkeypatch, tmp_path)
    tok, m, _ = bulk.load_model(model, "cpu", "fp32", None, True)

    def broken(**enc):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        bulk.embed_texts(TEXTS, tok, broken, pooling="mean", dim=DIM, batch=4, device="cpu", log=lambda *_: None)


def test_a_dimension_that_does_not_match_the_spec_is_an_error(monkeypatch, tmp_path):
    model = use_tiny_model(monkeypatch, tmp_path)
    tok, m, _ = bulk.load_model(model, "cpu", "fp32", None, True)
    with pytest.raises(RuntimeError, match="32-dim"):
        bulk.embed_texts(TEXTS, tok, m, pooling="mean", dim=DIM + 1, batch=4, device="cpu", log=lambda *_: None)


def _export_dir(tmp_path, model, texts):
    d = tmp_path / "export"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps({"model": model, "dim": DIM, "pooling": "mean", "query_prefix": "",
                                             "doc_prefix": "", "text_format": model_config.TEXT_FORMAT,
                                             "max_length": 256}))
    for ns, items in texts.items():
        (d / f"{ns}.jsonl").write_text("".join(json.dumps({"id": i, "text": t}) + "\n" for i, t in items))
    return d


def test_the_command_writes_vectors_and_ids_and_resumes(monkeypatch, tmp_path, capsys):
    model = use_tiny_model(monkeypatch, tmp_path)
    items = [(f"p{i}", t) for i, t in enumerate(TEXTS)]
    d = _export_dir(tmp_path, model, {"library": items, "feed": items[:2]})
    argv = [str(d), "--device", "cpu", "--offline", "--batch", "2"]
    assert bulk.main(argv) == 0
    assert "[feed_library] no feed_library.jsonl" in capsys.readouterr().out and not (d / "feed_library.npy").exists()
    ids = json.loads((d / "library.ids.json").read_text())
    mat = np.load(d / "library.npy")
    assert ids == [i for i, _ in items] and mat.shape == (len(TEXTS), DIM) and mat.dtype == np.float32
    assert np.abs(mat - embedder.embed(TEXTS)).max() < 1e-5
    assert np.load(d / "feed.npy").shape == (2, DIM)
    assert not list(d.glob("*.tmp"))
    # second run: everything current, nothing is embedded
    first = (d / "library.npy").stat().st_mtime_ns
    assert bulk.main(argv) == 0
    assert "already embedded" in capsys.readouterr().out and (d / "library.npy").stat().st_mtime_ns == first
    # one namespace missing: only that one is done again
    (d / "feed.npy").unlink()
    assert bulk.main(argv) == 0
    out = capsys.readouterr().out
    assert "[feed] done" in out and "[library] already embedded" in out
    # a changed text invalidates the namespace
    items[0] = ("p0", "something else entirely")
    (d / "library.jsonl").write_text("".join(json.dumps({"id": i, "text": t}) + "\n" for i, t in items))
    assert bulk.main(argv) == 0
    assert "[library] done" in capsys.readouterr().out
    # --out keeps the export directory clean
    out_dir = tmp_path / "result"
    assert bulk.main(argv + ["--out", str(out_dir), "--namespaces", "library"]) == 0
    assert (out_dir / "library.npy").exists() and (out_dir / "library.ids.json").exists()


def test_an_empty_namespace_gives_an_empty_matrix(monkeypatch, tmp_path):
    model = use_tiny_model(monkeypatch, tmp_path)
    d = _export_dir(tmp_path, model, {"feed_library": []})
    assert bulk.main([str(d), "--device", "cpu", "--offline", "--namespaces", "feed_library"]) == 0
    assert np.load(d / "feed_library.npy").shape == (0, DIM) and json.loads((d / "feed_library.ids.json").read_text()) == []


def test_a_missing_spec_is_reported(tmp_path, capsys):
    assert bulk.main([str(tmp_path)]) == 2
    assert "spec.json" in capsys.readouterr().err


def test_duplicate_ids_are_refused(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"id": "a", "text": "t"}\n{"id": "a", "text": "u"}\n')
    with pytest.raises(SystemExit):
        bulk.read_jsonl(p)


# ── the CPU embedder with a ModernBERT model, and the known-model entry ───────────────────────────

def test_the_cpu_embedder_loads_a_modernbert_model_without_remote_code(monkeypatch, tmp_path):
    import transformers

    model = use_tiny_model(monkeypatch, tmp_path)
    calls = []
    real = transformers.AutoModel.from_pretrained

    def spy(name, *a, **kw):
        calls.append(kw)
        return real(name, *a, **kw)

    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", spy)
    vecs = embedder.embed(TEXTS)
    tok, m = embedder._models[model]
    assert type(m).__name__ == "ModernBertModel" and tok.model_input_names == ["input_ids", "attention_mask"]
    assert vecs.shape == (len(TEXTS), DIM)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5) and np.isfinite(vecs).all()
    assert calls and all(kw.get("trust_remote_code") is False for kw in calls)
    # mean pooling over the attention mask: padding must not leak in (alone == in a padded batch)
    alone = embedder.embed([TEXTS[1]])
    assert np.abs(alone[0] - vecs[1]).max() < 1e-4
    # the query path works too
    q = embedder.embed_query("graph networks")
    assert q.shape == (DIM,) and abs(float(np.linalg.norm(q)) - 1.0) < 1e-5


def test_the_scientific_embedder_is_a_known_model(monkeypatch):
    assert model_config.KNOWN["J0nasW/sciembed-full"] == (768, "mean", "", "")
    monkeypatch.setenv("EMBED_MODEL", "J0nasW/sciembed-full")
    for var in ("EMBED_DIM", "EMBED_POOLING", "EMBED_QUERY_PREFIX", "EMBED_DOC_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    s = model_config.current()
    assert (s.model, s.dim, s.pooling, s.query_prefix, s.doc_prefix) == ("J0nasW/sciembed-full", 768, "mean", "", "")
    assert model_config.DEFAULT_MODEL == "BAAI/bge-small-en-v1.5"          # the default did not move
