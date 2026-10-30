"""The QA report in three forms built from the same finalized findings.

    HTML email  the complete readable report in the message body: title band, then
                every recipe in cycle and slot order; flagged recipes carry a key
                takeaway and their findings table
    PDF         the same report, designed for print, with summary tiles on top
    Excel       a flat findings extract, one sheet per flagged recipe and cycle

All three use the editorial palette: dark green, pastel green and cream.
"""

from __future__ import annotations

import datetime as dt
import html
import io
from typing import Literal

from demo_tools.pdf import (
    KeepTogether,
    Report,
    ReportFrame,
    Spacer,
    callout,
    data_table,
    kpi_row,
    para,
    pill,
    section_rule,
)
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ISSUE = "ISSUE"
NEEDS_REVIEW = "NEEDS REVIEW"
EXCEL_HEADERS = (
    "Finding ID",
    "Result",
    "Issue type",
    "Item",
    "Finding",
    "Step / evidence",
    "Reasoning",
)

# Editorial palette.
DARK_GREEN = "#094125"
PASTEL_GREEN = "#E6F1DE"
CREAM = "#FCF7EE"
BORDER = "#CAD8C7"
BODY = "#20231F"
MUTED = "#5C665F"
RED = "#B3261E"
RED_TINT = "#F9E1DE"
AMBER = "#9A6A00"
AMBER_TINT = "#FBEFCF"
FONT_STACK = "'Avenir Next','Trebuchet MS',Arial,sans-serif"


class Finding(BaseModel):
    """One discrepancy: an ISSUE, or a NEEDS REVIEW the editor should look at."""

    finding_id: str = Field(description="[SKU]-F01, [SKU]-F02, ...")
    result: Literal["ISSUE", "NEEDS REVIEW"]
    issue_type: str = Field(
        description="Ingredient listed but not used | Ingredient used but not listed | "
        "Equipment / cooking logic | Timing inconsistency | Source-data conflict"
    )
    item: str = Field(description="The ingredient, equipment or field concerned.")
    finding: str = Field(description="One sentence stating the discrepancy.")
    evidence: str = Field(description="Short quotation or value plus its location.")
    reasoning: str = Field(description="One or two sentences on why it is a finding.")


class RecipeResult(BaseModel):
    """The finalized QA outcome for one recipe in one cycle."""

    sku: str
    title: str
    subtitle: str = ""
    cycle: str = Field(default="", description="YYYY-MM-DD, or empty when not assigned.")
    slot: str = ""
    customization: str = Field(default="", description="Protein or variant, e.g. 'with Salmon'.")
    recipe_url: str = ""
    issues_found: Literal["Yes", "Review required", "No", "Not evaluated"]
    takeaway: str = Field(default="", description="One short line; empty when clean.")
    findings: list[Finding] = Field(default_factory=list)


def _slot_key(recipe: RecipeResult) -> tuple:
    slot = int(recipe.slot) if recipe.slot.isdigit() else 999
    return (recipe.cycle or "9999", slot, recipe.sku)


def ordered(recipes: list[RecipeResult]) -> list[RecipeResult]:
    return sorted(recipes, key=_slot_key)


def counts(recipes: list[RecipeResult]) -> dict[str, int]:
    return {
        "recipes": len(recipes),
        "issues": sum(r.issues_found == "Yes" for r in recipes),
        "review": sum(r.issues_found == "Review required" for r in recipes),
        "clean": sum(r.issues_found == "No" for r in recipes),
        "findings": sum(len(r.findings) for r in recipes),
    }


