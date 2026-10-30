"""
Batch Manifest and Source Ingestion Helper Utility Module.

Provides functions for chunk slicing, batch job manifests, extracting chat attachments,
and ingesting raw vendor records from Google Drive folders.
"""

import base64
import inspect
import io
import logging
import math
import os
import uuid
from typing import Any, Dict, List, Tuple

import pandas as pd

from vendor_match_agent.tools.drive_tools import (
    download_file_from_drive,
    export_gsheet_to_excel,
    list_files_in_folder,
)
from vendor_match_agent.utils.excel_helpers import clean_chat_filename, find_vendor_column

logger = logging.getLogger(__name__)


def create_batch_job_manifest(
    raw_vendor_names: List[str], chunk_size: int = 1000
) -> Tuple[str, dict]:
    """Slices raw vendor inputs into sub-chunks and generates a state manifest.

    Args:
        raw_vendor_names: List of all extracted raw vendor names to process.
        chunk_size: Maximum number of records per chunk (default 1000).

    Returns:
        Tuple of (job_id, manifest_dict) tracking chunk state and progress.
    """
    try:
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        total_records = len(raw_vendor_names) if raw_vendor_names else 0
        effective_chunk_size = max(1, chunk_size)
        num_chunks = math.ceil(total_records / effective_chunk_size) if total_records > 0 else 0

        chunks = {}
        for i in range(num_chunks):
            start_idx = i * effective_chunk_size
            end_idx = min((i + 1) * effective_chunk_size, total_records)
            chunk_key = str(i + 1)
            chunks[chunk_key] = {
                "status": "pending",
                "vendor_names": raw_vendor_names[start_idx:end_idx],
            }

        manifest = {
            "job_id": job_id,
            "total_records": total_records,
            "chunk_size": effective_chunk_size,
            "total_chunks": num_chunks,
            "chunks": chunks,
            "accumulated_known_resolved": {},
            "accumulated_proposed": {},
        }

        return job_id, manifest
    except Exception as err:
        logger.error(f"❌ [ERROR] Failed to create batch job manifest: {err}")
        fallback_id = f"job_{uuid.uuid4().hex[:8]}"
        return fallback_id, {
            "job_id": fallback_id,
            "total_records": 0,
            "chunk_size": chunk_size,
            "total_chunks": 0,
            "chunks": {},
            "accumulated_known_resolved": {},
            "accumulated_proposed": {},
        }


