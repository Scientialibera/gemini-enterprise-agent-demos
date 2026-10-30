"""Generic data cleaning and parsing utilities for DataFrames and string values."""

import re
from typing import Any, Optional

import pandas as pd


def clean_key(val: Any) -> str:
    """Strips newlines, spaces, and non-alphanumeric characters for fuzzy key matching.

    Args:
        val: Any string or scalar value to normalize.

    Returns:
        Cleaned lowercase alphanumeric string.
    """
    if val is None or pd.isna(val):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(val).lower())


def parse_num(val: Any) -> float:
    """Parses currency, percentages, shorthand notation ($16K, 1.1M, 2B), and numeric strings into floats.

    Args:
        val: Raw numeric, currency, or percentage value from a sheet or table.

    Returns:
        Parsed float representation (e.g. '16K' -> 16000.0, '5%' -> 0.05).
        Returns 0.0 for empty, invalid, or NA values.
    """
    if pd.isna(val) or val is None or str(val).strip() in ["", "-", "N/A", "null"]:
        return 0.0

    s = str(val).replace("$", "").replace(",", "").strip()
    is_pct = "%" in s
    s = s.replace("%", "")

    multiplier = 1.0
    if s.lower().endswith("k"):
        multiplier = 1_000.0
        s = s[:-1].strip()
    elif s.lower().endswith("m"):
        multiplier = 1_000_000.0
        s = s[:-1].strip()
    elif s.lower().endswith("b"):
        multiplier = 1_000_000_000.0
        s = s[:-1].strip()

    try:
        res = float(s) * multiplier
        return res / 100.0 if is_pct else res
    except (ValueError, TypeError):
        return 0.0


def clean_val(val: Any) -> str:
    """Safely converts DataFrame values to strings for Google Docs insertion.

    Args:
        val: Raw cell or table value.

    Returns:
        Clean stripped string, or empty string if NA / None.
    """
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip()


def get_first_col(df_raw: pd.DataFrame, target_name: str) -> Optional[pd.Series]:
    """Retrieves the FIRST left-to-right column match to avoid trailing empty duplicate columns.

    Args:
        df_raw: Source pandas DataFrame.
        target_name: The expected header name to search for.

    Returns:
        pandas Series of the first matched column, or None if not found.
    """
    target_key = clean_key(target_name)
    for col in df_raw.columns:
        if clean_key(col) == target_key:
            val = df_raw[col]
            return val.iloc[:, 0] if isinstance(val, pd.DataFrame) else val
    return None
