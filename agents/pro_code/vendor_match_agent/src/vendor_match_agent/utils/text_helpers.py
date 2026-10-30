"""
Text and String Normalization Utility Module.

Provides robust string sanitization, key normalization, and user identity extraction
routines used across the vendor standardization pipeline.
"""

import logging
import re
from typing import Any, Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)


def normalize_key(text: Any) -> str:
    """Normalizes whitespace, non-breaking spaces, and casing for exact lookup matching.

    Replaces tabs, newlines, carriage returns, and non-breaking spaces (\xa0) with
    a single whitespace character, then converts the string to lowercase.

    Args:
        text: Input string or object to normalize.

    Returns:
        Normalized, lowercase string without redundant whitespace. Empty string if input is null.
    """
    try:
        if text is None or pd.isna(text):
            return ""
        s = str(text)
        cleaned = re.sub(r"[\r\n\t\xa0]+", " ", s)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip().lower()
    except Exception as err:
        logger.warning(f"⚠️ [WARNING] Failed to normalize key '{text}': {err}")
        return ""


def normalize_key_fuzzy(
    text: Any, corp_exts: Optional[Set[str]] = None, manual_excl: Optional[Set[str]] = None
) -> str:
    """Strips legal suffixes, parenthetical notes, and manual exclusion words.

    Args:
        text: Input vendor string to filter.
        corp_exts: Set of corporate extension words to strip (e.g. 'inc', 'corp', 'llc').
        manual_excl: Set of custom words to exclude from fuzzy tokens.

    Returns:
        Cleaned string containing only core identifying tokens.
    """
    try:
        if text is None or pd.isna(text):
            return ""

        corp_set = corp_exts or set()
        excl_set = manual_excl or set()

        s = str(text).lower()
        # Remove parenthetical remarks e.g. "(USA)", "(Direct Debit)"
        s = re.sub(r"\(.*?\)", " ", s)
        tokens = re.findall(r"\b\w+\b", s)
        filtered = [t for t in tokens if t not in corp_set and t not in excl_set]
        return " ".join(filtered)
    except Exception as err:
        logger.warning(f"⚠️ [WARNING] Failed in fuzzy key normalization for '{text}': {err}")
        return ""


def normalize_key_alpha_numeric(text: Any) -> str:
    """Pass 3 lookup key: Strips all non-alphanumeric characters for tolerance.

    Used as a high-recall fallback match ignoring all spaces, hyphens, and punctuation.

    Args:
        text: Input string.

    Returns:
        Lowercase alphanumeric string with no whitespace or punctuation.
    """
    try:
        if text is None or pd.isna(text):
            return ""
        return re.sub(r"[^a-z0-9]", "", str(text).lower())
    except Exception as err:
        logger.warning(f"⚠️ [WARNING] Failed in alphanumeric key normalization for '{text}': {err}")
        return ""


def sanitize_str(val: Any) -> str:
    """Cleans null values, NaN, and special characters; converts safely to stripped string.

    Args:
        val: Value to sanitize.

    Returns:
        Clean stripped string, or empty string if input was null/NaN.
    """
    try:
        if val is None or pd.isna(val):
            return ""
        return str(val).strip()
    except Exception as err:
        logger.warning(f"⚠️ [WARNING] Failed to sanitize string '{val}': {err}")
        return ""


def extract_clean_username(tool_context: Any) -> str:
    """Safely extracts the invoking user's username or email from ToolContext.

    Falls back to 'pipeline_internal' if not present or during non-interactive runs.
    Strips email domain if present for clean folder and file naming.

    Args:
        tool_context: ADK ToolContext instance or None.

    Returns:
        Sanitized username string safe for filesystem or Drive path usage.
    """
    try:
        user_id = "pipeline_internal"
        if tool_context and hasattr(tool_context, "user_id") and tool_context.user_id:
            user_id = str(tool_context.user_id)
        elif tool_context and hasattr(tool_context, "user_email") and tool_context.user_email:
            user_id = str(tool_context.user_email)

        # Strip email domain if present for cleaner folder naming
        clean_name = user_id.split("@")[0].strip()
        sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", clean_name)
        return sanitized if sanitized else "pipeline_internal"
    except Exception as err:
        logger.warning(f"⚠️ [WARNING] Failed to extract clean username: {err}")
        return "pipeline_internal"
