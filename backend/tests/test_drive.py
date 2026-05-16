from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from services.drive import _build_client_config, _get_creds_file, get_file_url, upload_pdf, delete_file

FIXTURE = Path(__file__).parent / "fixtures" / "attention.pdf"


def _drive_auth_available() -> bool:
    return bool(_get_creds_file().exists())


# ── Unit tests (no network) ───────────────────────────────────────────────────

def test_get_file_url_format():
    url = get_file_url("abc123xyz")
    assert url == "https://drive.google.com/file/d/abc123xyz/view"


def test_upload_pdf_calls_drive_api():
    """upload_pdf returns the file ID from the Drive API response."""
    mock_service = MagicMock()
    mock_service.files().create().execute.return_value = {"id": "fake_file_id"}

    with patch("services.drive.get_drive_service", return_value=mock_service):
        file_id = upload_pdf(b"fake pdf bytes", "test.pdf")

    assert file_id == "fake_file_id"


def test_delete_file_calls_drive_api():
    mock_service = MagicMock()

    with patch("services.drive.get_drive_service", return_value=mock_service):
        delete_file("some_file_id")

    mock_service.files().update.assert_called_once_with(
        fileId="some_file_id", body={"trashed": True}
    )


def test_build_client_config_uses_env_credentials(monkeypatch):
    monkeypatch.setattr("services.drive._get_creds_file", lambda: Path("/tmp/missing-credentials.json"))
    monkeypatch.setattr("services.drive.settings.google_client_id", "client-id")
    monkeypatch.setattr("services.drive.settings.google_client_secret", "client-secret")

    config = _build_client_config()

    assert config["client_config"]["installed"]["client_id"] == "client-id"
    assert config["client_config"]["installed"]["client_secret"] == "client-secret"


def test_build_client_config_errors_when_not_configured(monkeypatch):
    monkeypatch.setattr("services.drive._get_creds_file", lambda: Path("/tmp/missing-credentials.json"))
    monkeypatch.setattr("services.drive.settings.google_client_id", "")
    monkeypatch.setattr("services.drive.settings.google_client_secret", "")

    with pytest.raises(FileNotFoundError, match="Google Drive OAuth client credentials not configured"):
        _build_client_config()


# ── Integration tests (hit real Drive) ───────────────────────────────────────

@pytest.mark.integration
@pytest.mark.skipif(not _drive_auth_available(), reason="Google Drive auth not configured locally")
def test_upload_and_delete_real_pdf():
    """Upload fixture PDF, verify file_id returned, then delete."""
    pdf_bytes = FIXTURE.read_bytes()
    file_id = upload_pdf(pdf_bytes, "attention_test_fixture.pdf")
    assert file_id and isinstance(file_id, str)

    url = get_file_url(file_id)
    assert file_id in url

    delete_file(file_id)  # clean up
