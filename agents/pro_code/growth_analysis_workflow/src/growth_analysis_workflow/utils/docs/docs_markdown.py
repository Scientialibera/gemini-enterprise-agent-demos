"""Google Docs markdown parsing and narrative text section renderer."""

import logging
import re
from typing import Any, Dict, List, Tuple

from googleapiclient.errors import HttpError

from growth_analysis_workflow.utils.docs.docs_styles import DEFAULT_PALETTE

logger = logging.getLogger(__name__)


def _parse_markdown_formatting_tokens(text_content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parses markdown syntax (headers, bullets, bolding) into plain text and character range mappings."""
    lines = text_content.strip().split("\n")
    full_buffer = ""
    line_mappings: List[Dict[str, Any]] = []

    for line in lines:
        raw_line = line.strip()
        if not raw_line:
            full_buffer += "\n"
            continue

        # 1. Header lines (###, ####, #####)
        if raw_line.startswith("#"):
            clean_line = re.sub(r"^#+\s*", "", raw_line).strip()
            clean_line = re.sub(r"^\*\*|\*\*$", "", clean_line).strip()
            clean_line = re.sub(
                r"\s*\((Suburban|Urban|Exurban|18 Mo\.|15 Mo\.)\)",
                "",
                clean_line,
                flags=re.IGNORECASE,
            )
            start_rel = len(full_buffer)
            full_buffer += clean_line + "\n"
            end_rel = len(full_buffer) - 1
            line_mappings.append({"type": "h3", "start": start_rel, "end": end_rel})

        # 2. Recommendations or bullets
        elif (
            raw_line.startswith("* ")
            or raw_line.startswith("- ")
            or raw_line.startswith("• ")
            or "Recommendation:" in raw_line
        ):
            is_hyphen = raw_line.startswith("- ") or "Recommendation:" in raw_line
            clean_line = raw_line

            if (
                clean_line.startswith("• ")
                or clean_line.startswith("* ")
                or clean_line.startswith("- ")
            ):
                clean_line = clean_line[2:].strip()

            # Ensure all metrics are bolded mathematically
            clean_line = re.sub(
                r"(?<!\*\*)(\b\d+\.\d+%|\b\d+\.\d+K|\b\d+K|\b\d+\.\d+★?|\b\d+%)(?!\*\*)",
                r"**\1**",
                clean_line,
            )

            parts = clean_line.split("**")
            bullet_prefix = "  - " if is_hyphen else "  • "

            start_rel = len(full_buffer)
            clean_text_buffer = bullet_prefix

            # Strip raw ** markers from the text buffer while saving character offset ranges
            bold_ranges = []
            for i, part in enumerate(parts):
                if not part:
                    continue
                if i % 2 == 1:  # Odd index = bold text inside **...**
                    b_start = start_rel + len(clean_text_buffer)
                    clean_text_buffer += part
                    b_end = start_rel + len(clean_text_buffer)
                    bold_ranges.append({"start": b_start, "end": b_end})
                else:
                    clean_text_buffer += part

            full_buffer += clean_text_buffer + "\n"
            end_rel = len(full_buffer) - 1

            line_mappings.append(
                {
                    "type": "bullet_base",
                    "start": start_rel,
                    "end": end_rel,
                    "bold_ranges": bold_ranges,
                }
            )

        else:
            parts = raw_line.split("**")
            start_rel = len(full_buffer)
            clean_text_buffer = ""
            bold_ranges = []

            for i, part in enumerate(parts):
                if not part:
                    continue
                if i % 2 == 1:
                    b_start = start_rel + len(clean_text_buffer)
                    clean_text_buffer += part
                    b_end = start_rel + len(clean_text_buffer)
                    bold_ranges.append({"start": b_start, "end": b_end})
                else:
                    clean_text_buffer += part

            full_buffer += clean_text_buffer + "\n"
            end_rel = len(full_buffer) - 1

            line_mappings.append(
                {
                    "type": "p",
                    "start": start_rel,
                    "end": end_rel,
                    "bold_ranges": bold_ranges,
                }
            )

    return full_buffer, line_mappings


def append_text_section(
    docs_service,
    doc_id: str,
    section_title: str,
    text_content: str,
    start_on_new_page: bool = False,
    palette: Dict[str, Any] = DEFAULT_PALETTE,
    tight_heading_gap: bool = False,
) -> None:
    """Parses markdown syntax and renders styled text sections in Google Docs, stripping ** markers."""
    if not text_content:
        logger.warning(f"Skipping '{section_title}' because text_content is empty.")
        return

    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc.get("body").get("content")[-1].get("endIndex") - 1
        if end_index < 1:
            end_index = 1

        title_text = f"{section_title}\n" if tight_heading_gap else f"{section_title}\n\n"
        title_len = len(section_title)

        header_requests = []
        current_idx = end_index

        if start_on_new_page:
            header_requests.append({"insertPageBreak": {"location": {"index": current_idx}}})
            current_idx += 1

        header_requests.extend(
            [
                {"insertText": {"location": {"index": current_idx}, "text": title_text}},
                {
                    "updateTextStyle": {
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 15, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": palette["title_green"]}},
                        },
                        "range": {"startIndex": current_idx, "endIndex": current_idx + title_len},
                        "fields": "bold,fontSize,foregroundColor",
                    }
                },
            ]
        )

        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": header_requests}
        ).execute()

        doc = docs_service.documents().get(documentId=doc_id).execute()
        current_idx = doc.get("body").get("content")[-1].get("endIndex") - 1

        full_buffer, line_mappings = _parse_markdown_formatting_tokens(text_content)

        if full_buffer:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {"insertText": {"location": {"index": current_idx}, "text": full_buffer}}
                    ]
                },
            ).execute()

            batch_style_requests = []
            for item in line_mappings:
                abs_start = current_idx + item["start"]
                abs_end = current_idx + item["end"]

                if item["type"] == "h3":
                    batch_style_requests.append(
                        {
                            "updateTextStyle": {
                                "textStyle": {
                                    "bold": True,
                                    "fontSize": {"magnitude": 10.5, "unit": "PT"},
                                    "foregroundColor": {
                                        "color": {"rgbColor": palette["header_green"]}
                                    },
                                },
                                "range": {"startIndex": abs_start, "endIndex": abs_end},
                                "fields": "bold,fontSize,foregroundColor",
                            }
                        }
                    )
                elif item["type"] in ["bullet_base", "p"]:
                    batch_style_requests.append(
                        {
                            "updateTextStyle": {
                                "textStyle": {
                                    "fontSize": {"magnitude": 9.5, "unit": "PT"},
                                    "foregroundColor": {"color": {"rgbColor": palette["charcoal"]}},
                                },
                                "range": {"startIndex": abs_start, "endIndex": abs_end},
                                "fields": "fontSize,foregroundColor",
                            }
                        }
                    )

                # Style calculated bold ranges
                for b_range in item.get("bold_ranges", []):
                    b_abs_start = current_idx + b_range["start"]
                    b_abs_end = current_idx + b_range["end"]
                    batch_style_requests.append(
                        {
                            "updateTextStyle": {
                                "textStyle": {
                                    "bold": True,
                                    "foregroundColor": {
                                        "color": {"rgbColor": palette["title_green"]}
                                    },
                                },
                                "range": {"startIndex": b_abs_start, "endIndex": b_abs_end},
                                "fields": "bold,foregroundColor",
                            }
                        }
                    )

            if batch_style_requests:
                docs_service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": batch_style_requests}
                ).execute()

        logger.info(f"Successfully appended styled text section: '{section_title}'")

    except HttpError as err:
        logger.error(f"Google Docs API Error in append_text_section: {err}")
        raise
