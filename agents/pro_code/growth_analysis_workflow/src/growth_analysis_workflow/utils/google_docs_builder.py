"""Google Docs layout, styling, and table building utilities.

Provides backward-compatible facade re-exporting modular components from utils.docs:
- docs_styles: DEFAULT_PALETTE
- docs_core: create_landscape_report_doc, insert_report_title, append_tldr_section, append_appendix_header
- docs_tables: append_styled_section, append_macro_insights_table
- docs_markdown: append_text_section, _parse_markdown_formatting_tokens
"""

from growth_analysis_workflow.utils.docs import (
    DEFAULT_PALETTE,
    _parse_markdown_formatting_tokens,
    append_appendix_header,
    append_macro_insights_table,
    append_styled_section,
    append_text_section,
    append_tldr_section,
    create_landscape_report_doc,
    insert_report_title,
)

__all__ = [
    "DEFAULT_PALETTE",
    "create_landscape_report_doc",
    "insert_report_title",
    "append_tldr_section",
    "append_appendix_header",
    "append_styled_section",
    "append_macro_insights_table",
    "append_text_section",
    "_parse_markdown_formatting_tokens",
]