def run_stamp(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return now.strftime("%Y-%m-%d %H:%M UTC")


def _heading(recipe: RecipeResult) -> str:
    parts = [f"Slot {recipe.slot or '—'}", recipe.title]
    if recipe.subtitle:
        parts.append(recipe.subtitle)
    parts.append(f"Cycle: {recipe.cycle or 'Not assigned'}")
    return " — ".join(parts)


def _meta(recipe: RecipeResult) -> str:
    sku = f"SKU {recipe.sku}" + (f" · {recipe.customization}" if recipe.customization else "")
    return sku


# ------------------------------------------------------------------ PDF

_C = colors.HexColor
_HEADING = ParagraphStyle(
    "recipe_heading",
    fontName="Helvetica-Bold",
    fontSize=11.5,
    leading=15,
    textColor=_C(DARK_GREEN),
    spaceBefore=4,
)
_FINDINGS = ParagraphStyle(
    "recipe_findings",
    fontName="Helvetica-Bold",
    fontSize=10,
    leading=13,
    textColor=_C(DARK_GREEN),
    spaceBefore=2,
    spaceAfter=3,
)
_META = ParagraphStyle(
    "recipe_meta", fontName="Helvetica", fontSize=8.6, leading=11.5, textColor=_C(BODY)
)
_STATUS = {
    "Yes": ("Issues found: Yes", _C(RED), _C(RED_TINT)),
    "Review required": ("Issues found: Review required", _C(AMBER), _C(AMBER_TINT)),
    "No": ("Issues found: No", _C(DARK_GREEN), _C(PASTEL_GREEN)),
    "Not evaluated": ("Not evaluated", _C(MUTED), _C("#EEF1EC")),
}


def _recipe_block(recipe: RecipeResult, width: float) -> list:
    label, color, tint = _STATUS[recipe.issues_found]
    title = html.escape(_heading(recipe))
    if recipe.recipe_url:
        title = title.replace(
            html.escape(recipe.title),
            f"<link href='{html.escape(recipe.recipe_url)}'>"
            f"<u>{html.escape(recipe.title)}</u></link>",
            1,
        )
    block: list = [
        Paragraph(title, _HEADING),
        Spacer(1, 2),
        Paragraph(html.escape(_meta(recipe)), _META),
        Spacer(1, 3),
        pill(label, color, tint),
        Spacer(1, 5),
    ]
    if recipe.takeaway and (recipe.findings or recipe.issues_found == "Not evaluated"):
        block += [
            callout(
                recipe.takeaway,
                width,
                color=_C(DARK_GREEN),
                tint=_C(PASTEL_GREEN),
                label="Key takeaways:",
            ),
            Spacer(1, 6),
        ]
    if recipe.findings:
        rows = []
        for finding in recipe.findings:
            f_color, f_tint = (
                (_C(RED), _C(RED_TINT)) if finding.result == ISSUE else (_C(AMBER), _C(AMBER_TINT))
            )
            rows.append(
                [
                    [
                        para(f"**{finding.finding_id}**", "cell"),
                        Spacer(1, 3),
                        pill(finding.result, f_color, f_tint),
                        Spacer(1, 3),
                        para(finding.issue_type, "muted"),
                    ],
                    para(f"**{finding.item}:** {finding.finding}", "cell"),
                    finding.evidence,
                    finding.reasoning,
                ]
            )
        rest = width - 1.5 * 72
        block += [
            Paragraph("Findings", _FINDINGS),
            data_table(
                ["ID / result / issue type", "Finding", "Evidence", "Reasoning"],
                rows,
                [1.5 * 72, rest * 0.30, rest * 0.38, rest * 0.32],
                header_color=_C(DARK_GREEN),
            ),
        ]
    block += [Spacer(1, 8), section_rule(width, _C(BORDER)), Spacer(1, 4)]
    return block


def build_pdf(
    recipes: list[RecipeResult], cycle_scope: str, run_at: str, xlsx_name: str = ""
) -> bytes:
    recipes = ordered(recipes)
    tally = counts(recipes)
    report = Report(
        ReportFrame(
            title="Recipe QA",
            subtitle=f"Cycle scope: {cycle_scope}  ·  Run: {run_at}",
            eyebrow="Editorial quality review",
            footer_note="Read-only review. No recipe data was changed.",
            band_color=_C(DARK_GREEN),
            accent_color=_C("#6FA37F"),
            eyebrow_color=_C("#B9D7C2"),
            subtitle_color=_C(PASTEL_GREEN),
            page_color=_C(CREAM),
        )
    )
    width = report.width
    story: list = [
        kpi_row(
            [
                (str(tally["recipes"]), "Recipes reviewed"),
                (str(tally["issues"]), "Issues found"),
                (str(tally["review"]), "Review required"),
                (str(tally["clean"]), "No issues"),
                (str(tally["findings"]), "Findings in total"),
            ],
            width,
            accent=_C(DARK_GREEN),
        ),
        Spacer(1, 10),
        para(
            "Checked for every recipe: ingredients listed but not used, ingredients used but not "
            "listed, equipment and cooking logic, and timing. Olive oil, neutral cooking oil, salt "
            "and pepper are excluded by policy. Each finding quotes the step or field it comes "
            "from.",
            "muted",
        ),
        Spacer(1, 8),
        section_rule(width, _C(BORDER)),
        Spacer(1, 4),
    ]
    for recipe in recipes:
        story.append(KeepTogether(_recipe_block(recipe, width)))
    if xlsx_name:
        story += [Spacer(1, 6), para(f"Attached with this report: {xlsx_name}", "muted")]
    return report.build(story)


# ------------------------------------------------------------------ Excel


def build_excel(recipes: list[RecipeResult]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    for recipe in ordered(recipes):
        if not recipe.findings:
            continue
        name = f"{recipe.sku}_{recipe.cycle or 'Unassigned'}"[:31]
        sheet = book.create_sheet(name)
        sheet.append(EXCEL_HEADERS)
        for finding in recipe.findings:
            sheet.append(
                (
                    finding.finding_id,
                    finding.result,
                    finding.issue_type,
                    finding.item,
                    finding.finding,
                    finding.evidence,
                    finding.reasoning,
                )
            )
    if not book.sheetnames:
        book.create_sheet("No_Findings").append(EXCEL_HEADERS)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# ------------------------------------------------------------------ email


def subject(recipes: list[RecipeResult], cycle_scope: str) -> str:
    tally = counts(recipes)
    if len(recipes) == 1:
        recipe = recipes[0]
        return (
            f"[Recipe QA] {recipe.title} | SKU {recipe.sku} | "
            f"{recipe.cycle or 'Not assigned'} | {recipe.issues_found}"
        )
    flagged = tally["issues"] + tally["review"]
    return f"[Recipe QA] {tally['recipes']} recipes | {flagged} with issues | {cycle_scope}"


def _e(value: object) -> str:
    return html.escape(str(value or ""))


def _html_recipe(recipe: RecipeResult) -> str:
    title = _e(recipe.title)
    if recipe.recipe_url:
        title = (
            f'<a href="{_e(recipe.recipe_url)}" style="color:{DARK_GREEN};'
            f'text-decoration:underline">{title}</a>'
        )
    parts = [f"Slot {_e(recipe.slot or '—')}", title]
    if recipe.subtitle:
        parts.append(_e(recipe.subtitle))
    parts.append(f"Cycle: {_e(recipe.cycle or 'Not assigned')}")
    out = [
        f'<h2 style="font-size:18px;line-height:1.4;color:{DARK_GREEN};margin:18px 0 6px">'
        + " — ".join(parts)
        + "</h2>",
        f'<p style="font-size:13px;margin:0 0 10px">{_e(_meta(recipe))} · '
        f"<strong>Issues found: {_e(recipe.issues_found)}</strong></p>",
    ]
    if recipe.takeaway and (recipe.findings or recipe.issues_found == "Not evaluated"):
        out.append(
            f'<p style="background:{PASTEL_GREEN};border-left:4px solid {DARK_GREEN};'
            f'padding:10px 12px;margin:8px 0 14px"><strong style="color:{DARK_GREEN}">'
            f"Key takeaways:</strong> {_e(recipe.takeaway)}</p>"
        )
    if recipe.findings:
        cell = f"padding:8px;border:1px solid {BORDER};vertical-align:top;word-wrap:break-word"
        rows = "".join(
            f'<tr><td style="{cell}"><strong>{_e(f.finding_id)}</strong><br>{_e(f.result)}'
            f'<br><span style="color:{MUTED}">{_e(f.issue_type)}</span></td>'
            f'<td style="{cell}"><strong>{_e(f.item)}:</strong> {_e(f.finding)}</td>'
            f'<td style="{cell}">{_e(f.evidence)}</td>'
            f'<td style="{cell}">{_e(f.reasoning)}</td></tr>'
            for f in recipe.findings
        )
        out.append(
            f'<h3 style="font-size:16px;color:{DARK_GREEN};margin:12px 0 8px">Findings</h3>'
            '<table style="border-collapse:collapse;width:100%;table-layout:fixed;font-size:13px">'
            f'<tr style="background:{DARK_GREEN};color:#FFFFFF;text-align:left">'
            '<th style="padding:8px;width:18%">ID / result / issue type</th>'
            '<th style="padding:8px;width:27%">Finding</th>'
            '<th style="padding:8px;width:30%">Evidence</th>'
            '<th style="padding:8px;width:25%">Reasoning</th></tr>' + rows + "</table>"
        )
    return "".join(out)


def email_bodies(
    recipes: list[RecipeResult], cycle_scope: str, run_at: str, pdf_name: str, xlsx_name: str
) -> tuple[str, str]:
    """The full report as the HTML body, and a plain-text fallback."""
    recipes = ordered(recipes)
    tally = counts(recipes)
    html_body = (
        f'<div style="font-family:{FONT_STACK};color:{BODY};background:{CREAM};padding:18px;'
        'max-width:860px">'
        f'<div style="background:{DARK_GREEN};color:#FFFFFF;padding:14px 18px;margin:0 0 18px">'
        '<div style="font-size:20px;font-weight:bold">Recipe QA</div>'
        f'<div style="font-size:13px;color:{PASTEL_GREEN}">Cycle scope: {_e(cycle_scope)} · '
        f"Run: {_e(run_at)}</div></div>"
        f'<p style="font-size:14px;margin:0 0 6px"><strong>{tally["recipes"]}</strong> recipes '
        f"reviewed · <strong>{tally['issues']}</strong> with issues · "
        f"<strong>{tally['review']}</strong> review required · <strong>{tally['clean']}</strong> "
        "with no issues</p>"
        + "".join(_html_recipe(recipe) for recipe in recipes)
        + f'<p style="font-size:13px;color:{MUTED};margin:18px 0 4px">Attached: {_e(pdf_name)} '
        f"and {_e(xlsx_name)}</p>"
        f'<p style="font-size:12px;color:{MUTED};margin:0">Read-only review. No recipe data was '
        "changed.</p></div>"
    )
    lines = [
        f"Recipe QA - cycle scope {cycle_scope}, run {run_at}",
        f"{tally['recipes']} recipes reviewed, {tally['issues']} with issues, "
        f"{tally['review']} review required, {tally['clean']} with no issues.",
        "",
    ]
    for recipe in recipes:
        lines.append(f"{_heading(recipe)} | {_meta(recipe)} | Issues found: {recipe.issues_found}")
        if recipe.takeaway and recipe.findings:
            lines.append(f"  Key takeaways: {recipe.takeaway}")
        for f in recipe.findings:
            lines.append(f"  {f.finding_id} [{f.result}] {f.issue_type} - {f.item}: {f.finding}")
    lines += ["", f"Attached: {pdf_name} and {xlsx_name}.", "Read-only review."]
    return html_body, "\n".join(lines)
