"""Read the performance workbook as a matrix of cell values.

Two sources give the same result:

* a Google Sheet ID, read through the Sheets API as the signed-in user;
* a ``gs://bucket/path.xlsx`` workbook, read from Cloud Storage as the runtime's
  own Agent Identity, which needs no user authorization or Google Workspace.

Either way the caller gets the values as display strings, row by row, the shape
the Sheets API returns.
"""

import io
import logging
import re
import threading
import warnings
from typing import Any, Dict, List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

GCS_PREFIX = "gs://"
_workbooks: Dict[str, Any] = {}
_lock = threading.Lock()


def _load_gcs_workbook(uri: str):
    """Download and parse the workbook once per runtime process."""
    with _lock:
        if uri in _workbooks:
            return _workbooks[uri]
    from google.cloud import storage
    from openpyxl import load_workbook

    bucket_name, _, blob_name = uri[len(GCS_PREFIX) :].partition("/")
    data = storage.Client().bucket(bucket_name).blob(blob_name).download_as_bytes()
    book = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    with _lock:
        _workbooks[uri] = book
    return book


def _gcs_values(uri: str, range_name: str) -> List[List[Any]]:
    book = _load_gcs_workbook(uri)
    title = range_name.strip().strip("'")
    if title not in book.sheetnames:
        raise ValueError(f"Tab '{title}' not found in {uri}. Tabs: {', '.join(book.sheetnames)}")
    rows = []
    for row in book[title].iter_rows(values_only=True):
        values = ["" if cell is None else str(cell) for cell in row]
        while values and values[-1] == "":
            values.pop()
        rows.append(values)
    return rows


def _sheets_values(spreadsheet_id: str, range_name: str) -> List[List[Any]]:
    from googleapiclient.discovery import build

    from growth_analysis_workflow.utils.google_auth import authenticate_google_oauth

    creds = authenticate_google_oauth()
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    result = (
        service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    )
    return result.get("values", [])


def get_all_sheet_names(spreadsheet_id: str) -> List[str]:
    """Retrieves all sheet tab names from the workbook.

    .. deprecated::
        Tab names are configured in resources/agents/sheet_reader_agent.yaml.
    """
    warnings.warn(
        "get_all_sheet_names is deprecated; sheet tab names are configured in YAML.",
        DeprecationWarning,
        stacklevel=2,
    )
    if spreadsheet_id.startswith(GCS_PREFIX):
        return list(_load_gcs_workbook(spreadsheet_id).sheetnames)
    from googleapiclient.discovery import build

    from growth_analysis_workflow.utils.google_auth import authenticate_google_oauth

    service = build("sheets", "v4", credentials=authenticate_google_oauth(), cache_discovery=False)
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return [sheet["properties"]["title"] for sheet in metadata.get("sheets", [])]


def read_google_sheet(
    spreadsheet_id: str,
    range_name: str,
    header_row: int,
) -> Tuple[pd.DataFrame, List[List[Any]]]:
    """Fetches one tab's values and parses them into a DataFrame.

    Args:
        spreadsheet_id: A Google Sheet ID, or a gs:// URI of an .xlsx workbook.
        range_name: The tab name, optionally quoted.
        header_row: 1-indexed row number containing column headers.

    Returns:
        Tuple of (DataFrame of the rows below the header, raw 2D values matrix).
    """
    try:
        if spreadsheet_id.startswith(GCS_PREFIX):
            values = _gcs_values(spreadsheet_id, range_name)
        else:
            values = _sheets_values(spreadsheet_id, range_name)

        header_index = header_row - 1
        if len(values) <= header_index:
            return pd.DataFrame(), values

        df = pd.DataFrame(values)
        raw_headers = df.iloc[header_index].tolist()

        headers = [
            re.sub(r"\s+", " ", str(val)).strip()
            if pd.notna(val) and str(val).strip() != ""
            else f"Column_{i + 1}"
            for i, val in enumerate(raw_headers)
        ]
        seen = {}
        unique_headers = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)

        df.columns = unique_headers
        df = df.iloc[header_index + 1 :].reset_index(drop=True)
        df = df.dropna(axis=1, how="all")
        return df, values

    except Exception as e:
        logger.error(f"Error reading sheet range '{range_name}': {e}")
        raise
