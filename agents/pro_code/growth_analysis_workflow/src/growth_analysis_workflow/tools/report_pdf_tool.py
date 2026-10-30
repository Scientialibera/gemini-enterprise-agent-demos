"""Executive PDF report, emailed to the growth team.

The same content as the Google Doc report, laid out as a designed landscape PDF:

    Page 1   title band, headline tiles, executive summary per store
    Page 2   cohort tables: bottom performers (18 and 15 months), top performers
    Page 3   outside factors by store: industry, weather, labor, reviews, actions
    Page 4+  the full store-by-store diagnosis

It runs as the workflow's own identity: the PDF is emailed through the Gmail app
password in Secret Manager to GROWTH_REPORT_RECIPIENTS, and saved to the session
as an artifact.
"""

import datetime as dt
import html
import json
import logging
import os
import re
from typing import Any, Dict, List

import pandas as pd
from demo_tools.mailer import Attachment, send_email
from demo_tools.pdf import (
    CORAL,
    GREEN,
    PageBreak,
    Report,
    ReportFrame,
    Spacer,
    callout,
    colored,
    data_table,
    inline_markup,
    kpi_row,
    markdown_flowables,
    para,
)
from google.genai import types
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from growth_analysis_workflow.tools.sheet_reader_tool import fetch_top_and_bottom_performing_stores
from growth_analysis_workflow.utils.report_insights_parser import (
    generate_macro_insights_tabular_summary,
    generate_tldr_executive_bullets,
)

logger = logging.getLogger(__name__)

RECIPIENTS_ENV = "GROWTH_REPORT_RECIPIENTS"
PDF_MIME = "application/pdf"

# Sheet column -> (table heading, width in points)
COHORT_COLUMNS = (
    ("Kitchen Name", "Store", 120),
    ("Population Type", "Market", 52),
    ("L6W SSS or YoY (Kitchen + MP)", "L6W SSS", 46),
    ("GOV (Kitchen + MP)", "Sales", 50),
    ("GOV (Kitchen Only)", "Direct", 48),
    ("GOV (MP Only)", "Partner", 48),
    ("App / Web Traffic (1P) - Overall", "Traffic", 44),
    ("Conversion (1P)", "Conv.", 42),
    ("Taste Rating (Kitchen)", "Taste", 38),
    ("IOR % (Kitchen) Target = < 10%", "Issue rate", 46),
    ("In-Stock Rate %", "In-stock", 44),
    ("Dinner Mix % Total GOV", "Dinner mix", 46),
    ("Promo GOV % 1P GOV", "Promo mix", 46),
)


def _sss(value: Any) -> float:
    try:
        return float(str(value).replace("%", "").strip())
    except ValueError:
        return 0.0


def _cohort_table(df: pd.DataFrame, width: float):
    rows = []
    for _, row in df.iterrows():
        cells = []
        for column, _, _ in COHORT_COLUMNS:
            value = row.get(column, "")
            value = "" if value is None or (isinstance(value, float) and pd.isna(value)) else value
            if column.startswith("L6W SSS"):
                cells.append(colored(value, CORAL if _sss(value) < 0 else GREEN))
            else:
                cells.append(str(value))
        rows.append(cells)
    widths = [w for _, _, w in COHORT_COLUMNS]
    scale = width / sum(widths)
    return data_table(
        [heading for _, heading, _ in COHORT_COLUMNS],
        rows,
        [w * scale for w in widths],
        bold_first_column=True,
        font_size=7.4,
        header_color=HEADER_GREEN,
    )


