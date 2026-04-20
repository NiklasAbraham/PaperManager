"""Google Drive service — upload/retrieve/delete research PDFs."""
from __future__ import annotations

import io
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

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


def download_pdf(file_id: str) -> bytes:
    """Download a Drive file and return its raw bytes."""
    service = get_drive_service()
    buf = io.BytesIO()
    request = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


_figures_folder_id: str | None = None


def _get_figures_folder() -> str:
    """Return (creating if needed) the Drive subfolder id for figures."""
    global _figures_folder_id
    if _figures_folder_id:
        return _figures_folder_id
    service = get_drive_service()
    # Search for an existing "figures" folder inside the main folder
    q = (
        f"name = 'figures' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and '{settings.google_drive_folder_id}' in parents "
        f"and trashed = false"
    )
    res = service.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = res.get("files", [])
    if files:
        _figures_folder_id = files[0]["id"]
    else:
        folder = service.files().create(
            body={
                "name": "figures",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [settings.google_drive_folder_id],
            },
            fields="id",
        ).execute()
        _figures_folder_id = folder["id"]
    return _figures_folder_id


def upload_image(image_bytes: bytes, filename: str) -> str:
    """Upload PNG image bytes to the figures subfolder and return the file ID."""
    service = get_drive_service()
    folder_id = _get_figures_folder()
    file_metadata = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/png", resumable=False)
    result = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )
    return result["id"]


def delete_file(file_id: str) -> None:
    """Move a Drive file to trash (soft delete)."""
    service = get_drive_service()
    service.files().update(fileId=file_id, body={"trashed": True}).execute()
