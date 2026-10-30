"""
Staging and Cloud State Persistence Helper Utility Module.

Provides robust functions for persisting, loading, cleaning, and archiving
session-level staging payloads and input files in Google Drive.
"""

import base64
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from vendor_match_agent.pipeline_config import load_yaml_config
from vendor_match_agent.tools.drive_tools import (
    delete_file_from_drive,
    download_file_from_drive,
    get_or_create_date_folder,
    list_files_in_folder,
    move_file_in_drive,
    upload_excel_to_drive,
)
from vendor_match_agent.utils.excel_helpers import clean_excel_str

CONFIG = load_yaml_config("config/pipeline_config.yaml")

logger = logging.getLogger(__name__)


class SetEncoder(json.JSONEncoder):
    """Custom JSON encoder to automatically convert Python sets to lists during serialization."""

    def default(self, obj: Any) -> Any:
        try:
            if isinstance(obj, set):
                return list(obj)
            return super().default(obj)
        except Exception as err:
            logger.warning(f"⚠️ [WARNING] SetEncoder fallback error: {err}")
            return str(obj)


def save_staged_payload_to_drive(cache_key: str, payload: dict, processed_folder_id: str) -> None:
    """Persists staged resolution payload as a JSON file in Drive, purging old duplicate snapshots.

    Args:
        cache_key: Unique cache key identifying the user or session.
        payload: Dict containing staged resolution records, metrics, and mappings.
        processed_folder_id: Google Drive folder ID for processed/staging files.
    """
    try:
        if not cache_key or not processed_folder_id:
            logger.warning(
                "⚠️ [WARNING] Missing cache_key or processed_folder_id for save_staged_payload_to_drive."
            )
            return

        staged_prefix = (
            CONFIG.get("drive", {}).get("files", {}).get("staging_payload_prefix", "_staged_")
        )
        staged_filename = f"{staged_prefix}{cache_key}.json"

        # REMOVED: Manual purge loop that was deleting files before upload

        with tempfile.TemporaryDirectory() as tmp_dir:
            local_json_path = os.path.join(tmp_dir, staged_filename)
            with open(local_json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, cls=SetEncoder)

            # Native update in-place handled by upload_excel_to_drive
            upload_excel_to_drive(
                local_path=local_json_path, filename=staged_filename, folder_id=processed_folder_id
            )
            logger.info(
                f"💾 [CLOUD STAGING] Persisted staged payload to Drive: '{staged_filename}'"
            )
    except Exception as e:
        logger.warning(f"⚠️ [WARNING] Could not persist staged payload to Drive: {e}")
        logger.warning(f"⚠️ [WARNING] Could not persist staged payload to Drive: {e}")


