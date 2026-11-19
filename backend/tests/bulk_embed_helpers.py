"""Synthetic helpers for the bulk-embedding tests: a tiny random ModernBERT with its own tokenizer, written
to a local directory (no download), and a loader for the scripts in ``backend/scripts``."""
from __future__ import annotations

import importlib.util
import string
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
DIM = 32


def load_script(name: str):
    """Import ``backend/scripts/<name>.py`` as a module (scripts is not a package)."""
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"pm_script_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_tiny_modernbert(path: Path, seed: int = 0) -> str:
    """A random 2-layer ModernBERT (hidden size 32) and a word-piece tokenizer over a-z and digits,
    saved to ``path``. Returns the path as a string (usable as a model id)."""
    import torch
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors
    from transformers import ModernBertConfig, ModernBertModel, PreTrainedTokenizerFast

    chars = string.ascii_lowercase + string.digits
    vocab_list = ["[PAD]", "[UNK]", "[CLS]", "[SEP]"] + list(chars) + ["##" + c for c in chars]
    vocab = {t: i for i, t in enumerate(vocab_list)}
    tk = Tokenizer(models.WordPiece(vocab, unk_token="[UNK]", max_input_chars_per_word=100))
    tk.normalizer = normalizers.BertNormalizer(lowercase=True)
    tk.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tk.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)])
    tok = PreTrainedTokenizerFast(tokenizer_object=tk, pad_token="[PAD]", unk_token="[UNK]", cls_token="[CLS]",
                                  sep_token="[SEP]", model_input_names=["input_ids", "attention_mask"])
    cfg = ModernBertConfig(
        vocab_size=len(vocab_list), hidden_size=DIM, intermediate_size=64, num_hidden_layers=2,
        num_attention_heads=2, max_position_embeddings=512, local_attention=16, global_attn_every_n_layers=2,
        pad_token_id=0, bos_token_id=2, eos_token_id=3, cls_token_id=2, sep_token_id=3)
    torch.manual_seed(seed)
    model = ModernBertModel(cfg).eval()
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(path)
    tok.save_pretrained(path)
    return str(path)


TEXTS = [
    "attention is all you need",
    "protein folding with diffusion models and a longer second sentence about structure prediction",
    "",
    "short",
    "graph neural networks for molecules " * 12,      # longer than 256 tokens once split into word pieces
    "contrastive pretraining of 3 scientific encoders",
]


def use_tiny_model(monkeypatch, tmp_path: Path, name: str = "model", seed: int = 0, pooling: str = "mean",
                   doc_prefix: str = "") -> str:
    """Make the tiny ModernBERT the configured embedding model of this test (EMBED_*), with an empty model
    cache and a temporary conference data directory. Returns the model id (a local directory)."""
    from services.conferences import embedder, store

    model = make_tiny_modernbert(tmp_path / name, seed)
    monkeypatch.setenv("EMBED_MODEL", model)
    monkeypatch.setenv("EMBED_DIM", str(DIM))
    monkeypatch.setenv("EMBED_POOLING", pooling)
    monkeypatch.setenv("EMBED_DOC_PREFIX", doc_prefix)
    monkeypatch.delenv("CONFERENCE_EMBED_MODEL", raising=False)
    monkeypatch.setenv("CONFERENCE_DATA_DIR", str(tmp_path / "conf"))
    monkeypatch.setattr(store, "_data_dir", None)
    monkeypatch.setattr(embedder, "_models", {})
    return model
