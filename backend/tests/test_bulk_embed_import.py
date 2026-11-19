"""vectors_import.py: the imported vectors become a prepared generation; the live one is left alone."""
from __future__ import annotations

import json

import numpy as np
import pytest

from services import vectorstore
from services.conferences import embedder
from services.vectorstore import ModelSpec, model_config, registry
from tests.bulk_embed_helpers import DIM, TEXTS, load_script, use_tiny_model
from tests.vectorstore_helpers import unit

imp = load_script("vectors_import")
bulk = load_script("embed_bulk")

OLD = ModelSpec("test/model-a", 24)
NEW = ModelSpec("test/model-b", 16, "mean", "", "", model_config.TEXT_FORMAT)
N = 30


def make_export(tmp_path, spec=NEW, n=N, namespace="library", shuffle=True, seed=3, with_done=True):
    """An export directory with vectors as embed_bulk.py writes them (here random unit vectors)."""
    d = tmp_path / "export"
    d.mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    recs = [{"id": f"paper-{i}", "text": f"synthetic text {i} " * 3, "hash": f"h{i}",
             "meta": {"kind": "paper", "source": "library"}} for i in range(n)]
    doc = {**spec.to_dict(), "format": 1, "max_length": 256, "counts": {namespace: n}}
    (d / "spec.json").write_text(json.dumps(doc))
    (d / f"{namespace}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    V = unit(rng, n, spec.dim)
    order = rng.permutation(n) if shuffle else np.arange(n)
    ids = [recs[i]["id"] for i in order]
    fp = bulk.fingerprint([r["id"] for r in recs], [r["text"] for r in recs], spec.to_dict(), 256)
    np.save(d / f"{namespace}.npy", V[order])
    (d / f"{namespace}.ids.json").write_text(json.dumps(ids))
    if with_done:
        (d / f"{namespace}.done.json").write_text(json.dumps({"fingerprint": fp, "count": n, "max_length": 256}))
    return d, recs, V, order


def live_store(n=20, spec=OLD, ids=None):
    """The backend's store: built with the old model, holding its writer lock like a running backend."""
    rng = np.random.default_rng(9)
    st = registry._make(registry.vector_dir(), "library", False, spec)
    ids = ids or [f"paper-{i}" for i in range(n)]
    st.upsert(ids, unit(rng, len(ids), spec.dim), [{"kind": "paper", "source": "library", "hash": "old"}] * len(ids))
    return st


def echo(recs, ids, V):
    """An embedder that answers with the imported vector of the text (cosine 1 against the import)."""
    by_text = {r["text"]: V[int(r["id"].split("-")[1])] for r in recs}
    return lambda texts: np.vstack([by_text[t] for t in texts])


def run(d, recs=None, V=None, **kw):
    spec, doc = imp.load_spec(d)
    return imp.import_namespace(d, "library", spec, doc, log=lambda *_: None, **kw)


def test_import_builds_a_prepared_generation_and_leaves_the_live_one_alone(tmp_path):
    d, recs, V, _ = make_export(tmp_path)
    st = live_store()                                              # "the backend": holds the writer lock
    before = st.search(unit(np.random.default_rng(1), 1, 24)[0], 5)
    spec, doc = imp.load_spec(d)
    res = imp.import_namespace(d, "library", spec, doc, embed_fn=echo(recs, None, V), log=lambda *_: None)
    assert res["imported"] == N and res["dim"] == 16 and res["generation"] == "p000001"
    assert res["check"]["mean_cosine"] == pytest.approx(1.0, abs=1e-5) and res["check"]["checked"] == 20
    # live reads and the live manifest are unchanged
    assert st.manifest().model == "test/model-a" and st.count() == 20 and not st.is_stale(OLD)
    assert st.search(unit(np.random.default_rng(1), 1, 24)[0], 5) == before
    assert (st.dir / "CURRENT").read_text().strip() == "g000001"
    # the prepared generation: right model, right content, in vector order of ids.json, with hashes
    reader = registry._make(registry.vector_dir(), "library", True, NEW)
    (m,) = reader.prepared()
    assert (m.model, m.dim, m.count, m.generation) == ("test/model-b", 16, N, "p000001")
    got = vectorstore.base._gen_class("exact").open(st.dir / "p000001", 16, read_only=True)
    ids, mat = got.all_vectors([])
    assert sorted(ids) == sorted(r["id"] for r in recs)
    for i, v in zip(ids, mat):
        assert np.array_equal(v, V[int(i.split("-")[1])])
    meta = got.metadata(["paper-4"])["paper-4"]
    assert meta["hash"] == "h4" and meta["kind"] == "paper" and meta["source"] == "library" and meta["added_at"]
    got.close()
    reader.close()
    st.close()


def test_missing_ids_are_reported(tmp_path):
    d, recs, V, _ = make_export(tmp_path, n=10)
    st = live_store(ids=[f"paper-{i}" for i in range(8)] + ["added-later-1", "added-later-2"])
    res = run(d, skip_check=True)
    assert res["missing_from_import"] == 2 and sorted(res["missing_sample"]) == ["added-later-1", "added-later-2"]
    assert res["only_in_import"] == 2 and res["live_vectors"] == 10
    assert res["check"] == "skipped (--skip-check)"
    st.close()


def test_import_into_a_namespace_that_was_never_built(tmp_path):
    d, *_ = make_export(tmp_path, n=5)
    res = run(d, skip_check=True)
    assert res["live_vectors"] == 0 and res["missing_from_import"] == 0 and res["imported"] == 5
    st = registry._make(registry.vector_dir(), "library", True, NEW)
    assert st.manifest() is None and len(st.prepared()) == 1
    st.close()


def test_importing_again_replaces_the_prepared_generation(tmp_path):
    d, *_ = make_export(tmp_path)
    run(d, skip_check=True)
    run(d, skip_check=True)
    st = registry._make(registry.vector_dir(), "library", True, NEW)
    assert [m.generation for m in st.prepared()] == ["p000002"]
    assert sorted(p.name for p in st.dir.glob("p*")) == ["p000002"]
    st.close()


@pytest.mark.parametrize("what, match", [
    ("dim", "dimension 16"), ("nan", "NaN"), ("norm", "unit length"), ("count", "ids"), ("dup", "duplicate"),
    ("unknown", "not in library.jsonl"), ("fingerprint", "not made from the texts"),
])
def test_files_that_do_not_fit_are_refused_and_nothing_is_stored(tmp_path, what, match):
    d, recs, V, order = make_export(tmp_path)
    npy, ids_p = d / "library.npy", d / "library.ids.json"
    mat, ids = np.load(npy), json.loads(ids_p.read_text())
    if what == "dim":
        np.save(npy, mat[:, :8])
    elif what == "nan":
        mat[3, 2] = np.nan
        np.save(npy, mat)
    elif what == "norm":
        np.save(npy, mat * 1.5)
    elif what == "count":
        ids_p.write_text(json.dumps(ids[:-1]))
    elif what == "dup":
        ids[1] = ids[0]
        ids_p.write_text(json.dumps(ids))
    elif what == "unknown":
        ids[0] = "somebody-else"
        ids_p.write_text(json.dumps(ids))
    elif what == "fingerprint":
        lines = (d / "library.jsonl").read_text().splitlines()
        r = json.loads(lines[0])
        r["text"] += " edited after embedding"
        lines[0] = json.dumps(r)
        (d / "library.jsonl").write_text("\n".join(lines) + "\n")
    with pytest.raises(imp.ImportCheckError, match=match):
        run(d, skip_check=True)
    st = registry._make(registry.vector_dir(), "library", True, NEW)
    assert st.prepared() == []
    st.close()


def test_a_missing_done_file_is_a_warning_not_an_error(tmp_path):
    d, *_ = make_export(tmp_path, with_done=False)
    res = run(d, skip_check=True)
    assert "could not verify" in res["warning"] and res["imported"] == N


def test_a_vector_missing_for_an_exported_text_is_an_error(tmp_path):
    d, recs, V, order = make_export(tmp_path, shuffle=False)
    np.save(d / "library.npy", np.load(d / "library.npy")[:-2])
    (d / "library.ids.json").write_text(json.dumps([r["id"] for r in recs][:-2]))
    (d / "library.done.json").unlink()
    with pytest.raises(imp.ImportCheckError, match="2 exported texts have no vector"):
        run(d, skip_check=True)


def test_the_sanity_check_rejects_vectors_of_another_embedding(tmp_path):
    d, recs, V, _ = make_export(tmp_path)
    rng = np.random.default_rng(5)
    wrong = lambda texts: unit(rng, len(texts), 16)           # noqa: E731 — what a wrong model or pooling gives
    with pytest.raises(imp.ImportCheckError, match="mean cosine"):
        run(d, embed_fn=wrong)
    st = registry._make(registry.vector_dir(), "library", True, NEW)
    assert st.prepared() == []                                  # nothing imported
    st.close()


def test_the_sanity_check_tolerates_half_precision_noise(tmp_path):
    d, recs, V, _ = make_export(tmp_path)
    rng = np.random.default_rng(5)
    base = echo(recs, None, V)

    def noisy(texts):
        v = base(texts) + rng.normal(scale=0.01, size=(len(texts), 16)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    res = run(d, embed_fn=noisy)
    assert 0.98 <= res["check"]["mean_cosine"] < 1.0
    assert run(d, check_n=0)["check"] == {"checked": 0}


def test_a_model_that_cannot_be_loaded_skips_the_check_and_says_so(tmp_path, monkeypatch):
    d, *_ = make_export(tmp_path)

    def cannot(sp=None):
        raise OSError("model not available offline")

    monkeypatch.setattr(embedder, "_load", cannot)
    logs = []
    spec, doc = imp.load_spec(d)
    res = imp.import_namespace(d, "library", spec, doc, log=logs.append)
    assert res["check"].startswith("SKIPPED") and "OSError" in res["check"] and res["imported"] == N
    assert any("NOT verified" in x for x in logs)


def test_the_check_embeds_with_the_target_model_and_restores_the_environment(tmp_path, monkeypatch):
    """End to end on a tiny ModernBERT: embed_bulk output, imported with the real CPU embedder as the check."""
    model = use_tiny_model(monkeypatch, tmp_path, name="target")
    monkeypatch.delenv("EMBED_MODEL")                    # the script runs with the *old* settings in its environment
    monkeypatch.delenv("EMBED_DIM")
    monkeypatch.delenv("EMBED_POOLING")
    monkeypatch.delenv("EMBED_DOC_PREFIX")
    spec = ModelSpec(model, DIM, "mean", "", "", model_config.TEXT_FORMAT)
    d = tmp_path / "export"
    d.mkdir()
    recs = [{"id": f"t{i}", "text": t, "hash": f"h{i}", "meta": {"kind": "paper", "source": "library"}}
            for i, t in enumerate(TEXTS)]
    (d / "spec.json").write_text(json.dumps({**spec.to_dict(), "max_length": 256}))
    (d / "library.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    assert bulk.main([str(d), "--device", "cpu", "--offline", "--namespaces", "library"]) == 0
    live_store(ids=[f"t{i}" for i in range(3)])
    spec2, doc = imp.load_spec(d)
    res = imp.import_namespace(d, "library", spec2, doc, check_n=4, log=lambda *_: None)
    assert res["check"]["checked"] == 4 and res["check"]["mean_cosine"] > 0.9999
    import os
    assert "EMBED_MODEL" not in os.environ and "EMBED_DIM" not in os.environ        # restored


def test_the_environment_lines_name_only_what_the_model_list_lacks():
    assert imp.env_lines(ModelSpec("J0nasW/sciembed-full", 768, "mean", "", "")) == ["EMBED_MODEL=J0nasW/sciembed-full"]
    assert imp.env_lines(ModelSpec("example/unlisted", 512, "cls", "q: ", "d: ")) == [
        "EMBED_MODEL=example/unlisted", "EMBED_DIM=512", "EMBED_POOLING=cls", "EMBED_QUERY_PREFIX=q: ",
        "EMBED_DOC_PREFIX=d: "]


def test_a_text_format_this_code_does_not_know_is_refused(tmp_path):
    d, *_ = make_export(tmp_path)
    doc = json.loads((d / "spec.json").read_text())
    doc["text_format"] = "title-abstract-0"
    (d / "spec.json").write_text(json.dumps(doc))
    with pytest.raises(imp.ImportCheckError, match="text format"):
        imp.load_spec(d)


def test_main_prints_the_switch_instructions_and_discard_removes_the_generation(tmp_path, capsys):
    d, *_ = make_export(tmp_path)
    live_store()
    assert imp.main([str(d), "--skip-check", "--namespaces", "library"]) == 0
    out = capsys.readouterr().out
    assert "EMBED_MODEL=test/model-b" in out and "EMBED_DIM=16" in out and "CONFERENCE_EMBED_MODEL" in out
    assert imp.main([str(d), "--discard", "--namespaces", "library"]) == 0
    assert "discarded 1 prepared" in capsys.readouterr().out
    assert imp.main([str(d), "--skip-check", "--namespaces", "feed"]) == 1          # not in the export
    bad = tmp_path / "empty"
    bad.mkdir()
    assert imp.main([str(bad), "--skip-check"]) == 1 and "spec.json" in capsys.readouterr().err


def test_an_empty_namespace_is_imported_as_an_empty_prepared_generation(tmp_path):
    d, *_ = make_export(tmp_path, n=0, shuffle=False)
    np.save(d / "library.npy", np.zeros((0, 16), np.float32))
    res = run(d, embed_fn=lambda t: np.zeros((0, 16)))
    assert res["exported"] == 0 and res["imported"] == 0 and res["generation"] == "p000001"
    st = registry._make(registry.vector_dir(), "library", False, NEW)
    assert st.adopt_matching() == "prepared" and st.count() == 0 and st.manifest().model == "test/model-b"
    st.close()
