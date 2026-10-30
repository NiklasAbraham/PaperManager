"""Fast-model provider routing and local file storage, both driven by .env."""
import pytest

from config import settings
from services import drive, litellm_client as lc


@pytest.fixture
def env(monkeypatch):
    for key, value in {
        "ai_provider": "auto", "fast_model": "", "litellm_endpoint": "", "litellm_api_key": "",
        "anthropic_api_key": "", "openai_api_key": "",
    }.items():
        monkeypatch.setattr(settings, key, value)
    return lambda **kw: [monkeypatch.setattr(settings, k, v) for k, v in kw.items()]


def test_auto_prefers_litellm_then_anthropic_then_openai(env):
    assert lc.fast_provider() is None
    env(openai_api_key="sk-o")
    assert (lc.fast_provider(), lc.fast_model(), lc.fast_model_label()) == ("openai", "gpt-5-mini", "GPT-5 mini")
    env(anthropic_api_key="sk-ant")
    assert (lc.fast_provider(), lc.fast_model_label()) == ("anthropic", "Claude Haiku 4.5")
    env(litellm_endpoint="https://proxy", litellm_api_key="k")
    assert (lc.fast_provider(), lc.fast_model()) == ("litellm", settings.litellm_model)


def test_explicit_provider_and_model_override(env):
    env(ai_provider="openai", anthropic_api_key="sk-ant", fast_model="gpt-5-nano")
    assert lc.fast_provider() == "openai"
    assert lc.resolve_chat_model("litellm") == "gpt-5-nano"
    assert lc.resolve_chat_model(settings.litellm_model) == "gpt-5-nano"
    assert lc.resolve_chat_model("claude-opus-4-6") == "claude-opus-4-6"


def test_chat_completion_routes_to_anthropic(env, monkeypatch):
    env(anthropic_api_key="sk-ant")
    seen = {}

    def fake(messages, model, **kw):
        seen.update(model=model, **kw)
        return "ok"

    monkeypatch.setattr(lc, "_anthropic_completion", fake)
    assert lc.chat_completion([{"role": "user", "content": "hi"}], json_mode=True) == "ok"
    assert seen["model"] == lc.ANTHROPIC_FAST_MODEL and seen["json_mode"] is True


def _litellm_down(monkeypatch):
    class Down:
        def __getattr__(self, name):
            raise RuntimeError("Bad Gateway")

    class Client:
        chat = Down()

    monkeypatch.setattr(lc, "get_litellm_client", lambda: Client())


def test_litellm_failure_falls_back_to_anthropic(env, monkeypatch):
    env(litellm_endpoint="https://proxy", litellm_api_key="k", anthropic_api_key="sk-ant")
    _litellm_down(monkeypatch)
    seen = {}
    monkeypatch.setattr(lc, "_anthropic_completion", lambda m, model, **kw: seen.setdefault("model", model) and "ok")
    assert lc.chat_completion([{"role": "user", "content": "hi"}]) == "ok"
    assert seen["model"] == lc.ANTHROPIC_FAST_MODEL


@pytest.mark.parametrize("override", [{"anthropic_api_key": ""}, {"ai_fallback": False}])
def test_litellm_failure_raises_without_fallback(env, monkeypatch, override):
    env(litellm_endpoint="https://proxy", litellm_api_key="k", anthropic_api_key="sk-ant", ai_fallback=True)
    env(**override)
    _litellm_down(monkeypatch)
    monkeypatch.setattr(lc, "_anthropic_completion", lambda *a, **kw: pytest.fail("should not fall back"))
    with pytest.raises(RuntimeError, match="Bad Gateway"):
        lc.chat_completion([{"role": "user", "content": "hi"}])


def test_local_storage_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_backend", "auto")
    monkeypatch.setattr(settings, "google_drive_folder_id", "")
    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path))
    assert drive.uses_local_storage()

    file_id = drive.upload_pdf(b"%PDF-1.4 test", "paper.pdf")
    assert file_id.startswith("local-") and file_id.endswith(".pdf")
    assert drive.download_pdf(file_id) == b"%PDF-1.4 test"
    assert drive.get_file_url(file_id) == ""
    drive.delete_file(file_id)
    assert not (tmp_path / file_id).exists()

    with pytest.raises(ValueError):
        drive.download_pdf("local-../../etc/passwd")


def test_drive_folder_selects_drive(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "auto")
    monkeypatch.setattr(settings, "google_drive_folder_id", "abc")
    assert not drive.uses_local_storage()
    monkeypatch.setattr(settings, "storage_backend", "local")
    assert drive.uses_local_storage()
