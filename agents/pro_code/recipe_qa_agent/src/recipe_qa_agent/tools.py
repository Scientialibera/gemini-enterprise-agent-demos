"""The agent's tools: read the recipe tables, prepare the report, and email it.

Delivery is two steps so the confirmation card reads like an email: preparing the
report builds the PDF and Excel extract and returns the subject and attachment
names; sending takes those as plain fields (To, Subject, Attachments, Content), so
the card shows exactly what goes out. The send rebuilds both files from the
prepared results kept in session state, so the attachments match the preview.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from demo_tools.bigquery import run_readonly_query
from demo_tools.mailer import Attachment, clean_recipients, send_email
from google.adk.tools import ToolContext
from google.genai import types

from .config import ALLOWED_DATASETS
from .report import (
    RecipeResult,
    build_excel,
    build_pdf,
    counts,
    email_bodies,
    run_stamp,
    subject,
)

LOGGER = logging.getLogger(__name__)
PDF_MIME = "application/pdf"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STATE_KEY = "recipe_qa_reports"


def query_recipe_data(sql: str) -> dict[str, Any]:
    """Run one read-only BigQuery SELECT against the recipe tables.

    Args:
        sql: A single SELECT statement. Wrap every table path in backticks.

    Returns:
        status, row_count, truncated and rows, or status "error" with a message to
        read and fix before retrying once.
    """
    return run_readonly_query(sql, ALLOWED_DATASETS)


def _files(report: dict[str, Any]) -> tuple[list[RecipeResult], bytes, bytes, str, str]:
    recipes = [RecipeResult.model_validate(r) for r in report["recipes"]]
    pdf = build_pdf(recipes, report["cycle_scope"], report["run_at"], report["xlsx_name"])
    xlsx = build_excel(recipes)
    html_body, text_body = email_bodies(
        recipes, report["cycle_scope"], report["run_at"], report["pdf_name"], report["xlsx_name"]
    )
    return recipes, pdf, xlsx, html_body, text_body


async def prepare_recipe_qa_report(
    cycle_scope: str,
    recipes: list[RecipeResult],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Build the QA report (PDF + Excel extract + HTML email body) from finalized results.

    Call when QA is finished for every recipe in the run and the user wants it sent.

    Args:
        cycle_scope: The cycle or cycles the run covers, e.g. "2026-10-26".
        recipes: Every recipe in the run with its finalized result and findings,
            clean recipes included.

    Returns:
        report_id, the email subject, the attachment file names and a one-line
        content summary, to pass to send_recipe_qa_email.
    """
    try:
        results = [
            r if isinstance(r, RecipeResult) else RecipeResult.model_validate(r) for r in recipes
        ]
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    if not results:
        return {"status": "error", "message": "The report has no recipes."}

    now = dt.datetime.now(dt.UTC)
    stamp = now.strftime("%Y-%m-%d_%H%M")
    report = {
        "report_id": uuid.uuid4().hex[:8],
        "cycle_scope": cycle_scope,
        "run_at": run_stamp(now),
        "pdf_name": f"Recipe_QA_Report_{stamp}.pdf",
        "xlsx_name": f"Recipe_QA_Extract_{stamp}_r1.xlsx",
        "recipes": [r.model_dump() for r in results],
    }
    try:
        _, pdf, xlsx, _, _ = _files(report)
    except Exception as exc:
        LOGGER.exception("Recipe QA report build failed")
        return {"status": "error", "message": f"Report build failed: {type(exc).__name__}: {exc}"}

    reports = dict(tool_context.state.get(STATE_KEY) or {})
    reports[report["report_id"]] = report
    tool_context.state[STATE_KEY] = reports

    for name, content, mime in (
        (report["pdf_name"], pdf, PDF_MIME),
        (report["xlsx_name"], xlsx, XLSX_MIME),
    ):
        try:
            await tool_context.save_artifact(
                name, types.Part.from_bytes(data=content, mime_type=mime)
            )
        except Exception as exc:
            LOGGER.info("Artifact %s not saved: %s", name, type(exc).__name__)

    tally = counts(results)
    return {
        "status": "ready",
        "report_id": report["report_id"],
        "subject": subject(results, cycle_scope),
        "attachments": f"{report['pdf_name']}, {report['xlsx_name']}",
        "content": (
            f"Full HTML QA report: {tally['recipes']} recipes reviewed, {tally['issues']} with "
            f"issues, {tally['review']} review required, {tally['clean']} with no issues."
        ),
    }


async def send_recipe_qa_email(
    to: str,
    subject: str,
    attachments: str,
    content: str,
    report_id: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Email a prepared QA report. The user approves the send in the confirmation card.

    Args:
        to: Recipient email addresses, comma-separated.
        subject: The subject returned by prepare_recipe_qa_report.
        attachments: The attachment file names returned by prepare_recipe_qa_report.
        content: The content summary returned by prepare_recipe_qa_report.
        report_id: The report_id returned by prepare_recipe_qa_report.

    Returns:
        The recipients, message ID and attachment names, or an error to report.
    """
    del attachments, content
    report = (tool_context.state.get(STATE_KEY) or {}).get(report_id)
    if not report:
        return {
            "status": "error",
            "message": f"No prepared report {report_id}; call prepare_recipe_qa_report first.",
        }
    try:
        recipients = clean_recipients(to)
        _, pdf, xlsx, html_body, text_body = _files(report)
        sent = send_email(
            recipients,
            subject,
            html_body,
            text_body,
            (
                Attachment(report["pdf_name"], pdf, PDF_MIME),
                Attachment(report["xlsx_name"], xlsx, XLSX_MIME),
            ),
        )
    except Exception as exc:
        LOGGER.exception("Recipe QA report delivery failed")
        return {"status": "error", "message": f"Delivery failed: {type(exc).__name__}: {exc}"}
    return {
        "status": "sent",
        "recipients": sent["recipients"],
        "message_id": sent["message_id"],
        "attachments": [report["pdf_name"], report["xlsx_name"]],
        "reply_to_user": (
            f"Sent to {', '.join(sent['recipients'])} with {report['pdf_name']} and "
            f"{report['xlsx_name']} attached."
        ),
    }
