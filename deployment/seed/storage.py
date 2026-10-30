"""Upload the Growth performance workbook to Cloud Storage for the demo setup.

When ``GROWTH_SPREADSHEET_ID`` is a ``gs://`` .xlsx URI, the workflow reads the
workbook from there as its own identity. This writes the synthetic workbook,
with its "last 6 weeks ending" date set to three days ago so the weather archive
covers it, and replaces the object on every run.
"""

from __future__ import annotations

import io
import os

SPREADSHEET_ENV = "GROWTH_SPREADSHEET_ID"
GCS_PREFIX = "gs://"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def seed_performance_workbook(project_id: str) -> str | None:
    """Write the sample workbook to the configured gs:// URI; None when not configured."""
    uri = os.getenv(SPREADSHEET_ENV, "").strip()
    if not uri.startswith(GCS_PREFIX):
        return None
    from google.cloud import storage

    from .sample_drive_files import performance_workbook

    bucket_name, _, blob_name = uri[len(GCS_PREFIX) :].partition("/")
    if not blob_name:
        raise SystemExit(f"{SPREADSHEET_ENV} must name an object: gs://<bucket>/<path>.xlsx")
    buffer = io.BytesIO()
    performance_workbook().save(buffer)
    client = storage.Client(project=project_id)
    client.bucket(bucket_name).blob(blob_name).upload_from_string(
        buffer.getvalue(), content_type=XLSX_MIME
    )
    print(f"PERFORMANCE_WORKBOOK_UPLOADED={uri}")
    return uri
