"""
Integration tests for Google Drive service.
Require real credentials — skip in CI with: pytest -m "not integration"
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from services.drive import get_file_url, upload_pdf, delete_file

FIXTURE = Path(__file__).parent / "fixtures" / "attention.pdf"


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


# ── Integration tests (hit real Drive) ───────────────────────────────────────

@pytest.mark.integration
def test_upload_and_delete_real_pdf():
    """Upload fixture PDF, verify file_id returned, then delete."""
    pdf_bytes = FIXTURE.read_bytes()
    file_id = upload_pdf(pdf_bytes, "attention_test_fixture.pdf")
    assert file_id and isinstance(file_id, str)

    url = get_file_url(file_id)
    assert file_id in url

    delete_file(file_id)  # clean up
