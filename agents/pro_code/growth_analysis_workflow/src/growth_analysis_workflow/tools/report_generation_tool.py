"""Production Report Generation Tool for Executive Google Doc Publishing.

Orchestrates clean landscape pagination:
- Page 1: Title Banner & TL;DR Executive Summary
- Page 2: Appendix Header, Section 1 Table (18mo Bottom 5), Section 2 Table (15mo Bottom 3)
- Page 3: Section 3 Table (18mo Top 5)
- Page 4: Section 4 Macro & Portfolio Summary Table
- Page 5+: Detailed Store-by-Store Diagnostic Breakdown
"""

import json
import logging
import re
from typing import Any

import pandas as pd
from googleapiclient.discovery import build

from growth_analysis_workflow.config_loader import load_agent_config
from growth_analysis_workflow.tools.sheet_reader_tool import fetch_top_and_bottom_performing_stores
from growth_analysis_workflow.utils.google_auth import authenticate_google_oauth
from growth_analysis_workflow.utils.google_docs_builder import (
    append_appendix_header,
    append_macro_insights_table,
    append_styled_section,
    append_text_section,
    append_tldr_section,
    create_landscape_report_doc,
    insert_report_title,
)
from growth_analysis_workflow.utils.report_insights_parser import (
    generate_macro_insights_tabular_summary,
    generate_tldr_executive_bullets,
)

logger = logging.getLogger(__name__)


def generate_sss_performance_report_doc(
    macro_insights_text: str = "",
    tool_context: Any = None,
) -> str:
    """ADK Tool: Generates an executive Google Doc performance report with structured page breaks."""
    try:
        store_data = None

        # 1. Attempt to retrieve pre-cached sheet data from ADK ToolContext
        if tool_context and hasattr(tool_context, "state"):
            store_data = tool_context.state.get("kitchen_sheet_data")
            if store_data:
                logger.info(
                    "[ADK State] Cache HIT: Retrieved sheet metrics directly from tool_context.state['kitchen_sheet_data']"
                )

        # 2. Fallback to network tool fetch if state is empty
        if not store_data:
            logger.info("Cache MISS: Fetching SSS store data via sheet reader tool...")
            store_data_raw = fetch_top_and_bottom_performing_stores(tool_context=tool_context)
            store_data = (
                json.loads(store_data_raw) if isinstance(store_data_raw, str) else store_data_raw
            )

        bottom_5_18mo = pd.DataFrame(
            store_data.get("bottom_5_18mo_stores") or store_data.get("bottom_5_stores", [])
        )
        bottom_3_15mo = pd.DataFrame(store_data.get("bottom_3_15mo_stores", []))
        top_5_18mo = pd.DataFrame(
            store_data.get("top_5_18mo_stores") or store_data.get("top_5_stores", [])
        )
        tldr_evaluations = store_data.get("tldr_store_evaluations", [])

        creds = authenticate_google_oauth()
        docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
        drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)

        config = load_agent_config("report_generation_agent")
        palette = config.get("brand_palette", {})
        sec_titles = config.get("section_titles", {})
        target_folder_id = config.get("storage", {}).get("target_folder_id", "")

        tabular_summary = []
        if macro_insights_text:
            tabular_summary = generate_macro_insights_tabular_summary(
                macro_insights_text, max_retries=3
            )

        # 1. Initialize Landscape Google Doc
        doc_id = create_landscape_report_doc(docs_service, drive_service, config)

        # 2. Page 1: Title Banner
        insert_report_title(docs_service, doc_id)

        # 3. Page 1: TL;DR Executive Summary
        tldr_title = sec_titles.get("tldr_title", "Executive Summary & TL;DR Insights")
        if tldr_evaluations:
            logger.info(
                f"Synthesizing TL;DR executive bullets for {len(tldr_evaluations)} stores..."
            )
            tldr_bullets_text = generate_tldr_executive_bullets(
                tldr_evaluations, macro_summary_data=tabular_summary
            )
            append_tldr_section(
                docs_service,
                doc_id,
                tldr_bullets_text,
                palette=palette,
                section_title=f"{tldr_title}\n",
            )

        # 4. Page 2: Appendix Header + Section 1 & 2 Tables
        app_header = sec_titles.get(
            "appendix_header", "Appendix: Deep-Dive Diagnostics & Performance Tables"
        )
        append_appendix_header(
            docs_service, doc_id, palette=palette, header_title=f"{app_header}\n\n"
        )

        sec1_title = sec_titles.get(
            "section_1", "Section 1: L6W SSS Negative Kitchens - 18 Mo. Cohort (Bottom 5)"
        )
        sec2_title = sec_titles.get(
            "section_2", "Section 2: L6W SSS Negative Kitchens - 15 Mo. Cohort (Bottom 3)"
        )
        sec3_title = sec_titles.get(
            "section_3", "Section 3: L6W SSS Positive Kitchens - 18 Mo. Cohort (Top 5)"
        )

        append_styled_section(
            docs_service,
            doc_id,
            sec1_title,
            bottom_5_18mo,
            palette=palette,
            start_on_new_page=False,
        )
        if not bottom_3_15mo.empty:
            append_styled_section(
                docs_service,
                doc_id,
                sec2_title,
                bottom_3_15mo,
                palette=palette,
                start_on_new_page=False,
            )

        # 5. Page 3: Section 3 Table ONLY
        append_styled_section(
            docs_service, doc_id, sec3_title, top_5_18mo, palette=palette, start_on_new_page=True
        )

        # 6. Page 4: Section 4 Macro Table ONLY
        if macro_insights_text:
            sec4_heading = sec_titles.get(
                "section_4_heading", "Section 4: Macro & Portfolio Insights"
            )
            sec4_table_subtitle = sec_titles.get(
                "section_4_table_subtitle", "Executive Macro & Portfolio Summary Table"
            )
            append_macro_insights_table(
                docs_service,
                doc_id,
                tabular_summary,
                palette=palette,
                start_on_new_page=True,
                section_heading=f"{sec4_heading}\n\n",
                table_subtitle=f"{sec4_table_subtitle}\n\n",
            )

            detailed_text = macro_insights_text
            match = re.search(
                r"(Detailed Store Diagnostics|Detailed Store-by-Store)",
                detailed_text,
                re.IGNORECASE,
            )
            if match:
                detailed_text = detailed_text[match.start() :].strip()
            else:
                match = re.search(r"##\s", detailed_text)
                if match:
                    detailed_text = detailed_text[match.start() :].strip()

            detailed_text = re.sub(
                r"(?i)^#*\s*Section [34]: Macro & Portfolio Insights\s*", "", detailed_text
            ).strip()
            detailed_text = re.sub(
                r"(?i)^#*\s*Detailed Store Diagnostics\s*", "", detailed_text
            ).strip()
            detailed_text = re.sub(
                r"(?i)^#*\s*Detailed Store-by-Store Diagnostic Breakdown\s*", "", detailed_text
            ).strip()

            sec4_detailed_title = sec_titles.get(
                "section_4_detailed", "Detailed Store-by-Store Diagnostic Breakdown"
            )
            append_text_section(
                docs_service,
                doc_id,
                sec4_detailed_title,
                detailed_text,
                start_on_new_page=True,
                palette=palette,
            )

        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        result_message = (
            f"Google Doc Generated Successfully.\n"
            f"Document URL: {doc_url}\n"
            f"Saved in Shared Folder ID: {target_folder_id}"
        )
        logger.info(result_message)
        return result_message

    except Exception as e:
        logger.error(f"Error generating performance report Google Doc: {e}", exc_info=True)
        return f"Report generation failed with error: {str(e)}"