async def extract_attached_files_from_context(tool_context: Any) -> List[Tuple[str, bytes]]:
    """Extracts uploaded file artifacts from current turn's user_content.parts FIRST, falling back to latest list_artifacts.

    Args:
        tool_context: ADK ToolContext instance.

    Returns:
        List of tuples: (filename, file_bytes).
    """
    uploaded_files: List[Tuple[str, bytes]] = []
    if not tool_context:
        return uploaded_files

    def resolve_filename(part_obj: Any, default_idx: int) -> str:
        try:
            candidate = None
            if hasattr(part_obj, "file_data") and part_obj.file_data:
                fd = part_obj.file_data
                candidate = getattr(fd, "display_name", None) or getattr(fd, "filename", None)
            if not candidate and hasattr(part_obj, "inline_data") and part_obj.inline_data:
                id_obj = part_obj.inline_data
                candidate = getattr(id_obj, "display_name", None) or getattr(
                    id_obj, "filename", None
                )
            if not candidate:
                candidate = getattr(part_obj, "display_name", None) or getattr(
                    part_obj, "filename", None
                )

            if candidate and isinstance(candidate, str) and candidate.strip():
                return os.path.basename(candidate.strip())

            return f"vendor_data_part_{default_idx}.xlsx"
        except Exception as e:
            logger.debug(f"Filename resolution note: {e}")
            return f"vendor_data_part_{default_idx}.xlsx"

    # PASS 1: Check CURRENT TURN's user_content.parts FIRST (Turn-isolated attachment)
    if hasattr(tool_context, "user_content") and tool_context.user_content:
        try:
            parts = getattr(tool_context.user_content, "parts", []) or []
            file_counter = 0
            for part in parts:
                inline_data = getattr(part, "inline_data", None)
                file_data = getattr(part, "file_data", None)

                part_bytes = None
                if inline_data and getattr(inline_data, "data", None):
                    part_bytes = inline_data.data
                elif file_data:
                    art_name = getattr(file_data, "file_uri", None) or getattr(
                        file_data, "display_name", None
                    )
                    if art_name and hasattr(tool_context, "load_artifact"):
                        try:
                            art_val = tool_context.load_artifact(art_name)
                            part_bytes = await art_val if inspect.isawaitable(art_val) else art_val
                        except Exception:
                            pass

                if part_bytes:
                    file_counter += 1
                    real_name = resolve_filename(part, file_counter)
                    uploaded_files.append((real_name, part_bytes))
        except Exception as e:
            logger.debug(f"User content parts lookup note: {e}")

    # PASS 2: Fall back to list_artifacts ONLY if current turn user_content had no inline parts
    if not uploaded_files and hasattr(tool_context, "list_artifacts"):
        try:
            artifacts_res = tool_context.list_artifacts()
            artifacts = await artifacts_res if inspect.isawaitable(artifacts_res) else artifacts_res

            if artifacts:
                # Take ONLY the latest uploaded artifact to prevent ingesting historic files
                latest_art_name = artifacts[-1] if isinstance(artifacts, list) else artifacts
                art_val = (
                    tool_context.load_artifact(latest_art_name)
                    if hasattr(tool_context, "load_artifact")
                    else latest_art_name
                )
                artifact = await art_val if inspect.isawaitable(art_val) else art_val

                art_data = None
                if artifact:
                    if hasattr(artifact, "inline_data") and artifact.inline_data:
                        art_data = getattr(artifact.inline_data, "data", None)
                    elif hasattr(artifact, "data"):
                        art_data = artifact.data
                    elif isinstance(artifact, (bytes, str)):
                        art_data = artifact
                if art_data:
                    real_name = resolve_filename(artifact, 1)
                    uploaded_files.append((real_name, art_data))
        except Exception as e:
            logger.debug(f"Artifact lookup note: {e}")

    return uploaded_files


def _parse_uploaded_tabular_sheets(
    raw_data: bytes, local_path: str, raw_filename: str = ""
) -> List[pd.DataFrame]:
    """Parses tabular sheets from raw bytes or local file path with header detection fallbacks."""
    dfs_to_process = []
    try:
        try:
            xls = pd.ExcelFile(io.BytesIO(raw_data), engine="openpyxl")
            for sheet_name in xls.sheet_names:
                df_0 = pd.read_excel(xls, sheet_name=sheet_name, header=0)
                if find_vendor_column(df_0, strict_pass=True):
                    dfs_to_process.append(df_0)
                else:
                    matched_df = None
                    for h_offset in range(1, 5):
                        try:
                            df_h = pd.read_excel(xls, sheet_name=sheet_name, header=h_offset)
                            if find_vendor_column(df_h, strict_pass=True):
                                matched_df = df_h
                                break
                        except Exception:
                            continue
                    dfs_to_process.append(matched_df if matched_df is not None else df_0)
        except Exception:
            try:
                xls = pd.ExcelFile(local_path)
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(local_path, sheet_name=sheet_name)
                    dfs_to_process.append(df)
            except Exception:
                try:
                    df = pd.read_csv(io.BytesIO(raw_data))
                    dfs_to_process.append(df)
                except Exception:
                    df = pd.read_csv(local_path, encoding="latin1", on_bad_lines="skip")
                    dfs_to_process.append(df)
    except Exception as parse_err:
        logger.warning(f"⚠️ Could not parse chat attachment '{raw_filename}': {parse_err}")

    return dfs_to_process


