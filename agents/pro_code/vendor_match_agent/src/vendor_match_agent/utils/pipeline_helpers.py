"""
Pipeline Helpers Central Module.

Aggregates and re-exports specialized utilities for text normalization, Excel parsing,
staging persistence, and manifest management.
Maintains full backward compatibility for all pipeline callers.
"""

import logging

# Re-export Excel and column identification utilities
from vendor_match_agent.utils.excel_helpers import (
    TARGET_VENDOR_COLUMNS,
    clean_chat_filename,
    clean_excel_str,
    find_vendor_column,
)

# Re-export manifest and file ingestion utilities
from vendor_match_agent.utils.manifest_helpers import (
    create_batch_job_manifest,
    extract_attached_files_from_context,
    ingest_chat_uploads,
    ingest_drive_source_folder,
)

# Re-export Drive staging and archiving utilities
from vendor_match_agent.utils.staging_helpers import (
    SetEncoder,
    archive_processed_inputs,
    create_review_staging_workbook,
    delete_staged_payload_from_drive,
    load_staged_payload_from_drive,
    save_staged_payload_to_drive,
)

# Re-export text and identity utilities
from vendor_match_agent.utils.text_helpers import (
    extract_clean_username,
    normalize_key,
    normalize_key_alpha_numeric,
    normalize_key_fuzzy,
    sanitize_str,
)

logger = logging.getLogger(__name__)

__all__ = [
    "extract_clean_username",
    "sanitize_str",
    "normalize_key",
    "normalize_key_fuzzy",
    "normalize_key_alpha_numeric",
    "clean_excel_str",
    "clean_chat_filename",
    "find_vendor_column",
    "TARGET_VENDOR_COLUMNS",
    "SetEncoder",
    "archive_processed_inputs",
    "delete_staged_payload_from_drive",
    "save_staged_payload_to_drive",
    "load_staged_payload_from_drive",
    "create_review_staging_workbook",
    "create_batch_job_manifest",
    "extract_attached_files_from_context",
    "ingest_chat_uploads",
    "ingest_drive_source_folder",
]
