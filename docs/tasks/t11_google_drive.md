# T11 — Google Drive Integration

**Phase:** 3 — File handling + AI
**Depends on:** T01
**Touches:** `backend/services/drive.py`

## Goal
Upload a PDF to a specific Google Drive folder and return the file ID.
Also support getting a download/view URL for stored PDFs.

## Setup (one-time)
1. Go to Google Cloud Console → create a project
2. Enable the Google Drive API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `credentials.json` → store in `backend/` (never commit)
5. Run auth flow once to generate `token.json`
6. Add `GOOGLE_DRIVE_FOLDER_ID` to `.env` (the folder where PDFs will be stored)

## drive.py

```python
def get_drive_service():
    # Loads credentials from token.json / credentials.json
    # Returns a Google Drive API service object

def upload_pdf(pdf_bytes: bytes, filename: str) -> str:
    # Uploads to the configured Drive folder
    # Returns the Google Drive file_id (string)

def get_file_url(file_id: str) -> str:
    # Returns a shareable view URL:
    # https://drive.google.com/file/d/{file_id}/view

def delete_file(file_id: str): ...
    # Moves to trash (soft delete)
```

## Done when
- [ ] Auth flow works and `token.json` is generated
- [ ] `upload_pdf(bytes, "test.pdf")` returns a valid Drive file ID
- [ ] File appears in the configured Drive folder
- [ ] `get_file_url(file_id)` returns a valid URL

## Tests
`backend/tests/test_drive.py`
- These are integration tests — they actually hit Google Drive
- Mark with `@pytest.mark.integration` so they can be skipped in CI
- Upload a small test PDF → get back a file_id
- Get URL → URL contains the file_id
- Delete → file no longer accessible

## Notes
- `credentials.json` and `token.json` must be in `.gitignore`
- For Railway deployment: store credentials as environment variables (base64-encoded JSON)
- If running headlessly (no browser for OAuth), use a service account instead
