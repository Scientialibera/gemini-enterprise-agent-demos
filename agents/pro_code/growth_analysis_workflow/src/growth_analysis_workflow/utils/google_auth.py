"""Google credentials and Drive helpers for the Sheets, Docs and Drive tools.

The dev build read a token.json baked into the deployment. Here every call uses
the signed-in Gemini Enterprise user's credentials, bound by the workflow while
the tool runs, so the sheet and the report folder follow that user's access.
"""

import logging
from typing import List, Optional

from gemini_shared import current_user_credentials
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

DEFAULT_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def authenticate_google_oauth(scopes: Optional[List[str]] = None) -> Credentials:
    """The signed-in user's credentials, bound for this tool call.

    The scopes are granted by the workflow's Gemini Enterprise authorization;
    the argument is kept so callers read as they do in the dev build.
    """
    return current_user_credentials()


def move_file_to_folder(drive_service, file_id: str, folder_id: str) -> None:
    """Moves a file into the specified Google Drive folder.

    Args:
        drive_service: Authorized Google Drive Resource client instance.
        file_id: The ID of the Google Doc or file to move.
        folder_id: The ID of the target shared Google Drive folder.

    Raises:
        HttpError: If Google Drive API call fails.
    """
    try:
        file = (
            drive_service.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
        previous_parents = ",".join(file.get("parents", []))
        drive_service.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            supportsAllDrives=True,
            fields="id, parents",
        ).execute()
        logger.info(f"Successfully moved file {file_id} to folder {folder_id}")
    except HttpError as err:
        logger.error(f"Failed to move file {file_id} to folder {folder_id}: {err}")
        raise
