#!/usr/bin/env python3
"""
Setup Google Drive OAuth authentication.
This script must be run on a machine with a browser (not in Docker).
Run: python3 backend/scripts/setup_drive_oauth.py
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = Path(__file__).parent.parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent.parent / "token.json"


def setup_oauth():
    """Run the OAuth flow to generate token.json."""
    if not CREDENTIALS_FILE.exists():
        print(f"❌ Error: credentials.json not found at {CREDENTIALS_FILE}")
        print("\nYou need to:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project and enable Google Drive API")
        print("3. Create OAuth 2.0 credentials (Desktop app)")
        print("4. Download the credentials.json file")
        print(f"5. Place it at {CREDENTIALS_FILE}")
        sys.exit(1)

    creds = None
    
    # Check if we already have valid tokens
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds and creds.valid:
            print("✅ Token already exists and is valid!")
            print(f"   Location: {TOKEN_FILE}")
            return

    # Refresh expired token or create new one
    if creds and creds.expired and creds.refresh_token:
        print("Refreshing expired token...")
        creds.refresh(Request())
    else:
        print("Starting OAuth flow...")
        print("Your browser will open. Please authorize the application.")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE), SCOPES
        )
        creds = flow.run_local_server(port=0)

    # Save the token
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json())
    print(f"\n✅ Success! Token saved to {TOKEN_FILE}")
    print("\nNext steps:")
    print("1. Copy this file to the Docker container:")
    print(f"   docker cp {TOKEN_FILE} papermanager-backend-1:/app/token.json")
    print("2. Restart the backend:")
    print("   docker compose restart backend")


if __name__ == "__main__":
    try:
        setup_oauth()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
