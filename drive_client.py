"""
drive_client.py
Upload bill images to Google Drive under season subfolders.

Structure:
  Shetkari-Journal/  (GOOGLE_DRIVE_ROOT_FOLDER_ID)
    └── Bills-YYYY/
        ├── Kharif-YYYY/
        └── Rabi-YYYY/
"""

import io
import logging
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from config import SERVICE_ACCOUNT_INFO, GOOGLE_DRIVE_ROOT_FOLDER_ID

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_service():
    creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return folder_id, creating it if it doesn't exist."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Create folder
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_image(image_bytes: bytes, season: str, original_filename: str = "") -> str:
    """
    Upload image_bytes to Drive under season subfolder.
    Returns shareable web view link or empty string on failure.
    """
    try:
        service = _get_service()

        # Build folder path: root → Bills-YYYY → season
        year = season.split("-")[-1]
        bills_folder = _get_or_create_folder(service, f"Bills-{year}", GOOGLE_DRIVE_ROOT_FOLDER_ID)
        season_folder = _get_or_create_folder(service, season, bills_folder)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bill_{timestamp}.jpg"

        # Upload
        file_metadata = {"name": filename, "parents": [season_folder]}
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/jpeg")
        uploaded = service.files().create(
            body=file_metadata, media_body=media, fields="id, webViewLink"
        ).execute()

        file_id = uploaded.get("id")

        # Make it readable by anyone with the link
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        link = uploaded.get("webViewLink", "")
        logger.info(f"Uploaded bill to Drive: {link}")
        return link

    except Exception as e:
        logger.error(f"Drive upload failed: {e}")
        return ""
