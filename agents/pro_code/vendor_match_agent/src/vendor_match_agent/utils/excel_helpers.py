"""
Excel and Tabular File Helper Utility Module.

Provides robust column identification heuristics, cell data cleaning, and filename
sanitization for Excel and CSV data processing.
"""

import logging
import re
from typing import Any, List, Optional

import pandas as pd

from vendor_match_agent.pipeline_config import load_yaml_config

logger = logging.getLogger(__name__)

# Load configuration for default governance columns
CONFIG = load_yaml_config("config/pipeline_config.yaml")
TARGET_VENDOR_COLUMNS: List[str] = CONFIG.get("governance", {}).get(
    "target_columns",
    [
        "supplier name",
        "vendor_name",
        "vendor",
        "vendor name",
        "supplier",
        "payee",
        "company name",
    ],
)
COLUMN_KEYWORDS: List[str] = CONFIG.get("governance", {}).get(
    "column_keywords",
    [
        "vendor",
        "supplier",
        "payee",
        "company name",
        "name",
    ],
)


# Regex matching illegal XML / ASCII control characters that crash openpyxl
ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


def clean_excel_str(val: Any) -> str:
    """Safely converts Excel cell values to clean strings, stripping illegal XML characters.

    Args:
        val: Cell value of any type.

    Returns:
        Stripped string safe for openpyxl serialization. Empty string if null/NaN.
    """
    try:
        if val is None or pd.isna(val):
            return ""
        val_str = str(val)
        return ILLEGAL_CHARACTERS_RE.sub("", val_str).strip()
    except Exception as err:
        logger.warning(f"⚠️ [WARNING] Failed to clean Excel string value: {err}")
        return ""


def clean_chat_filename(filename: str) -> str:
    """Cleans up internal artifact suffixes like 'File.xlsx_Sheet1_Sheet1.csv' -> 'File.xlsx'.

    Args:
        filename: Raw artifact or attachment filename.

    Returns:
        Sanitized filename with valid tabular file extension.
    """
    try:
        if not filename or not str(filename).strip():
            return "vendor_data.xlsx"

        clean = re.sub(r"(_Sheet\d+)+.*$", "", str(filename), flags=re.IGNORECASE)
        clean = re.sub(r"(_Chat_Query.*)+$", "", clean, flags=re.IGNORECASE)
        clean = clean.strip()
        if not clean.lower().endswith((".xlsx", ".xls", ".csv")):
            clean += ".xlsx"
        return clean
    except Exception as err:
        logger.warning(f"⚠️ [WARNING] Error cleaning chat filename '{filename}': {err}")
        return "vendor_data.xlsx"


def find_vendor_column(
    df_or_columns: Any, target_columns: Optional[List[str]] = None, strict_pass: bool = False
) -> Optional[str]:
    """Finds the vendor column matching target governance headers.

    Uses a three-tier heuristic algorithm:
    1. Exact match against target governance headers (with underscore tolerance).
    2. Substring keyword match ('vendor', 'supplier', 'payee', 'company name', 'name').
    3. Fallback to Column 0 (unless strict_pass=True).

    Args:
        df_or_columns: DataFrame, list of column strings, or pd.Index.
        target_columns: Optional list of header names to prioritize.
        strict_pass: If True, skips Column 0 fallback during header offset scanning.

    Returns:
        String name of the matching column, or None if no match is found.
    """
    try:
        if isinstance(df_or_columns, pd.DataFrame):
            if df_or_columns is None or df_or_columns.empty:
                return None
            cols = df_or_columns.columns.tolist()
        elif isinstance(df_or_columns, (list, tuple, pd.Index)):
            cols = list(df_or_columns)
        else:
            return None

        if not cols:
            return None

        targets = target_columns or TARGET_VENDOR_COLUMNS
        target_set = {str(t).strip().lower() for t in targets}
        target_set_no_underscores = {str(t).strip().lower().replace("_", " ") for t in targets}

        # Pass 1: Exact Match against configured target governance headers
        for col in cols:
            col_clean = str(col).strip().lower()
            col_no_underscore = col_clean.replace("_", " ")
            if col_clean in target_set or col_no_underscore in target_set_no_underscores:
                return str(col)

        # Pass 2: Keyword match for vendor/supplier/payee/company
        for col in cols:
            col_clean = str(col).strip().lower()
            if any(keyword in col_clean for keyword in COLUMN_KEYWORDS):
                return str(col)

        # Pass 3: Ultimate Fallback (Defaults to Column 0 if not running in strict pass mode)
        if strict_pass:
            return None

        return str(cols[0])
    except Exception as err:
        logger.error(f"❌ [ERROR] Exception in find_vendor_column: {err}")
        return None
