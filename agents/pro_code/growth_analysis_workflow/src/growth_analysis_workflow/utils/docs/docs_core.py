"""Google Docs report creation, landscape setup, and document structure headers."""

import datetime
import logging
from typing import Any, Dict

from googleapiclient.errors import HttpError

from growth_analysis_workflow.utils.docs.docs_markdown import append_text_section
from growth_analysis_workflow.utils.docs.docs_styles import DEFAULT_PALETTE
from growth_analysis_workflow.utils.google_auth import move_file_to_folder

logger = logging.getLogger(__name__)


def create_landscape_report_doc(
    docs_service,
    drive_service,
    config: Dict[str, Any],
) -> str:
    """Creates a new Google Doc formatted in landscape with brand background color."""
    storage_cfg = config.get("storage", {})
    page_cfg = config.get("page_style", {})
    palette = config.get("brand_palette", DEFAULT_PALETTE)
    target_folder_id = storage_cfg.get("target_folder_id", "")

    title_prefix = storage_cfg.get("doc_title_prefix", "L6W SSS Performance Report")
    doc_title = f"{title_prefix} - {datetime.datetime.now().strftime('%Y-%m-%d')}"

    try:
        doc = docs_service.documents().create(body={"title": doc_title}).execute()
        doc_id = doc.get("documentId")
        logger.info(f"Created Google Doc ID: {doc_id}")

        if target_folder_id:
            move_file_to_folder(drive_service, doc_id, target_folder_id)

        orientation = page_cfg.get("orientation", "landscape")
        default_width = 792 if orientation == "landscape" else 612
        default_height = 612 if orientation == "landscape" else 792
        width_pt = page_cfg.get("width_pt", default_width)
        height_pt = page_cfg.get("height_pt", default_height)
        margins = page_cfg.get("margins_pt", {"top": 36, "bottom": 36, "left": 36, "right": 36})
        cream_color = palette.get("cream_bg", DEFAULT_PALETTE["cream_bg"])
        logger.info(f"Configuring document layout: {orientation} ({width_pt}pt x {height_pt}pt)")

        style_requests = [
            {
                "updateDocumentStyle": {
                    "documentStyle": {
                        "pageSize": {
                            "width": {"magnitude": width_pt, "unit": "PT"},
                            "height": {"magnitude": height_pt, "unit": "PT"},
                        },
                        "marginTop": {"magnitude": margins.get("top", 36), "unit": "PT"},
                        "marginBottom": {"magnitude": margins.get("bottom", 36), "unit": "PT"},
                        "marginLeft": {"magnitude": margins.get("left", 36), "unit": "PT"},
                        "marginRight": {"magnitude": margins.get("right", 36), "unit": "PT"},
                        "background": {"color": {"color": {"rgbColor": cream_color}}},
                    },
                    "fields": "pageSize,marginTop,marginBottom,marginLeft,marginRight,background",
                }
            }
        ]

        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": style_requests}
        ).execute()

        return doc_id

    except HttpError as err:
        logger.error(f"Failed to initialize landscape Google Doc: {err}")
        raise


def insert_report_title(docs_service, doc_id: str, title_text: str = "") -> None:
    """Inserts the main title banner at the top of the Google Document."""
    date_str = datetime.datetime.now().strftime("%b %-d, %Y")
    full_title = title_text or f"Kitchen Portfolio SSS Diagnostic Report | Generated: {date_str}\n"

    idx_start = 1
    idx_after_title = idx_start + len(full_title)

    requests = [
        {"insertText": {"location": {"index": idx_start}, "text": full_title}},
        {
            "updateTextStyle": {
                "textStyle": {
                    "bold": True,
                    "fontSize": {"magnitude": 18, "unit": "PT"},
                    "foregroundColor": {"color": {"rgbColor": DEFAULT_PALETTE["title_green"]}},
                },
                "range": {"startIndex": idx_start, "endIndex": idx_after_title},
                "fields": "bold,fontSize,foregroundColor",
            }
        },
    ]

    try:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()
        logger.info(f"Inserted report title in doc {doc_id}")
    except HttpError as err:
        logger.error(f"Error inserting title in doc {doc_id}: {err}")
        raise


def append_tldr_section(
    docs_service,
    doc_id: str,
    tldr_text: str,
    palette: Dict[str, Any] = DEFAULT_PALETTE,
    section_title: str = "Executive Summary & TL;DR Insights\n",
) -> None:
    """Appends the TL;DR Executive Summary block directly below the title banner with proper spacing."""
    if not tldr_text:
        logger.warning("Skipping append_tldr_section because tldr_text is empty.")
        return

    try:
        append_text_section(
            docs_service,
            doc_id,
            section_title,
            tldr_text,
            start_on_new_page=False,
            palette=palette,
            tight_heading_gap=False,  # Provides vertical breathing room below title
        )
        logger.info("Successfully appended TL;DR Executive Summary section.")

    except Exception as err:
        logger.error(f"Error appending TL;DR section in doc {doc_id}: {err}")
        raise


def append_appendix_header(
    docs_service,
    doc_id: str,
    palette: Dict[str, Any] = DEFAULT_PALETTE,
    header_title: str = "Appendix: Deep-Dive Diagnostics & Performance Tables\n\n",
) -> None:
    """Inserts a visual section break starting Page 2 for the deep-dive appendix tables."""
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc.get("body").get("content")[-1].get("endIndex") - 1
        if end_index < 1:
            end_index = 1

        appendix_title = (
            header_title if header_title.endswith("\n\n") else f"{header_title.rstrip()}\n\n"
        )
        title_len = len(appendix_title.strip())

        requests = [
            {"insertPageBreak": {"location": {"index": end_index}}},
            {"insertText": {"location": {"index": end_index + 1}, "text": appendix_title}},
            {
                "updateTextStyle": {
                    "textStyle": {
                        "bold": True,
                        "fontSize": {"magnitude": 16, "unit": "PT"},
                        "foregroundColor": {"color": {"rgbColor": palette["header_green"]}},
                    },
                    "range": {"startIndex": end_index + 1, "endIndex": end_index + 1 + title_len},
                    "fields": "bold,fontSize,foregroundColor",
                }
            },
        ]

        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()
        logger.info("Successfully appended Appendix Header divider on Page 2.")

    except Exception as err:
        logger.error(f"Error appending Appendix Header in doc {doc_id}: {err}")
        raise
