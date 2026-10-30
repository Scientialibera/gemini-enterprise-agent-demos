"""Google Drive operations, made as the signed-in Gemini Enterprise user.

Every call uses the credentials bound for the current tool call by
``gemini_shared.with_user_credentials``, so the agent reads and writes only the
files and Shared Drive folders that user can. No token is stored: each request
carries the user's own session token.
"""

import random
import time
from datetime import datetime

from gemini_shared import current_user_credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


def _get_drive_service():
    """Build a Drive client for the user whose tool call is in progress."""
    return build("drive", "v3", credentials=current_user_credentials(), cache_discovery=False)


def _literal(value: str) -> str:
    """A Drive query string literal. File names come from users, and a quote would end it."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def download_file_from_drive(file_id: str, local_dest_path: str) -> str:
    """Ingests an Excel file binary stream from a Shared Drive with backoff retry."""
    for attempt in range(3):
        try:
            request = _get_drive_service().files().get_media(fileId=file_id, supportsAllDrives=True)
            with open(local_dest_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            return local_dest_path
        except Exception:
            if attempt < 2:
                time.sleep(2.0 * (2**attempt) + random.uniform(0, 1))
                continue
            raise


def upload_excel_to_drive(local_path: str, filename: str, folder_id: str) -> str:
    """Publishes the Excel workbook into the target Drive folder (updates if file exists)."""
    media = MediaFileUpload(
        local_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=False,
    )

    q = f"{_literal(folder_id)} in parents and name = {_literal(filename)} and trashed = false"
    try:
        existing = (
            _get_drive_service()
            .files()
            .list(q=q, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True)
            .execute()
        )
        files = existing.get("files", [])
        if files:
            file_id = files[0]["id"]
            updated = (
                _get_drive_service()
                .files()
                .update(fileId=file_id, media_body=media, supportsAllDrives=True)
                .execute()
            )
            return updated["id"]
    except Exception:
        pass

    file_metadata = {"name": filename, "parents": [folder_id]}
    created = (
        _get_drive_service()
        .files()
        .create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True)
        .execute()
    )
    return created["id"]


def list_files_in_folder(folder_id: str) -> list:
    """Scans a Google Drive folder and returns metadata for all non-trashed items."""
    service = _get_drive_service()
    q = f"{_literal(folder_id)} in parents and trashed = false"
    try:
        response = (
            service.files()
            .list(
                q=q,
                fields="files(id, name, mimeType)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        return response.get("files", [])
    except Exception as e:
        print(f"❌ [ERROR] Failed to list files in folder {folder_id}: {e}")
        return []


def export_gsheet_to_excel(file_id: str, local_dest_path: str) -> str:
    """Exports a native Google Sheet file as an Excel binary stream with backoff retry."""
    for attempt in range(3):
        try:
            request = (
                _get_drive_service()
                .files()
                .export_media(
                    fileId=file_id,
                    mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            )
            with open(local_dest_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            return local_dest_path
        except Exception as e:
            if attempt < 2:
                time.sleep(2.0 * (2**attempt) + random.uniform(0, 1))
                continue
            raise e


def move_file_in_drive(
    file_id: str, current_parent_id: str, target_parent_id: str, new_filename: str | None = None
) -> None:
    """Moves and renames a file in Google Drive to the date archive folder."""
    try:
        service = _get_drive_service()
        file = (
            service.files().get(fileId=file_id, fields="parents", supportsAllDrives=True).execute()
        )
        parents = file.get("parents", [])
        previous_parents = ",".join(parents) if parents else current_parent_id

        body = {}
        if new_filename:
            body["name"] = new_filename

        updated_file = (
            service.files()
            .update(
                fileId=file_id,
                addParents=target_parent_id,
                removeParents=previous_parents,
                body=body,
                fields="id, parents, name",
                supportsAllDrives=True,
            )
            .execute()
        )
        print(
            f"📦 [ARCHIVE SUCCESS] Moved file {file_id} ('{updated_file.get('name')}') to Processed folder {target_parent_id}"
        )
    except Exception as e:
        print(f"⚠️ [ARCHIVE ERROR] Failed to move file {file_id}: {e}")


def get_or_create_date_folder(parent_folder_id: str) -> str:
    """Finds or creates a subfolder named YYYY-MM-DD inside parent_folder_id."""
    service = _get_drive_service()
    today_str = datetime.now().strftime("%Y-%m-%d")

    query = f"{_literal(parent_folder_id)} in parents and name = {_literal(today_str)} and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    try:
        response = (
            service.files()
            .list(
                q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
            )
            .execute()
        )
        files = response.get("files", [])
        if files:
            return files[0]["id"]
    except Exception as search_err:
        print(f"⚠️ Error searching for date folder: {search_err}")

    folder_metadata = {
        "name": today_str,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    created = (
        service.files().create(body=folder_metadata, fields="id", supportsAllDrives=True).execute()
    )

    date_folder_id = created.get("id")
    print(f"📁 Created new daily archive folder '{today_str}' ({date_folder_id})")
    return date_folder_id


def delete_file_from_drive(file_id: str) -> bool:
    """Permanently deletes or trashes a temporary file from Google Drive."""
    service = _get_drive_service()
    try:
        # 1. Attempt permanent delete
        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        print(f"🗑️ [CLEANUP] Permanently deleted file {file_id} from Drive.")
        return True
    except Exception:
        # 2. Fallback to trashing (removes from active folder view cleanly)
        try:
            service.files().update(
                fileId=file_id, body={"trashed": True}, supportsAllDrives=True
            ).execute()
            print(f"🗑️ [CLEANUP] Trashed file {file_id} in Drive.")
            return True
        except Exception as trash_err:
            print(f"⚠️ [CLEANUP WARNING] Could not delete or trash file {file_id}: {trash_err}")
            return False
