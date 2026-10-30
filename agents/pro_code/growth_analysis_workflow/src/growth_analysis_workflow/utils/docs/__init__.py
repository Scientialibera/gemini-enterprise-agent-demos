"""Google Docs building and formatting subpackage."""

from growth_analysis_workflow.utils.docs.docs_core import (
    append_appendix_header,
    append_tldr_section,
    create_landscape_report_doc,
    insert_report_title,
)
from growth_analysis_workflow.utils.docs.docs_markdown import (
    _parse_markdown_formatting_tokens,
    append_text_section,
)
from growth_analysis_workflow.utils.docs.docs_styles import DEFAULT_PALETTE
from growth_analysis_workflow.utils.docs.docs_tables import (
    append_macro_insights_table,
    append_styled_section,
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
