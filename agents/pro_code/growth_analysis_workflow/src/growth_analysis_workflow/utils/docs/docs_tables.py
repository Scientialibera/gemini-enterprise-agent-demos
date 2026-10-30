"""Google Docs styled table builders for store cohort performance and macro insights."""

import logging
from typing import Any, Dict, List, Tuple

import pandas as pd
from googleapiclient.errors import HttpError

from growth_analysis_workflow.utils.data_helpers import clean_val
from growth_analysis_workflow.utils.docs.docs_styles import DEFAULT_PALETTE

logger = logging.getLogger(__name__)


def _build_cohort_table_matrix(df: pd.DataFrame) -> Tuple[List[str], List[List[str]]]:
    """Extracts and sanitizes store cohort DataFrame into a 2D string matrix."""
    headers = [
        "Kitchen Name",
        "L6W SSS / YoY",
        "GOV",
        "Kitchen GOV",
        "MP GOV",
        "Traffic",
        "Conv %",
        "Taste Rating",
        "IOR",
        "In stock Rate",
        "% daypart (% dinner)",
        "% Promo GOV",
    ]
    table_matrix = [headers]
    for _, row in df.iterrows():
        table_matrix.append(
            [
                clean_val(row.get("Kitchen Name")),
                clean_val(row.get("L6W SSS or YoY (Kitchen + MP)")),
                clean_val(row.get("GOV (Kitchen + MP)")),
                clean_val(row.get("GOV (Kitchen Only)")),
                clean_val(row.get("GOV (MP Only)")),
                clean_val(row.get("App / Web Traffic (1P) - Overall")),
                clean_val(row.get("Conversion (1P)")),
                clean_val(row.get("Taste Rating (Kitchen)")),
                clean_val(row.get("IOR % (Kitchen) Target = < 10%")),
                clean_val(row.get("In-Stock Rate %")),
                clean_val(row.get("Dinner Mix % Total GOV")),
                clean_val(row.get("Promo GOV % 1P GOV")),
            ]
        )
    return headers, table_matrix