def load_staged_payload_from_drive(cache_key: str, processed_folder_id: str) -> Optional[dict]:
    """Recovers staged resolution payload from Drive if memory cache misses across cloud workers.

    Args:
        cache_key: Unique cache key identifying the user or session.
        processed_folder_id: Google Drive folder ID for processed/staging files.

    Returns:
        Dict payload if recovered from Drive, otherwise None.
    """
    try:
        if not cache_key or not processed_folder_id:
            return None

        staged_prefix = (
            CONFIG.get("drive", {}).get("files", {}).get("staging_payload_prefix", "_staged_")
        )
        staged_filename = f"{staged_prefix}{cache_key}.json"
        clean_sub = cache_key.split("_")[0] if "_" in cache_key else cache_key

        files = list_files_in_folder(processed_folder_id)

        # Collect matching files and take the latest uploaded version
        matching_files = [
            f
            for f in files
            if f["name"] == staged_filename
            or (
                f["name"].startswith(staged_prefix)
                and (cache_key in f["name"] or clean_sub in f["name"])
            )
        ]

        if matching_files:
            exact_matches = [f for f in matching_files if f["name"] == staged_filename]
            target = exact_matches[-1] if exact_matches else matching_files[-1]
            file_id = target["id"]

            with tempfile.TemporaryDirectory() as tmp_dir:
                local_json_path = os.path.join(tmp_dir, staged_filename)
                download_file_from_drive(file_id, local_json_path)
                with open(local_json_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                logger.info(
                    f"📥 [CLOUD STAGING] Recovered staged payload from Drive for key '{cache_key}' (file_id: {file_id})"
                )
                return payload
    except Exception as e:
        logger.warning(f"⚠️ [WARNING] Failed to load staged payload from Drive: {e}")
    return None


def delete_staged_payload_from_drive(cache_key: str, processed_folder_id: str) -> None:
    """Deletes ALL temporary staging JSON files AND temporary review workbooks from Drive.

    Args:
        cache_key: Unique cache key identifying the user or session.
        processed_folder_id: Google Drive folder ID for processed/staging files.
    """
    try:
        if not cache_key or not processed_folder_id:
            return

        clean_sub = cache_key.split("_")[0] if "_" in cache_key else cache_key
        user_sub = cache_key.split("_")[-1] if "_" in cache_key else cache_key

        files = list_files_in_folder(processed_folder_id)
        targets = [
            f
            for f in files
            if (f["name"].startswith("_staged_") or f["name"].startswith("_STAGING_REVIEW_"))
            and (cache_key in f["name"] or clean_sub in f["name"] or user_sub in f["name"])
        ]

        if targets:
            deleted_count = 0
            for target in targets:
                try:
                    if delete_file_from_drive(target["id"]):
                        deleted_count += 1
                except Exception as del_err:
                    logger.warning(
                        f"⚠️ Could not delete staging target '{target.get('name')}': {del_err}"
                    )
            if deleted_count > 0:
                logger.info(
                    f"🗑️ [CLEANUP] Removed {deleted_count} temporary staging/review file(s) from Drive."
                )
    except Exception as e:
        logger.warning(f"⚠️ [WARNING] Cleanup error in delete_staged_payload_from_drive: {e}")


def archive_processed_inputs(
    processed_folder_id: str,
    grouped_uploads: Dict[str, str],
    files_to_archive: List[Dict[str, str]],
    source_folder_id: str,
    temp_dir: str,
    filename_prefix: str,
) -> None:
    """Moves processed source files to the Drive Processed folder inside YYYY-MM-DD subfolders.

    Args:
        processed_folder_id: Google Drive folder ID for processed archive.
        grouped_uploads: Map of filename to base64 content for uploaded files.
        files_to_archive: List of file info dicts (containing 'id' and 'name') from source folder.
        source_folder_id: Google Drive folder ID for incoming source files.
        temp_dir: Local temporary directory for staging files.
        filename_prefix: Date or timestamp prefix to prepend to archived filenames.
    """
    try:
        target_date_folder_id = get_or_create_date_folder(processed_folder_id)

        # 1. Archive Chat Uploads
        for fname, b64_str in grouped_uploads.items():
            arch_name = f"{filename_prefix}_{fname}"
            if b64_str and not b64_str.startswith("LOCAL_TEMP_"):
                try:
                    file_bytes = base64.b64decode(b64_str)
                    local_p = os.path.join(temp_dir, arch_name)
                    with open(local_p, "wb") as f:
                        f.write(file_bytes)
                    upload_excel_to_drive(local_p, arch_name, target_date_folder_id)
                    logger.info(
                        f"📦 [ARCHIVE CHAT] Successfully archived '{fname}' to Drive Processed folder as '{arch_name}'."
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Could not archive chat upload '{fname}': {e}")

        # 2. Archive Source Drive Files
        for f_info in files_to_archive:
            try:
                f_id = f_info["id"]
                f_name = f_info["name"]
                arch_name = f"{filename_prefix}_{f_name}"

                move_file_in_drive(
                    file_id=f_id,
                    current_parent_id=source_folder_id,
                    target_parent_id=target_date_folder_id,
                    new_filename=arch_name,
                )
            except Exception as move_err:
                logger.warning(
                    f"⚠️ Could not archive source file '{f_info.get('name')}': {move_err}"
                )
    except Exception as e:
        logger.error(f"❌ [ERROR] Critical failure in archive_processed_inputs: {e}")


def create_review_staging_workbook(
    proposed_mappings: Dict[str, List[str]],
    known_resolved_map: Dict[str, List[str]],
    processed_folder_id: str,
    temp_dir: str,
    session_prefix: str,
) -> Tuple[str, str]:
    """Helper: Builds a temporary 2-tab Excel review sheet in Drive for large datasets.

    Args:
        proposed_mappings: Mapping of proposed standardized master names to their resolved raw variants.
        known_resolved_map: Mapping of existing master dictionary names to auto-matched raw variants.
        processed_folder_id: Google Drive folder ID where the staging review file will be stored.
        temp_dir: Local temporary directory path for staging the Excel file before upload.
        session_prefix: Clean session prefix string used to name the staging file uniquely.

    Returns:
        Tuple containing (drive_file_id, drive_file_url). Returns ("", "") on failure.
    """
    try:
        gov_staging = CONFIG.get("governance", {}).get("staging_review_sheet", {})
        review_prefix = (
            CONFIG.get("drive", {})
            .get("files", {})
            .get("staging_review_prefix", "_STAGING_REVIEW_")
        )
        file_name = f"{review_prefix}{session_prefix}.xlsx"
        local_path = os.path.join(temp_dir, file_name)

        # Tab 1: Proposed Master Additions (newly resolved clusters)
        tab1_cfg = gov_staging.get("proposed_tab", {})
        tab1_name = tab1_cfg.get("sheet_name", "Proposed Master Additions")
        tab1_cols = tab1_cfg.get("columns", {})
        t1_master_col = tab1_cols.get("master_name", "Proposed Standardized Master Name")
        t1_vars_col = tab1_cols.get("raw_variants", "Resolved Raw Variants")
        t1_count_col = tab1_cols.get("variant_count", "Variant Count")

        proposed_rows = [
            {
                t1_master_col: clean_excel_str(master),
                t1_vars_col: ", ".join([clean_excel_str(v) for v in vars_list]),
                t1_count_col: len(vars_list),
            }
            for master, vars_list in proposed_mappings.items()
        ]
        df_proposed = pd.DataFrame(
            proposed_rows
            if proposed_rows
            else [{t1_master_col: "None", t1_vars_col: "None", t1_count_col: 0}]
        )

        # Tab 2: Instant Dictionary Matches (known mappings matched via cache)
        tab2_cfg = gov_staging.get("matched_tab", {})
        tab2_name = tab2_cfg.get("sheet_name", "Instant Dictionary Matches")
        tab2_cols = tab2_cfg.get("columns", {})
        t2_master_col = tab2_cols.get("master_name", "Master Dictionary Name")
        t2_vars_col = tab2_cols.get("matched_variants", "Auto-Matched Input Variants")
        t2_count_col = tab2_cols.get("variant_count", "Variant Count")

        matched_rows = [
            {
                t2_master_col: clean_excel_str(master),
                t2_vars_col: ", ".join([clean_excel_str(v) for v in vars_list]),
                t2_count_col: len(vars_list),
            }
            for master, vars_list in known_resolved_map.items()
        ]
        df_matched = pd.DataFrame(
            matched_rows
            if matched_rows
            else [{t2_master_col: "None", t2_vars_col: "None", t2_count_col: 0}]
        )

        # Clean entire DataFrames as a safeguard against openpyxl XML errors
        df_proposed = df_proposed.map(clean_excel_str)
        df_matched = df_matched.map(clean_excel_str)

        # Write two-tab Excel review workbook
        with pd.ExcelWriter(local_path, engine="openpyxl") as writer:
            df_proposed.to_excel(writer, sheet_name=tab1_name, index=False)
            df_matched.to_excel(writer, sheet_name=tab2_name, index=False)

        # Upload staging workbook to Drive
        file_id = upload_excel_to_drive(
            local_path=local_path, filename=file_name, folder_id=processed_folder_id
        )
        file_url = f"https://drive.google.com/open?id={file_id}"
        logger.info(
            f"📊 [STAGING REVIEW] Uploaded staging review sheet to Drive: '{file_name}' (ID: {file_id})"
        )
        return file_id, file_url
    except Exception as e:
        logger.error(f"❌ [ERROR] Failed to create review staging workbook: {e}")
        return "", ""
