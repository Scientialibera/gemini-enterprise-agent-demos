"""Recipe content layout helpers."""

from __future__ import annotations

import re
from typing import Any

from .drawing import (
    clean,
    wrapped_line_count,
)
from .theme import (
    HEAD_CHAR_WIDTH_RATIO,
    TITLE_FONT_SIZES,
    TITLE_MAX_LINES,
    TITLE_W,
)


def split_instructions(step: dict[str, Any]) -> list[str]:
    bullets = step.get("bullets")
    if bullets:
        return [clean(v).strip() for v in bullets if clean(v).strip()]

    body = clean(step.get("body") or step.get("instructions"))
    if not body:
        return []
    if "\n" in body:
        return [re.sub(r"^[-•□\s]+", "", s).strip() for s in body.splitlines() if s.strip()]

    body = re.sub(r";\s+", ". ", body)
    parts = re.split(r"\.\s+", body)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not re.search(r"[.!?]$", p):
            p += "."
        # A clause split off at a semicolon starts lower case; as its own
        # checklist item it reads as a sentence.
        out.append(p[0].upper() + p[1:])
    return out


def title_font(title: str) -> float:
    """The largest headline size that sets the dish name in two lines.

    Measured rather than switched on character count: "Lemon Herb Roast
    Chicken" is short by count but breaks into three lines at full size.
    """
    for size in TITLE_FONT_SIZES:
        if (
            wrapped_line_count(clean(title), TITLE_W, size, HEAD_CHAR_WIDTH_RATIO)
            <= TITLE_MAX_LINES
        ):
            return size
    return TITLE_FONT_SIZES[-1]


def heading_size(text: str, width: float, sizes: tuple[float, ...], lines: int = 1) -> float:
    """The largest of ``sizes`` that sets a heading within ``lines`` lines."""
    for size in sizes:
        if wrapped_line_count(clean(text), width, size, HEAD_CHAR_WIDTH_RATIO) <= lines:
            return size
    return sizes[-1]


STEPS_PER_TIP = 4


def cooking_tip_for_steps(recipe: dict[str, Any], first: int, count: int) -> str:
    """The tip banner for a page carrying steps ``first`` to ``first + count - 1``.

    ``cooking_tip`` may be a list with one entry per four steps, each about
    those steps, so a tip about boiling pasta is not repeated above the steps
    for the sauce. Pages are packed by height rather than by fours, so a page
    shows every tip whose steps it carries, joined, and no tip is dropped. A
    plain string is used on the first page only.
    """
    tips = recipe.get("cooking_tip")
    if not isinstance(tips, list):
        return clean(tips) if first == 0 else ""
    entries = [clean(tip) for tip in tips if clean(tip)]
    # Each tip appears once, on the page that carries the first of its steps.
    return " ".join(
        tip for group, tip in enumerate(entries) if first <= group * STEPS_PER_TIP < first + count
    )
