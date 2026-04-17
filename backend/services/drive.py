"""Google Drive service — upload/retrieve/delete research PDFs."""
from __future__ import annotations

import io
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from config import settings

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_CREDS_FILE = Path(__file__).parent.parent / "credentials.json"
_TOKEN_FILE = Path(__file__).parent.parent / "token.json"


def get_drive_service():
    """Return an authenticated Drive v3 service object."""
    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), _SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_FILE.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_pdf(pdf_bytes: bytes, filename: str) -> str:
    """Upload *pdf_bytes* to the configured Drive folder and return the file ID."""
    service = get_drive_service()
    file_metadata = {
        "name": filename,
        "parents": [settings.google_drive_folder_id],
    }
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf", resumable=False)
    result = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )
    return result["id"]


def get_file_url(file_id: str) -> str:
    """Return a browser-viewable URL for the given Drive file ID."""
    return f"https://drive.google.com/file/d/{file_id}/view"


def delete_file(file_id: str) -> None:
    """Move a Drive file to trash (soft delete)."""
    service = get_drive_service()
    service.files().update(fileId=file_id, body={"trashed": True}).execute()