def ingest_chat_uploads(
    uploaded_files: List[Tuple[str, bytes]], temp_dir: str
) -> Tuple[Dict[str, str], List[str]]:
    """Reads uploaded files attached in chat, sanitizing filenames for archiving.

    Args:
        uploaded_files: List of (raw_filename, content_bytes) tuples.
        temp_dir: Local temporary directory to write files.

    Returns:
        Tuple of (grouped_uploads_dict, raw_extracted_vendor_names).
    """
    grouped_uploads: Dict[str, str] = {}
    raw_extracted_names: List[str] = []

    for raw_filename, content_bytes in uploaded_files:
        if not content_bytes:
            continue

        try:
            clean_display_name = clean_chat_filename(raw_filename)

            raw_data = content_bytes
            if isinstance(raw_data, str):
                try:
                    raw_data = base64.b64decode(raw_data)
                except Exception:
                    raw_data = raw_data.encode("utf-8")
            elif isinstance(raw_data, bytes):
                if (
                    raw_data.startswith(b"UEsD")
                    or raw_data.startswith(b"0M8R")
                    or raw_data.startswith(b"7zXZ")
                ):
                    try:
                        raw_data = base64.b64decode(raw_data)
                    except Exception:
                        pass

            local_path = os.path.join(temp_dir, clean_display_name)
            with open(local_path, "wb") as f:
                f.write(raw_data)

            dfs_to_process = _parse_uploaded_tabular_sheets(raw_data, local_path, raw_filename)
            if not dfs_to_process:
                continue

            file_record_count = 0
            for df in dfs_to_process:
                col_match = find_vendor_column(df)
                if col_match and col_match in df.columns:
                    vendor_list = df[col_match].dropna().astype(str).tolist()
                    raw_extracted_names.extend(vendor_list)
                    file_record_count += len(vendor_list)

            grouped_uploads[clean_display_name] = base64.b64encode(raw_data).decode("utf-8")
            logger.info(
                f"📎 [CHAT UPLOAD] Ingested '{clean_display_name}' -> extracted {file_record_count} record(s)."
            )
        except Exception as file_err:
            logger.error(
                f"❌ [ERROR] Failed processing chat attachment '{raw_filename}': {file_err}"
            )

    return grouped_uploads, raw_extracted_names


def ingest_drive_source_folder(
    source_folder_id: str, temp_dir: str
) -> Tuple[List[Dict[str, str]], List[str], int]:
    """Downloads and extracts vendor names from incoming Google Drive files.

    Args:
        source_folder_id: Google Drive folder ID for source input files.
        temp_dir: Local temporary directory for downloading files.

    Returns:
        Tuple of (files_to_archive, raw_extracted_vendor_names, total_files_count).
    """
    files_to_archive: List[Dict[str, str]] = []
    raw_extracted_names: List[str] = []

    try:
        files_found = list_files_in_folder(source_folder_id)
    except Exception as list_err:
        logger.error(
            f"❌ [ERROR] Failed to list source Drive folder '{source_folder_id}': {list_err}"
        )
        return files_to_archive, raw_extracted_names, 0

    for f_info in files_found:
        try:
            f_id = f_info["id"]
            f_name = f_info["name"]
            mime_type = f_info.get("mimeType", "")

            local_path = os.path.join(
                temp_dir, f_name if f_name.endswith(".xlsx") else f"{f_name}.xlsx"
            )
            logger.info(f"📄 Ingesting Drive File: {f_name}")

            if mime_type == "application/vnd.google-apps.spreadsheet":
                export_gsheet_to_excel(f_id, local_path)
            else:
                try:
                    download_file_from_drive(f_id, local_path)
                except Exception:
                    export_gsheet_to_excel(f_id, local_path)

            files_to_archive.append({"id": f_id, "name": f_name})

            dfs_to_process = []
            if f_name.lower().endswith(".csv"):
                df = pd.read_csv(local_path)
                dfs_to_process.append(df)
            else:
                xls = pd.ExcelFile(local_path)
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(local_path, sheet_name=sheet_name)
                    dfs_to_process.append(df)

            for df in dfs_to_process:
                col_match = find_vendor_column(df)
                if col_match and col_match in df.columns:
                    vendor_list = df[col_match].dropna().astype(str).tolist()
                    raw_extracted_names.extend(vendor_list)
        except Exception as e:
            logger.warning(f"⚠️ Could not read sheets from '{f_info.get('name')}': {e}")

    return files_to_archive, raw_extracted_names, len(files_found)
