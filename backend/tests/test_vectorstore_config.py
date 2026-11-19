"""Model configuration (one place), the registry and its settings."""
from __future__ import annotations

import numpy as np
import pytest

from services import vectorstore
from services.vectorstore import ModelConfigError, model_config
from services.vectorstore.model_config import DEFAULT_MODEL

_VARS = ("EMBED_MODEL", "CONFERENCE_EMBED_MODEL", "EMBED_DIM", "EMBED_POOLING", "EMBED_QUERY_PREFIX", "EMBED_DOC_PREFIX")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in _VARS:
        monkeypatch.delenv(v, raising=False)


def test_the_default_is_the_long_standing_bge_small_setup():
    s = model_config.current()
    assert (s.model, s.dim, s.pooling) == (DEFAULT_MODEL, 384, "cls")
    assert s.query_prefix.startswith("Represent this sentence") and s.doc_prefix == ""
    assert model_config.dim() == 384 and model_config.legacy_model() == DEFAULT_MODEL


def test_embedder_constants_come_from_the_same_place():
    from services.conferences import embedder

    s = model_config.current()
    assert (embedder.MODEL, embedder.DIM) == (s.model, s.dim)
    assert embedder.query_text("short query") == s.query_prefix + "short query"
    assert embedder.query_text(" ".join(["word"] * 30)) == " ".join(["word"] * 30)        # long: no prefix


def test_known_models_bring_their_dimension_pooling_and_prefixes(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "intfloat/e5-base-v2")
    s = model_config.current()
    assert (s.dim, s.pooling, s.query_prefix, s.doc_prefix) == (768, "mean", "query: ", "passage: ")
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-large-en-v1.5")
    assert model_config.dim() == 1024


def test_an_unknown_model_needs_a_dimension_and_defaults_to_mean_pooling(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "example/custom-encoder")
    with pytest.raises(ModelConfigError):
        model_config.current()
    monkeypatch.setenv("EMBED_DIM", "512")
    s = model_config.current()
    assert (s.model, s.dim, s.pooling, s.query_prefix) == ("example/custom-encoder", 512, "mean", "")
    monkeypatch.setenv("EMBED_POOLING", "cls")
    monkeypatch.setenv("EMBED_QUERY_PREFIX", "find: ")
    monkeypatch.setenv("EMBED_DOC_PREFIX", "doc: ")
    s = model_config.current()
    assert (s.pooling, s.query_prefix, s.doc_prefix) == ("cls", "find: ", "doc: ")


def test_bad_values_are_named(monkeypatch):
    monkeypatch.setenv("EMBED_DIM", "many")
    with pytest.raises(ModelConfigError, match="EMBED_DIM"):
        model_config.current()
    monkeypatch.setenv("EMBED_DIM", "")
    monkeypatch.setenv("EMBED_POOLING", "max")
    with pytest.raises(ModelConfigError, match="EMBED_POOLING"):
        model_config.current()


def test_empty_variables_count_as_unset_and_the_legacy_name_still_works(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "")
    monkeypatch.setenv("EMBED_DIM", "")
    monkeypatch.setenv("CONFERENCE_EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    assert (model_config.current().model, model_config.dim()) == ("BAAI/bge-base-en-v1.5", 768)
    monkeypatch.setenv("EMBED_MODEL", DEFAULT_MODEL)                      # the new name wins
    assert model_config.current().model == DEFAULT_MODEL


def test_space_key_ignores_the_query_prefix_only():
    a = model_config.ModelSpec("m", 8)
    assert a.space_key() == model_config.ModelSpec("m", 8, query_prefix="q").space_key()
    for other in (model_config.ModelSpec("n", 8), model_config.ModelSpec("m", 9),
                  model_config.ModelSpec("m", 8, pooling="mean"), model_config.ModelSpec("m", 8, doc_prefix="d"),
                  model_config.ModelSpec("m", 8, text_format="x")):
        assert a.space_key() != other.space_key()
    assert model_config.ModelSpec.from_dict(a.to_dict()) == a


def test_the_registry_shares_one_store_per_namespace_and_directory():
    a = vectorstore.get_store("alpha")
    assert a is vectorstore.get_store("alpha") and a is not vectorstore.get_store("beta")
    assert vectorstore.get_store("gamma", create=False) is None
    assert not (vectorstore.vector_dir() / "gamma").exists()                 # create=False writes nothing
    assert a.manifest().model == DEFAULT_MODEL and a.manifest().dim == 384


def test_the_directory_comes_from_the_environment_with_a_writable_fallback(tmp_path, monkeypatch):
    target = tmp_path / "custom" / "vectors"
    monkeypatch.setenv("VECTOR_STORE_DIR", str(target))
    vectorstore.reset()
    assert vectorstore.vector_dir() == target and target.is_dir()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("VECTOR_STORE_DIR", str(blocker / "sub"))            # cannot be created
    vectorstore.reset()
    d = vectorstore.vector_dir()
    assert d != blocker / "sub" and d.is_dir()


def test_a_model_switch_through_the_environment_makes_the_registry_store_stale(monkeypatch):
    st = vectorstore.get_store("library")
    st.upsert(["a"], np.eye(384, dtype=np.float32)[:1])
    assert not st.is_stale()
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    assert st.is_stale() and st.state() == "stale"
    monkeypatch.delenv("EMBED_MODEL")
    assert not st.is_stale()


def test_the_exact_backend_needs_nothing_beyond_numpy():
    """A fresh interpreter, lancedb made unimportable: the package imports and the exact store works."""
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys, tempfile\n"
        "sys.modules['lancedb'] = None\n"
        "import numpy as np\n"
        "from services.vectorstore import ExactStore, ModelSpec\n"
        "s = ExactStore(tempfile.mkdtemp(), 'ns', spec=ModelSpec('m', 4))\n"
        "s.upsert(['a'], np.eye(4, dtype=np.float32)[:1])\n"
        "assert s.search(np.eye(4, dtype=np.float32)[0], 1)[0].id == 'a'\n"
        "assert 'pyarrow' not in sys.modules and 'faiss' not in sys.modules\n"
        "print('ok')\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-600:]