def _tldr_sections(tldr_text: str) -> List[Any]:
    """One tinted block per store from the TL;DR markdown."""
    flowables: List[Any] = []
    for chunk in re.split(r"(?m)^###\s+", tldr_text or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        heading, _, body = chunk.partition("\n")
        flowables.append(_store_heading(heading.strip()))
        flowables.extend(markdown_flowables(body))
        flowables.append(Spacer(1, 6))
    return flowables


def _detailed_text(macro_insights_text: str) -> str:
    text = macro_insights_text or ""
    match = re.search(r"(Detailed Store Diagnostics|Detailed Store-by-Store)", text, re.IGNORECASE)
    if match:
        text = text[match.start() :]
    text = re.sub(r"(?im)^#*\s*Detailed Store(-by-Store)? Diagnostic(s| Breakdown)\s*$", "", text)
    return text.strip()


# The report palette: cream pages, green headers and titles.
CREAM_BG = colors.HexColor("#F5F3E9")
HEADER_GREEN = colors.HexColor("#3E9E62")
TITLE_GREEN = colors.HexColor("#215235")
CELL_BG = colors.HexColor("#FAF9F5")


def _section_title(text: str):
    style = ParagraphStyle(
        "section_title",
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=TITLE_GREEN,
        spaceAfter=2,
    )
    return Paragraph(inline_markup(text), style)


def _store_heading(text: str):
    style = ParagraphStyle(
        "store_heading",
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=HEADER_GREEN,
        spaceBefore=7,
        spaceAfter=1,
    )
    return Paragraph(inline_markup(text), style)


def build_report_pdf(
    store_data: Dict[str, Any],
    tldr_text: str,
    macro_rows: List[Dict[str, Any]],
    macro_insights_text: str,
    as_of: str,
) -> bytes:
    bottom_18 = pd.DataFrame(store_data.get("bottom_5_18mo_stores") or [])
    bottom_15 = pd.DataFrame(store_data.get("bottom_3_15mo_stores") or [])
    top_18 = pd.DataFrame(store_data.get("top_5_18mo_stores") or [])
    bottom_all = pd.concat([bottom_18, bottom_15], ignore_index=True)

    report = Report(
        ReportFrame(
            title=f"Store Portfolio SSS Diagnostic Report  |  Generated: {dt.date.today():%b %d, %Y}",
            subtitle=f"Last 6 weeks (L6W) ending {as_of}  ·  Same-store sales, funnel, "
            "operations and outside factors",
            eyebrow="Growth analytics  ·  Gemini Enterprise agent",
            footer_note="Internal metrics from the performance workbook; outside factors from "
            "weather, reviews, labor and news sources.",
            landscape_pages=True,
            band_color=TITLE_GREEN,
            accent_color=HEADER_GREEN,
            eyebrow_color=colors.HexColor("#A8D5B5"),
            subtitle_color=colors.HexColor("#DCEBDF"),
            page_color=CREAM_BG,
        )
    )
    width = report.width
    sss_column = "L6W SSS or YoY (Kitchen + MP)"
    worst = min((_sss(v) for v in bottom_all.get(sss_column, [])), default=0.0)
    best = max((_sss(v) for v in top_18.get(sss_column, [])), default=0.0)
    story: List[Any] = [
        kpi_row(
            [
                (str(len(bottom_all)), "Stores with negative L6W SSS, diagnosed"),
                (f"{worst:+.1f}%", "Steepest same-store sales decline"),
                (f"{best:+.1f}%", "Strongest same-store sales growth"),
                ("5", "Outside data sources researched per store"),
            ],
            width,
            accent=HEADER_GREEN,
        ),
        Spacer(1, 12),
        _section_title("Executive Summary & TL;DR Insights"),
        para(
            "One diagnosis per underperforming store: its funnel against benchmark, the outside "
            "factors at play, and the recommended next move. Owner tags name who acts.",
            "muted",
        ),
        Spacer(1, 4),
    ]
    story.extend(_tldr_sections(tldr_text))

    story += [
        PageBreak(),
        _section_title("Appendix: Deep-Dive Diagnostics & Performance Tables"),
        Spacer(1, 6),
    ]
    if not bottom_18.empty:
        story += [
            _store_heading("Section 1: L6W SSS Negative Stores - 18 Mo. Cohort (Bottom 5)"),
            _cohort_table(bottom_18, width),
            Spacer(1, 10),
        ]
    if not bottom_15.empty:
        story += [
            _store_heading("Section 2: L6W SSS Negative Stores - 15 Mo. Cohort (Bottom 3)"),
            _cohort_table(bottom_15, width),
            Spacer(1, 10),
        ]
    if not top_18.empty:
        story += [
            _store_heading("Section 3: L6W SSS Positive Stores - 18 Mo. Cohort (Top 5)"),
            _cohort_table(top_18, width),
        ]

    if macro_rows:
        story += [
            PageBreak(),
            _section_title("Section 4: Macro & Portfolio Insights"),
            para(
                "Executive Macro & Portfolio Summary Table: what the research agents found "
                "around each underperforming store.",
                "muted",
            ),
            Spacer(1, 6),
        ]
        rows = [
            [
                f"**{row.get('store_name', '')}**",
                row.get("qsr_trends", ""),
                row.get("weather_trends", ""),
                row.get("unemployment", ""),
                row.get("customer_sentiment", ""),
                row.get("recommendations", ""),
            ]
            for row in macro_rows
        ]
        story.append(
            data_table(
                [
                    "Store",
                    "QSR Trends",
                    "Weather Trends",
                    "Unemployment & Labor",
                    "Customer Reviews",
                    "Recommendations",
                ],
                rows,
                [width * f for f in (0.13, 0.18, 0.17, 0.16, 0.18, 0.18)],
                header_color=HEADER_GREEN,
                font_size=7.4,
            )
        )

    detailed = _detailed_text(macro_insights_text)
    if detailed:
        story += [
            PageBreak(),
            _section_title("Detailed Store-by-Store Diagnostic Breakdown"),
            Spacer(1, 2),
        ]
        story.extend(markdown_flowables(detailed))

    story += [
        Spacer(1, 12),
        callout(
            "Every number in the tables is computed in code from the performance workbook; the "
            "model writes only the diagnosis and recommendations. Review before the weekly "
            "business review.",
            width,
            color=TITLE_GREEN,
            tint=CELL_BG,
            label="How this was built:",
        ),
    ]
    return report.build(story)


def _email_bodies(
    bottom: pd.DataFrame, macro_rows: List[Dict[str, Any]], as_of: str, pdf_name: str
) -> tuple[str, str]:
    actions = {str(r.get("store_name", "")).split(" (")[0].lower(): r for r in macro_rows}
    rows_html, lines = [], []
    for _, row in bottom.iterrows():
        name = str(row.get("Kitchen Name", ""))
        sss = str(row.get("L6W SSS or YoY (Kitchen + MP)", ""))
        action = str(actions.get(name.lower(), {}).get("recommendations", "")).lstrip("• ")
        rows_html.append(
            f"<tr><td style='padding:8px;border-bottom:1px solid #D9DEE3'><strong>"
            f"{html.escape(name)}</strong></td><td style='padding:8px;border-bottom:1px solid "
            f"#D9DEE3;color:#D9483B'><strong>{html.escape(sss)}</strong></td><td style='padding:8px;"
            f"border-bottom:1px solid #D9DEE3'>{html.escape(action)}</td></tr>"
        )
        lines.append(f"- {name} ({sss}): {action}")
    navy, teal = TITLE_GREEN.hexval()[2:], HEADER_GREEN.hexval()[2:]
    html_body = (
        "<div style=\"font-family:'Helvetica Neue',Arial,sans-serif;color:#1D2730;max-width:760px\">"
        f"<div style='background:#{navy};color:#fff;padding:16px 20px'>"
        "<div style='font-size:20px;font-weight:bold'>Store Performance Diagnostic</div>"
        f"<div style='font-size:13px;color:#C9D6DF'>Last 6 weeks ending {html.escape(as_of)}</div>"
        f"</div><div style='height:4px;background:#{teal}'></div>"
        f"<p style='font-size:14px;margin:18px 0'>{len(bottom)} stores are behind last year. "
        "The attached report diagnoses each one with internal metrics and outside factors.</p>"
        "<table style='border-collapse:collapse;width:100%;font-size:13px'>"
        f"<tr style='background:#{navy};color:#fff;text-align:left'><th style='padding:8px'>Store"
        "</th><th style='padding:8px'>L6W SSS</th><th style='padding:8px'>Recommended move</th></tr>"
        + "".join(rows_html)
        + f"</table><p style='font-size:13px;color:#5B6770;margin:18px 0 0'>Attached: "
        f"{html.escape(pdf_name)}</p></div>"
    )
    text_body = "\n".join(
        [
            f"Store Performance Diagnostic - last 6 weeks ending {as_of}",
            "",
            *lines,
            "",
            f"Attached: {pdf_name}",
        ]
    )
    return html_body, text_body


async def generate_sss_performance_report_pdf(
    macro_insights_text: str = "",
    tool_context: Any = None,
    tldr_text: str = "",
    macro_rows: List[Dict[str, Any]] | None = None,
) -> str:
    """ADK Tool: builds the executive PDF report and emails it to the growth team.

    When the diagnosis already supplies the TL;DR bullets and the outside-factors
    table, they are used as given and no further model call is made.
    """
    try:
        store_data = None
        if tool_context is not None and hasattr(tool_context, "state"):
            store_data = tool_context.state.get("kitchen_sheet_data")
        if not store_data:
            raw = fetch_top_and_bottom_performing_stores(tool_context=tool_context)
            store_data = json.loads(raw) if isinstance(raw, str) else raw

        inputs = store_data.get("bottom_5_weather_agent_input") or [{}]
        as_of = str(inputs[0].get("target_date") or dt.date.today().isoformat())

        if macro_rows is None:
            macro_rows = (
                generate_macro_insights_tabular_summary(macro_insights_text, max_retries=3)
                if macro_insights_text
                else []
            )
        if not tldr_text:
            tldr_text = generate_tldr_executive_bullets(
                store_data.get("tldr_store_evaluations", []), macro_summary_data=macro_rows
            )
        pdf = build_report_pdf(store_data, tldr_text, macro_rows, macro_insights_text, as_of)
        pdf_name = f"Store_Performance_Diagnostic_{dt.date.today():%Y-%m-%d}.pdf"

        # Local runs can keep a copy on disk to review the layout.
        save_dir = os.getenv("GROWTH_REPORT_SAVE_DIR", "").strip()
        if save_dir:
            with open(os.path.join(save_dir, pdf_name), "wb") as handle:
                handle.write(pdf)

        if tool_context is not None:
            try:
                await tool_context.save_artifact(
                    pdf_name, types.Part.from_bytes(data=pdf, mime_type=PDF_MIME)
                )
            except Exception as exc:
                logger.info(f"Report artifact not saved: {type(exc).__name__}")

        recipients = os.getenv(RECIPIENTS_ENV, "").strip()
        if not recipients:
            return (
                f"Report built ({pdf_name}) but {RECIPIENTS_ENV} is not set, so it was not emailed."
            )

        bottom = pd.concat(
            [
                pd.DataFrame(store_data.get("bottom_5_18mo_stores") or []),
                pd.DataFrame(store_data.get("bottom_3_15mo_stores") or []),
            ],
            ignore_index=True,
        )
        html_body, text_body = _email_bodies(bottom, macro_rows, as_of, pdf_name)
        sent = send_email(
            recipients,
            f"Store Performance Diagnostic | L6W ending {as_of} | {len(bottom)} stores behind",
            html_body,
            text_body,
            (Attachment(pdf_name, pdf, PDF_MIME),),
        )
        message = (
            f"Report emailed to {', '.join(sent['recipients'])}.\n"
            f"Attachment: {pdf_name} ({len(bottom)} stores diagnosed)."
        )
        logger.info(message)
        return message
    except Exception as e:
        logger.error(f"Error generating the performance report PDF: {e}", exc_info=True)
        return f"Report generation failed with error: {e}"