def append_styled_section(
    docs_service,
    doc_id: str,
    section_title: str,
    df: pd.DataFrame,
    palette: Dict[str, Any] = DEFAULT_PALETTE,
    start_on_new_page: bool = False,
) -> None:
    """Appends a styled store performance table (Section 1, 2, or 3) using batched API requests."""
    if df.empty:
        logger.warning(f"Skipping '{section_title}' because DataFrame is empty.")
        return

    headers, table_matrix = _build_cohort_table_matrix(df)
    rows_count = len(table_matrix)
    cols_count = len(headers)

    try:
        # Step 1: Single GET to locate current end index
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = max(1, doc.get("body").get("content")[-1].get("endIndex") - 1)

        # Step 2: Batch 1 POST - Title Text & Empty Table Insertion
        title_text = f"{section_title}\n\n"
        title_len = len(section_title)

        batch1_requests = []
        current_idx = end_index

        if start_on_new_page:
            batch1_requests.append({"insertPageBreak": {"location": {"index": current_idx}}})
            current_idx += 1

        batch1_requests.extend(
            [
                {"insertText": {"location": {"index": current_idx}, "text": title_text}},
                {
                    "updateTextStyle": {
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 14, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": palette["title_green"]}},
                        },
                        "range": {"startIndex": current_idx, "endIndex": current_idx + title_len},
                        "fields": "bold,fontSize,foregroundColor",
                    }
                },
                {
                    "insertTable": {
                        "rows": rows_count,
                        "columns": cols_count,
                        "location": {"index": current_idx + len(title_text)},
                    }
                },
            ]
        )

        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": batch1_requests}
        ).execute()

        # Step 3: Single GET to retrieve exact table start index and cell paragraph indices
        doc = docs_service.documents().get(documentId=doc_id).execute()
        content_elems = doc.get("body", {}).get("content", [])

        table_elem = None
        table_start_index = 0
        for elem in reversed(content_elems):
            if "table" in elem:
                table_elem = elem["table"]
                table_start_index = elem["startIndex"]
                break

        if not table_elem:
            raise ValueError(f"Could not locate inserted table for section: {section_title}")

        # Step 4: Construct ALL cell text insertions, cell styles, and text styles into BATCH 2
        batch2_requests = []

        # 4a. Map cell insertion indices (Reverse order so lower index positions don't shift)
        cell_updates = []
        for r, row in enumerate(table_elem.get("tableRows", [])):
            for c, cell in enumerate(row.get("tableCells", [])):
                if r < rows_count and c < cols_count:
                    cell_text = str(table_matrix[r][c])
                    p_start = cell["content"][0]["paragraph"]["elements"][0]["startIndex"]
                    cell_updates.append((p_start, cell_text))

        cell_updates.sort(key=lambda x: x[0], reverse=True)
        for idx, txt in cell_updates:
            if txt:
                batch2_requests.append({"insertText": {"location": {"index": idx}, "text": txt}})

        # 4b. Table cell background & padding styles
        batch2_requests.extend(
            [
                {
                    "updateTableCellStyle": {
                        "tableCellStyle": {
                            "backgroundColor": {"color": {"rgbColor": palette["header_green"]}},
                            "paddingTop": {"magnitude": 5, "unit": "PT"},
                            "paddingBottom": {"magnitude": 5, "unit": "PT"},
                        },
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": 0,
                                "columnIndex": 0,
                            },
                            "rowSpan": 1,
                            "columnSpan": cols_count,
                        },
                        "fields": "backgroundColor,paddingTop,paddingBottom",
                    }
                },
                {
                    "updateTableCellStyle": {
                        "tableCellStyle": {
                            "backgroundColor": {"color": {"rgbColor": palette["cell_bg"]}},
                            "paddingTop": {"magnitude": 4, "unit": "PT"},
                            "paddingBottom": {"magnitude": 4, "unit": "PT"},
                        },
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": 1,
                                "columnIndex": 0,
                            },
                            "rowSpan": rows_count - 1,
                            "columnSpan": cols_count,
                        },
                        "fields": "backgroundColor,paddingTop,paddingBottom",
                    }
                },
            ]
        )

        # Step 5: Execute BATCH 2 (Cell Text + Table Styling)
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": batch2_requests}
        ).execute()

        # Step 6: Final GET for exact text range bolding & trailing paragraph newline
        doc = docs_service.documents().get(documentId=doc_id).execute()
        for elem in reversed(doc.get("body", {}).get("content", [])):
            if "table" in elem:
                table_elem = elem["table"]
                break

        batch3_requests = []
        for r, row in enumerate(table_elem.get("tableRows", [])):
            is_header = r == 0
            for c, cell in enumerate(row.get("tableCells", [])):
                p_elem = cell["content"][0]["paragraph"]["elements"][0]
                start_idx = p_elem["startIndex"]
                end_idx = start_idx + len(table_matrix[r][c])
                if start_idx < end_idx:
                    if is_header:
                        batch3_requests.append(
                            {
                                "updateTextStyle": {
                                    "textStyle": {
                                        "bold": True,
                                        "fontSize": {"magnitude": 9, "unit": "PT"},
                                        "foregroundColor": {
                                            "color": {"rgbColor": palette["white"]}
                                        },
                                    },
                                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                                    "fields": "bold,fontSize,foregroundColor",
                                }
                            }
                        )
                    else:
                        batch3_requests.append(
                            {
                                "updateTextStyle": {
                                    "textStyle": {
                                        "fontSize": {"magnitude": 8.5, "unit": "PT"},
                                        "foregroundColor": {
                                            "color": {"rgbColor": palette["charcoal"]}
                                        },
                                    },
                                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                                    "fields": "fontSize,foregroundColor",
                                }
                            }
                        )

        final_end_index = max(1, doc.get("body").get("content")[-1].get("endIndex") - 1)
        batch3_requests.append(
            {"insertText": {"location": {"index": final_end_index}, "text": "\n\n"}}
        )

        if batch3_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": batch3_requests}
            ).execute()

        logger.info(f"Successfully appended styled table for: '{section_title}'")

    except HttpError as err:
        logger.error(f"Google Docs API Error in append_styled_section: {err}")
        raise


