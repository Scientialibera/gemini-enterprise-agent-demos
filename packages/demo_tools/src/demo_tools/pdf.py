"""The shared report theme: one look for every PDF the demo agents produce.

Built on ReportLab with its standard fonts, so nothing has to be installed on the
runtime. Text from the model passes through ``para`` first: it is escaped, a
light subset of markdown (``**bold**``, ``*italic*``) becomes markup, and glyphs
the standard fonts cannot draw are replaced rather than rendered as boxes.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ------------------------------------------------------------------ palette

NAVY = colors.HexColor("#12263A")
TEAL = colors.HexColor("#1F7A8C")
TEAL_DARK = colors.HexColor("#155E6C")
MINT = colors.HexColor("#E3F2EF")
SAND = colors.HexColor("#F7F4EE")
BORDER = colors.HexColor("#D9DEE3")
INK = colors.HexColor("#1D2730")
MUTED = colors.HexColor("#5B6770")
WHITE = colors.white
CORAL = colors.HexColor("#D9483B")
CORAL_TINT = colors.HexColor("#FBE7E4")
AMBER = colors.HexColor("#C98A0C")
AMBER_TINT = colors.HexColor("#FDF2DA")
GREEN = colors.HexColor("#2E8B57")
GREEN_TINT = colors.HexColor("#E2F3E9")
SLATE_TINT = colors.HexColor("#EEF1F4")

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

# ------------------------------------------------------------------ text styles

STYLES = {
    "body": ParagraphStyle(
        "body", fontName=FONT, fontSize=9.2, leading=12.6, textColor=INK, alignment=TA_LEFT
    ),
    "small": ParagraphStyle("small", fontName=FONT, fontSize=8, leading=10.4, textColor=INK),
    "muted": ParagraphStyle("muted", fontName=FONT, fontSize=8, leading=10.4, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName=FONT, fontSize=8, leading=10.2, textColor=INK),
    "cell_bold": ParagraphStyle(
        "cell_bold", fontName=FONT_BOLD, fontSize=8, leading=10.2, textColor=INK
    ),
    "head": ParagraphStyle("head", fontName=FONT_BOLD, fontSize=8, leading=10, textColor=WHITE),
    "h1": ParagraphStyle(
        "h1", fontName=FONT_BOLD, fontSize=17, leading=21, textColor=NAVY, spaceAfter=4
    ),
    "h2": ParagraphStyle(
        "h2",
        fontName=FONT_BOLD,
        fontSize=12.5,
        leading=16,
        textColor=NAVY,
        spaceBefore=8,
        spaceAfter=4,
    ),
    "h3": ParagraphStyle(
        "h3",
        fontName=FONT_BOLD,
        fontSize=10.2,
        leading=13.5,
        textColor=TEAL_DARK,
        spaceBefore=6,
        spaceAfter=2,
    ),
    "eyebrow": ParagraphStyle(
        "eyebrow", fontName=FONT_BOLD, fontSize=7.5, leading=9, textColor=TEAL
    ),
    "bullet": ParagraphStyle(
        "bullet",
        fontName=FONT,
        fontSize=9.2,
        leading=12.6,
        textColor=INK,
        leftIndent=12,
        bulletIndent=2,
        spaceAfter=2,
    ),
    "kpi_value": ParagraphStyle(
        "kpi_value", fontName=FONT_BOLD, fontSize=20, leading=23, textColor=NAVY
    ),
    "kpi_label": ParagraphStyle(
        "kpi_label", fontName=FONT, fontSize=7.8, leading=10, textColor=MUTED
    ),
    "callout": ParagraphStyle("callout", fontName=FONT, fontSize=9.2, leading=12.6, textColor=INK),
}

# ------------------------------------------------------------------ text helpers

# Glyphs outside the standard fonts' encoding, mapped to something they can draw.
_REPLACEMENTS = {
    "★": " stars",  # ★
    "☆": "",
    "→": "->",
    "←": "<-",
    "↑": "up",
    "↓": "down",
    "≤": "<=",
    "≥": ">=",
    "≈": "~",
    " ": " ",
    " ": " ",
    " ": " ",
    "‑": "-",
    "−": "-",
    "✓": "",
    "✔": "",
    "✗": "",
    "❌": "",
    "✅": "",
}
_ENCODABLE = re.compile(r"[^\x09\x0a\x0d\x20-\x7e\xa0-\xff–—‘’“”•…€]")


def clean_text(text: object) -> str:
    """Plain text the standard fonts can draw."""
    value = "" if text is None else str(text)
    for source, target in _REPLACEMENTS.items():
        value = value.replace(source, target)
    return _ENCODABLE.sub("", value)


def inline_markup(text: object) -> str:
    """Escape, then turn **bold** and *italic* into ReportLab markup."""
    value = clean_text(text)
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", value)
    value = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", value)
    return value.replace("\n", "<br/>")


def para(text: object, style: str | ParagraphStyle = "body") -> Paragraph:
    chosen = STYLES[style] if isinstance(style, str) else style
    return Paragraph(inline_markup(text), chosen)


def colored(text: object, color: colors.Color, style: str = "cell", bold: bool = True) -> Paragraph:
    """Escaped text in one colour, bold by default, for a highlighted table cell."""
    body = inline_markup(text)
    if bold:
        body = f"<b>{body}</b>"
    return Paragraph(f"<font color='#{color.hexval()[2:]}'>{body}</font>", STYLES[style])


def markdown_flowables(markdown: str) -> list[Flowable]:
    """Headings, bullets and paragraphs from the light markdown the models write."""
    flowables: list[Flowable] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            flowables.append(para(" ".join(paragraph)))
            flowables.append(Spacer(1, 3))
            paragraph.clear()

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped in {"---", "***"}:
            flush()
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        bullet = re.match(r"^(?:[*\-•]|\d+[.)])\s+(.*)$", stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            style = "h2" if level <= 2 else "h3"
            flowables.append(para(heading.group(2).strip("# "), style))
        elif bullet:
            flush()
            flowables.append(
                Paragraph(inline_markup(bullet.group(1)), STYLES["bullet"], bulletText="•")
            )
        else:
            paragraph.append(stripped)
    flush()
    return flowables


# ------------------------------------------------------------------ building blocks


def data_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    col_widths: Sequence[float],
    *,
    header_color: colors.Color = NAVY,
    zebra: bool = True,
    bold_first_column: bool = False,
    font_size: float | None = None,
) -> Table:
    """A wrapping table with a coloured header row and alternating row tint."""
    cell = STYLES["cell"]
    cell_bold = STYLES["cell_bold"]
    if font_size:
        cell = ParagraphStyle(
            "cell_sized", parent=cell, fontSize=font_size, leading=font_size * 1.27
        )
        cell_bold = ParagraphStyle(
            "cell_bold_sized", parent=cell_bold, fontSize=font_size, leading=font_size * 1.27
        )
    data = [[Paragraph(inline_markup(h), STYLES["head"]) for h in headers]]
    for row in rows:
        data.append(
            [
                value
                if isinstance(value, Flowable | list)
                else Paragraph(
                    inline_markup(value), cell_bold if (bold_first_column and i == 0) else cell
                )
                for i, value in enumerate(row)
            ]
        )
    table = Table(data, colWidths=list(col_widths), repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
    ]
    if zebra:
        for index in range(1, len(data)):
            if index % 2 == 0:
                style.append(("BACKGROUND", (0, index), (-1, index), SAND))
    table.setStyle(TableStyle(style))
    return table


def kpi_row(items: Sequence[tuple[str, str]], width: float, accent: colors.Color = TEAL) -> Table:
    """Big-number tiles: (value, label) pairs side by side."""
    count = max(1, len(items))
    cells = [
        [para(value, "kpi_value"), Spacer(1, 2), para(label, "kpi_label")] for value, label in items
    ]
    gap = 8
    tile = (width - gap * (count - 1)) / count
    widths = []
    row = []
    for index, cell in enumerate(cells):
        row.append(cell)
        widths.append(tile)
        if index < count - 1:
            row.append("")
            widths.append(gap)
    table = Table([row], colWidths=widths)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP")]
    for index in range(0, len(row), 2):
        style += [
            ("BACKGROUND", (index, 0), (index, 0), WHITE),
            ("BOX", (index, 0), (index, 0), 0.6, BORDER),
            ("LINEABOVE", (index, 0), (index, 0), 3, accent),
            ("LEFTPADDING", (index, 0), (index, 0), 10),
            ("TOPPADDING", (index, 0), (index, 0), 9),
            ("BOTTOMPADDING", (index, 0), (index, 0), 9),
        ]
    table.setStyle(TableStyle(style))
    return table


def callout(
    text: str,
    width: float,
    *,
    color: colors.Color = TEAL,
    tint: colors.Color = MINT,
    label: str = "",
) -> Table:
    """A tinted box with a coloured left rule, for takeaways and notes."""
    content = f"<b>{inline_markup(label)}</b> " if label else ""
    body = Paragraph(content + inline_markup(text), STYLES["callout"])
    table = Table([[body]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), tint),
                ("LINEBEFORE", (0, 0), (0, -1), 3.5, color),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def pill(text: str, color: colors.Color, tint: colors.Color) -> Table:
    """A small coloured status label."""
    style = ParagraphStyle("pill", fontName=FONT_BOLD, fontSize=7.2, leading=8.6, textColor=color)
    label = clean_text(text.upper())
    width = stringWidth(label, FONT_BOLD, 7.2) + 12
    table = Table([[Paragraph(inline_markup(label), style)]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), tint),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    table.hAlign = "LEFT"
    return table


def section_rule(width: float, color: colors.Color = BORDER) -> Table:
    table = Table([[""]], colWidths=[width], rowHeights=[1])
    table.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 0.8, color)]))
    return table


# ------------------------------------------------------------------ document


@dataclass(frozen=True, slots=True)
class ReportFrame:
    """Title, subtitle and footer text that every page of a report carries."""

    title: str
    subtitle: str
    eyebrow: str
    footer_note: str
    landscape_pages: bool = False
    band_color: colors.Color = NAVY
    accent_color: colors.Color = TEAL
    eyebrow_color: colors.Color = colors.HexColor("#9CC9D1")
    subtitle_color: colors.Color = colors.HexColor("#C9D6DF")
    page_color: colors.Color | None = None


class Report:
    """A paged report: a tall title band on page one, a slim header afterwards."""

    margin = 0.55 * inch

    def __init__(self, frame: ReportFrame) -> None:
        self.frame = frame
        self.pagesize = landscape(letter) if frame.landscape_pages else letter
        self.generated = dt.datetime.now(dt.UTC)

    @property
    def width(self) -> float:
        return self.pagesize[0] - 2 * self.margin

    def _first_page(self, canvas, doc) -> None:
        width, height = self.pagesize
        band = 1.18 * inch
        canvas.saveState()
        self._page_background(canvas)
        canvas.setFillColor(self.frame.band_color)
        canvas.rect(0, height - band, width, band, stroke=0, fill=1)
        canvas.setFillColor(self.frame.accent_color)
        canvas.rect(0, height - band - 4, width, 4, stroke=0, fill=1)
        canvas.setFillColor(self.frame.eyebrow_color)
        canvas.setFont(FONT_BOLD, 7.5)
        canvas.drawString(self.margin, height - 0.36 * inch, clean_text(self.frame.eyebrow).upper())
        canvas.setFillColor(WHITE)
        canvas.setFont(FONT_BOLD, 19)
        canvas.drawString(self.margin, height - 0.68 * inch, clean_text(self.frame.title))
        canvas.setFillColor(self.frame.subtitle_color)
        canvas.setFont(FONT, 9.5)
        canvas.drawString(self.margin, height - 0.93 * inch, clean_text(self.frame.subtitle))
        canvas.restoreState()
        self._footer(canvas, doc)

    def _later_pages(self, canvas, doc) -> None:
        width, height = self.pagesize
        canvas.saveState()
        self._page_background(canvas)
        canvas.setFillColor(self.frame.band_color)
        canvas.rect(0, height - 0.42 * inch, width, 0.42 * inch, stroke=0, fill=1)
        canvas.setFillColor(WHITE)
        canvas.setFont(FONT_BOLD, 8.5)
        canvas.drawString(self.margin, height - 0.27 * inch, clean_text(self.frame.title))
        canvas.setFillColor(self.frame.subtitle_color)
        canvas.setFont(FONT, 8)
        canvas.drawRightString(
            width - self.margin, height - 0.27 * inch, clean_text(self.frame.subtitle)
        )
        canvas.restoreState()
        self._footer(canvas, doc)

    def _page_background(self, canvas) -> None:
        if self.frame.page_color is not None:
            width, height = self.pagesize
            canvas.setFillColor(self.frame.page_color)
            canvas.rect(0, 0, width, height, stroke=0, fill=1)

    def _footer(self, canvas, doc) -> None:
        width, _ = self.pagesize
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.6)
        canvas.line(self.margin, 0.5 * inch, width - self.margin, 0.5 * inch)
        canvas.setFillColor(MUTED)
        canvas.setFont(FONT, 7.2)
        canvas.drawString(self.margin, 0.33 * inch, clean_text(self.frame.footer_note))
        canvas.drawRightString(width - self.margin, 0.33 * inch, f"Page {doc.page}")
        canvas.restoreState()

    def build(self, story: list[Flowable]) -> bytes:
        buffer = io.BytesIO()
        _, height = self.pagesize
        doc = BaseDocTemplate(
            buffer,
            pagesize=self.pagesize,
            leftMargin=self.margin,
            rightMargin=self.margin,
            topMargin=self.margin,
            bottomMargin=self.margin,
            title=clean_text(self.frame.title),
            author="Gemini Enterprise demo agent",
        )
        first = Frame(
            self.margin,
            0.65 * inch,
            self.width,
            height - 1.5 * inch - 0.65 * inch,
            id="first",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        later = Frame(
            self.margin,
            0.65 * inch,
            self.width,
            height - 0.62 * inch - 0.65 * inch,
            id="later",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        doc.addPageTemplates(
            [
                PageTemplate(
                    id="First",
                    frames=[first],
                    onPage=self._first_page,
                    autoNextPageTemplate="Later",
                ),
                PageTemplate(id="Later", frames=[later], onPage=self._later_pages),
            ]
        )
        doc.build(story)
        return buffer.getvalue()


__all__ = [
    "AMBER",
    "AMBER_TINT",
    "BORDER",
    "CORAL",
    "CORAL_TINT",
    "GREEN",
    "GREEN_TINT",
    "INK",
    "MINT",
    "MUTED",
    "NAVY",
    "SAND",
    "SLATE_TINT",
    "STYLES",
    "TEAL",
    "TEAL_DARK",
    "WHITE",
    "CondPageBreak",
    "KeepTogether",
    "PageBreak",
    "Report",
    "ReportFrame",
    "Spacer",
    "callout",
    "clean_text",
    "colored",
    "data_table",
    "inline_markup",
    "kpi_row",
    "markdown_flowables",
    "para",
    "pill",
    "section_rule",
]
