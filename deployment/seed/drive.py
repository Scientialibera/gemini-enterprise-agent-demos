"""Seed Google Drive with the sample performance sheet and vendor workbooks.

Idempotent: a file already in its folder (matched by name) is reused, not
uploaded again. The performance sheet's ID is exported as GROWTH_SPREADSHEET_ID
for the rest of the run when the config leaves it empty. Runs with your ADC,
which needs the Drive scope (see docs/deployment-guide.md).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .sample_drive_files import COHORT_TABS, write_files

PERFORMANCE_SHEET = "growth_performance_sample.xlsx"
SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _drive():
    import google.auth
    from googleapiclient.discovery import build

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _find(drive, folder: str, name: str) -> str | None:
    query = f"{_literal(folder)} in parents and name = {_literal(name)} and trashed = false"
    files = (
        drive.files()
        .list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True)
        .execute()
        .get("files", [])
    )
    return files[0]["id"] if files else None


def _missing_tabs(sheet_id: str) -> list[str]:
    """Cohort tabs the existing performance sheet lacks (a sheet seeded for Growth V1)."""
    import google.auth
    from googleapiclient.discovery import build

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties.title")
    titles = {s["properties"]["title"] for s in meta.execute().get("sheets", [])}
    return [tab for tab in COHORT_TABS if tab not in titles]


def _targets() -> dict[str, str]:
    """Each sample file's folder, from the agents' own settings."""
    report = os.getenv("GROWTH_REPORT_FOLDER_ID", "")
    return {
        PERFORMANCE_SHEET: os.getenv("SEED_DRIVE_PERFORMANCE_SHEET_FOLDER_ID", "") or report,
        "master_vendor_dictionary.xlsx": os.getenv("VENDOR_MATCH_DRIVE_MASTER_DICT_FOLDER_ID", ""),
        "incoming_vendors_sample.xlsx": os.getenv("VENDOR_MATCH_DRIVE_SOURCE_FOLDER_ID", ""),
    }


def seed_drive() -> dict[str, str]:
    """Upload whatever is missing; return file name -> Drive ID."""
    targets = _targets()
    missing = [name for name, folder in targets.items() if not folder]
    if missing:
        raise SystemExit(
            "seed.drive needs the Growth report folder and the Vendor Match master and source "
            f"folders in config.yaml (no folder for: {', '.join(missing)})."
        )
    drive = _drive()
    ids: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for path in write_files(Path(tmp)):
            folder = targets[path.name]
            # The sheet is stored converted, under its stem; workbooks keep their
            # extension because Vendor Match finds the dictionary by file name.
            name = path.stem if path.name == PERFORMANCE_SHEET else path.name
            from googleapiclient.http import MediaFileUpload

            existing = _find(drive, folder, name)
            if existing and path.name == PERFORMANCE_SHEET and _missing_tabs(existing):
                # Same file, so GROWTH_SPREADSHEET_ID stays valid; Drive converts the upload.
                drive.files().update(
                    fileId=existing,
                    media_body=MediaFileUpload(str(path), mimetype=XLSX_MIME),
                    supportsAllDrives=True,
                ).execute()
                ids[path.name] = existing
                print(f"DRIVE_FILE_UPDATED={name} id={existing} (now has the cohort tabs)")
                continue
            if existing:
                ids[path.name] = existing
                print(f"DRIVE_FILE_EXISTS={name} id={existing}")
                continue

            body: dict[str, object] = {"name": name, "parents": [folder]}
            if path.name == PERFORMANCE_SHEET:
                body["mimeType"] = SPREADSHEET_MIME
            created = (
                drive.files()
                .create(
                    body=body,
                    media_body=MediaFileUpload(str(path), mimetype=XLSX_MIME),
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )
            ids[path.name] = created["id"]
            print(f"DRIVE_FILE_UPLOADED={name} id={created['id']}")

    sheet = ids[PERFORMANCE_SHEET]
    configured = os.getenv("GROWTH_SPREADSHEET_ID", "")
    if not configured:
        os.environ["GROWTH_SPREADSHEET_ID"] = sheet
        print(
            f"CONFIG_SUGGESTION=agents.growth_analysis_workflow.spreadsheet_id: {sheet} "
            "(used for this run; add it to config.yaml)"
        )
    elif configured != sheet:
        print(f"NOTE=config.yaml points Growth at sheet {configured}, not the seeded {sheet}.")
    return ids
