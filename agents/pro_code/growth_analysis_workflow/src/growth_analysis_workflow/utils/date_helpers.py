"""Date manipulation and L6W (42-day) window calculation utilities."""

import datetime
from datetime import timedelta, timezone
from typing import Optional, Tuple


def parse_target_date(target_date_str: Optional[str]) -> datetime.date:
    """Parses a target date string (YYYY-MM-DD) or defaults to current UTC date.

    Args:
        target_date_str: Target reference date string in YYYY-MM-DD format.

    Returns:
        datetime.date: Parsed date object or current date in UTC.
    """
    if target_date_str and isinstance(target_date_str, str) and target_date_str.strip():
        try:
            return datetime.datetime.strptime(target_date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            pass
    return datetime.datetime.now(timezone.utc).date()


def get_l6w_date_bounds(
    target_date_str: Optional[str] = None,
    days_back: int = 42,
) -> Tuple[datetime.date, datetime.date]:
    """Calculates the canonical L6W date window (start_date, ref_date).

    Args:
        target_date_str: Optional reference date string (YYYY-MM-DD). Defaults to today UTC.
        days_back: Number of days in lookback window (default: 42 days for L6W).

    Returns:
        Tuple of (start_date, ref_date).
    """
    ref_date = parse_target_date(target_date_str)
    start_date = ref_date - timedelta(days=days_back)
    return start_date, ref_date