def append_macro_insights_table(
    docs_service,
    doc_id: str,
    tabular_data: List[Dict[str, Any]],
    palette: Dict[str, Any] = DEFAULT_PALETTE,
    start_on_new_page: bool = False,
    section_heading: str = "Section 4: Macro & Portfolio Insights\n\n",
    table_subtitle: str = "Executive Macro & Portfolio Summary Table\n\n",
) -> None:
    """Appends the 8-column executive summary table for Section 4 using batched API requests."""
    if not tabular_data:
        logger.warning("Skipping macro insights table because tabular_data is empty.")
        return

    headers = [
        "Store Name",
        "QSR Trends",
        "Weather Trends",
        "Unemployment & Labor",
        "Customer Reviews",
        "Recommendations",
    ]
    table_matrix = [headers]
    for row in tabular_data:
        table_matrix.append(
            [
                clean_val(row.get("store_name")),
                clean_val(row.get("qsr_trends")),
                clean_val(row.get("weather_trends")),
                clean_val(row.get("unemployment")),
                clean_val(row.get("customer_sentiment")),
                clean_val(row.get("recommendations")),
            ]
        )

    rows_count = len(table_matrix)
    cols_count = len(headers)

    try:
        # Step 1: Single GET to locate current end index
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = max(1, doc.get("body").get("content")[-1].get("endIndex") - 1)

        batch1_requests = []
        current_idx = end_index

        if start_on_new_page:
            batch1_requests.append({"insertPageBreak": {"location": {"index": current_idx}}})
            current_idx += 1

        intro_text = section_heading + table_subtitle
        heading_start = current_idx
        heading_end = heading_start + len(section_heading)
        subtitle_start = heading_end
        subtitle_end = heading_start + len(intro_text)

        batch1_requests.extend(
            [
                {"insertText": {"location": {"index": heading_start}, "text": intro_text}},
                {
                    "updateTextStyle": {
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 15, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": palette["title_green"]}},
                        },
                        "range": {"startIndex": heading_start, "endIndex": heading_end - 2},
                        "fields": "bold,fontSize,foregroundColor",
                    }
                },
                {
                    "updateTextStyle": {
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 11.5, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": palette["header_green"]}},
                        },
                        "range": {"startIndex": subtitle_start, "endIndex": subtitle_end - 2},
                        "fields": "bold,fontSize,foregroundColor",
                    }
                },
                {
                    "insertTable": {
                        "rows": rows_count,
                        "columns": cols_count,
                        "location": {"index": heading_start + len(intro_text)},
                    }
                },
            ]
        )

        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": batch1_requests}
        ).execute()

        # Step 2: Single GET to locate inserted table start index and cell paragraphs
        doc = docs_service.documents().get(documentId=doc_id).execute()
        content_elems = doc.get("body", {}).get("content", [])

        table_elem = None
        table_start_index = 0
        for elem in reversed(content_elems):
            if "table" in elem:
                table_elem = elem["table"]
                table_start_index = elem["startIndex"]
                break

        if not table_elem:
            raise ValueError("Could not locate inserted Section 4 Macro Table.")

        batch2_requests = []

        # 2a. Map cell text updates in reverse index order
        cell_updates = []
        for r, row in enumerate(table_elem.get("tableRows", [])):
            for c, cell in enumerate(row.get("tableCells", [])):
                if r < rows_count and c < cols_count:
                    cell_text = str(table_matrix[r][c])
                    p_start = cell["content"][0]["paragraph"]["elements"][0]["startIndex"]
                    cell_updates.append((p_start, cell_text))

        cell_updates.sort(key=lambda x: x[0], reverse=True)
        for idx, txt in cell_updates:
            if txt:
                batch2_requests.append({"insertText": {"location": {"index": idx}, "text": txt}})

        # 2b. Table cell background & padding styles
        batch2_requests.extend(
            [
                {
                    "updateTableCellStyle": {
                        "tableCellStyle": {
                            "backgroundColor": {"color": {"rgbColor": palette["header_green"]}},
                            "paddingTop": {"magnitude": 5, "unit": "PT"},
                            "paddingBottom": {"magnitude": 5, "unit": "PT"},
                            "paddingLeft": {"magnitude": 4, "unit": "PT"},
                            "paddingRight": {"magnitude": 4, "unit": "PT"},
                        },
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": 0,
                                "columnIndex": 0,
                            },
                            "rowSpan": 1,
                            "columnSpan": cols_count,
                        },
                        "fields": "backgroundColor,paddingTop,paddingBottom,paddingLeft,paddingRight",
                    }
                },
                {
                    "updateTableCellStyle": {
                        "tableCellStyle": {
                            "backgroundColor": {"color": {"rgbColor": palette["cell_bg"]}},
                            "paddingTop": {"magnitude": 4, "unit": "PT"},
                            "paddingBottom": {"magnitude": 4, "unit": "PT"},
                            "paddingLeft": {"magnitude": 4, "unit": "PT"},
                            "paddingRight": {"magnitude": 4, "unit": "PT"},
                        },
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": 1,
                                "columnIndex": 0,
                            },
                            "rowSpan": rows_count - 1,
                            "columnSpan": cols_count,
                        },
                        "fields": "backgroundColor,paddingTop,paddingBottom,paddingLeft,paddingRight",
                    }
                },
            ]
        )

        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": batch2_requests}
        ).execute()

        # Step 3: Final GET for font styling across cells
        doc = docs_service.documents().get(documentId=doc_id).execute()
        for elem in reversed(doc.get("body", {}).get("content", [])):
            if "table" in elem:
                table_elem = elem["table"]
                break

        batch3_requests = []
        for r, row in enumerate(table_elem.get("tableRows", [])):
            is_header = r == 0
            for c, cell in enumerate(row.get("tableCells", [])):
                p_elem = cell["content"][0]["paragraph"]["elements"][0]
                start_idx = p_elem["startIndex"]
                end_idx = start_idx + len(table_matrix[r][c])
                if start_idx < end_idx:
                    if is_header:
                        batch3_requests.append(
                            {
                                "updateTextStyle": {
                                    "textStyle": {
                                        "bold": True,
                                        "fontSize": {"magnitude": 8, "unit": "PT"},
                                        "foregroundColor": {
                                            "color": {"rgbColor": palette["white"]}
                                        },
                                    },
                                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                                    "fields": "bold,fontSize,foregroundColor",
                                }
                            }
                        )
                    elif c == 0:
                        batch3_requests.append(
                            {
                                "updateTextStyle": {
                                    "textStyle": {
                                        "bold": True,
                                        "fontSize": {"magnitude": 7.5, "unit": "PT"},
                                        "foregroundColor": {
                                            "color": {"rgbColor": palette["title_green"]}
                                        },
                                    },
                                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                                    "fields": "bold,fontSize,foregroundColor",
                                }
                            }
                        )
                    else:
                        batch3_requests.append(
                            {
                                "updateTextStyle": {
                                    "textStyle": {
                                        "fontSize": {"magnitude": 7.2, "unit": "PT"},
                                        "foregroundColor": {
                                            "color": {"rgbColor": palette["charcoal"]}
                                        },
                                    },
                                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                                    "fields": "fontSize,foregroundColor",
                                }
                            }
                        )

        if batch3_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": batch3_requests}
            ).execute()

        logger.info("Successfully appended 8-column Macro & Portfolio Insights summary table.")

    except HttpError as err:
        logger.error(f"Google Docs API Error in append_macro_insights_table: {err}")
        raise
