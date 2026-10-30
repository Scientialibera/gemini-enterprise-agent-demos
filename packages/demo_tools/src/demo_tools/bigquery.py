"""Run one read-only query as the agent's own identity, limited to named datasets.

The model writes the SQL, so the statement is checked before it runs: a dry run
must report a plain SELECT, and every table it reads must sit in one of the
allowed datasets. The runtime identity's IAM is the real boundary; this check
keeps a confused model from wandering into other data or running DML.
"""

from __future__ import annotations

import datetime as dt
import decimal
import logging
import os
from typing import Any

from gemini_shared import get_bootstrap_settings

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 300
# A demo dataset is a few MB; anything near this means a runaway query.
MAX_BYTES_BILLED = 2 * 1024**3
LOCATION_ENV = "DEMO_BIGQUERY_LOCATION"
DEFAULT_LOCATION = "US"

_client = None


def _bigquery_client():
    global _client
    if _client is None:
        from google.cloud import bigquery

        _client = bigquery.Client(project=get_bootstrap_settings().project_id)
    return _client


def _plain(value: Any) -> Any:
    """Make a BigQuery value JSON-safe for the model."""
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def run_readonly_query(
    sql: str, allowed_datasets: tuple[str, ...], max_rows: int = DEFAULT_MAX_ROWS
) -> dict[str, Any]:
    """Dry-run, check and run one SELECT; return its rows or a readable error.

    ``allowed_datasets`` holds ``project.dataset`` names. Errors come back as
    data rather than exceptions, so the model can read them and fix its query.
    """
    from google.cloud import bigquery

    sql = (sql or "").strip().rstrip(";")
    if not sql:
        return {"status": "error", "message": "The query is empty."}
    client = _bigquery_client()
    location = os.getenv(LOCATION_ENV, "").strip() or DEFAULT_LOCATION
    allowed = {name.lower() for name in allowed_datasets}

    try:
        dry = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
            location=location,
        )
    except Exception as exc:
        return {"status": "error", "message": _short_error(exc)}

    if (dry.statement_type or "").upper() != "SELECT":
        return {
            "status": "error",
            "message": f"Only SELECT queries are allowed, not {dry.statement_type}.",
        }
    # A deployed runtime may know its project by number rather than by ID; BigQuery
    # reports referenced tables by ID, so a numeric entry matches on the dataset alone
    # (the runtime's identity can only read its own project's data anyway).
    by_number = {name.split(".", 1)[1] for name in allowed if name.split(".", 1)[0].isdigit()}
    for table in dry.referenced_tables or []:
        dataset = f"{table.project}.{table.dataset_id}".lower()
        if dataset not in allowed and table.dataset_id.lower() not in by_number:
            return {
                "status": "error",
                "message": f"Table {table.project}.{table.dataset_id}.{table.table_id} is "
                f"outside the datasets this agent may read: {', '.join(sorted(allowed))}.",
            }

    try:
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED),
            location=location,
        )
        result = job.result(max_results=max_rows + 1, timeout=120)
        rows = [{key: _plain(value) for key, value in row.items()} for row in result]
    except Exception as exc:
        return {"status": "error", "message": _short_error(exc)}

    truncated = len(rows) > max_rows
    LOGGER.info("Read-only query returned %s row(s)", len(rows[:max_rows]))
    return {
        "status": "success",
        "row_count": min(len(rows), max_rows),
        "truncated": truncated,
        "rows": rows[:max_rows],
    }


def _short_error(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    return message.split("\n")[0][:600]
