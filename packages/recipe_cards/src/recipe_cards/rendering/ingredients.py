"""Recipe ingredients layout helpers."""

from __future__ import annotations

import math

from ..errors import ContentTooLong
from .drawing import (
    add_box,
    add_cutout_image,
    add_rule,
    add_soft_shadow,
    add_text,
    add_vrule,
    chunks,
    clean,
    fit_to_box,
    servings_label,
)
from .footer import add_footer
from .theme import (
    CONTINUES_NOTE_GAP,
    HEAD_FONT,
    INGREDIENT_FONT_SIZE,
    INGREDIENT_MAX_ROWS,
    INGREDIENT_PANEL_MAX_BOTTOM,
    INGREDIENT_PANEL_PADDING,
    INGREDIENT_PANEL_TOP,
    INGREDIENT_ROW_MAX_HEIGHT,
    INGREDIENT_ROW_MIN_HEIGHT,
    LEFT_W,
    SERVINGS_TEXT_OFFSET,
    SERVINGS_Y,
    C,
)


def add_ingredient_row(
    slide,
    ing,
    y: float,
    row_h: float,
    *,
    muted: bool = False,
    x: float = 0.40,
    width: float = 2.64,
    field: str = "ingredients",
) -> None:
    """Draw one ingredient: cutout, quantity, rule, label.

    ``muted`` sets the row in the secondary colour, which is how an ingredient
    that belongs to a variation is distinguished from one the recipe requires.
    """
    colour = C["muted"] if muted else C["ink"]
    scale = width / 2.64
    note = clean(ing.get("note"))
    label = clean(ing.get("item")) + ("\n" + note if note else "")
    quantity = clean(ing.get("quantity"))
    for name, text, w, h in (
        ("quantity", quantity, 0.66 * scale, row_h * 0.60),
        ("item/note", label, 1.16 * scale - 0.02, row_h * 0.72 - 0.02),
    ):
        if fit_to_box(text, w, h, INGREDIENT_FONT_SIZE) != text:
            raise ContentTooLong(
                f"{field}.{name}",
                f"Ingredient {name} does not fit its row.",
                "Use a shorter ingredient description or unit abbreviation; preserve the amount.",
            )
    # The reference cards set the ingredient as a cutout on the panel with no
    # ring around it, so the photograph reads as the ingredient itself rather
    # than as an avatar of one.
    add_cutout_image(
        slide,
        ing.get("image_path") or ing.get("imagePath"),
        x,
        y + row_h * 0.10,
        0.58 * scale,
        row_h * 0.80,
        placeholder=clean(ing.get("item"), "?")[:1].upper(),
    )
    add_text(
        slide,
        quantity,
        x + 0.60 * scale,
        y + row_h * 0.20,
        0.66 * scale,
        row_h * 0.60,
        font_size=INGREDIENT_FONT_SIZE,
        color=colour,
        align="right",
        fit=False,
    )
    add_vrule(slide, x + 1.34 * scale, y + row_h * 0.30, row_h * 0.40, C["yellow"], 1.6)
    add_text(
        slide,
        label,
        x + 1.44 * scale,
        y + row_h * 0.14,
        1.16 * scale,
        row_h * 0.72,
        font_size=INGREDIENT_FONT_SIZE,
        color=colour,
        margin=0.01,
        fit=False,
    )


def ingredient_entries(recipe):
    """Keep core and optional ingredients ordered, with their correction paths."""
    entries = [
        (ingredient, key == "variation_ingredients", f"{key}[{index}]")
        for key in ("ingredients", "variation_ingredients")
        for index, ingredient in enumerate(recipe.get(key) or [])
    ]
    options = recipe.get("customizations") or []
    if not options:
        return entries
    replaced = {name.casefold() for option in options for name in option.get("replaces", [])}
    grouped = [
        ({**ing, "_option": "BASE OPTION"}, optional, field)
        for ing, optional, field in entries
        if ing["item"].casefold() in replaced
    ]
    for index, option in enumerate(options):
        grouped.extend(
            (
                {
                    **ing,
                    "_option": ("OR: " if option.get("replaces") else "OPTION: ") + option["name"],
                },
                True,
                f"customizations[{index}].ingredients[{i}]",
            )
            for i, ing in enumerate(option.get("ingredients", []))
        )
    return grouped + [entry for entry in entries if entry[0]["item"].casefold() not in replaced]


# The shortest row that still holds a two-line ingredient name beside its
# picture. The rail takes as many rows as fit at this height, so a long list
# stays on the overview rather than spilling three items onto the next page
# while every row above them stood twice as tall as it needed.
RAIL_MIN_ROW_H = 0.50
RAIL_HEADING_H = 0.38


def _group_headers(entries) -> int:
    labels = [ingredient.get("_option", "") for ingredient, _, _ in entries]
    return sum(
        1
        for index, label in enumerate(labels)
        if label and label != (labels[index - 1] if index else None)
    )


def _rail_row_height(recipe, entries) -> float:
    """Row height the rail would give these entries."""
    height = INGREDIENT_PANEL_MAX_BOTTOM - INGREDIENT_PANEL_TOP
    if recipe.get("customizations"):
        usable = height - RAIL_HEADING_H - _group_headers(entries) * RAIL_GROUP_HEADER_H
        return usable / max(1, len(entries))
    heading_rows = 1 if any(optional for _, optional, _ in entries) else 0
    return (height - 2 * INGREDIENT_PANEL_PADDING) / max(1, len(entries) + heading_rows)


def rail_capacity(recipe) -> int:
    """How many ingredients the overview's rail shows."""
    entries = ingredient_entries(recipe)
    capacity = min(len(entries), INGREDIENT_MAX_ROWS)
    while capacity < len(entries) and (
        _rail_row_height(recipe, entries[: capacity + 1]) >= RAIL_MIN_ROW_H
    ):
        capacity += 1
    return capacity


def add_ingredient_rail(slide, recipe):
    y0 = SERVINGS_Y
    pill = add_box(slide, 0.68, y0, 2.10, 0.38, C["yellow"], C["yellow"], radius=True)
    pill.adjustments[0] = 0.5
    add_soft_shadow(pill, alpha=26)
    add_text(
        slide,
        servings_label(recipe.get("servings")),
        0.78,
        y0 + SERVINGS_TEXT_OFFSET,
        1.90,
        0.26,
        font_size=15,
        bold=True,
        color=C["dark_blue"],
        align="center",
    )

    if recipe.get("customizations"):
        add_customized_rail(slide, recipe)
        return

    core = list(recipe.get("ingredients") or [])
    # Ingredients a variation needs are listed too, under their own heading, so
    # a cook can shop for one without reading the whole method. They are kept
    # apart from the core list because they are optional: mixed in, an optional
    # item reads as required.
    extras = list(recipe.get("variation_ingredients") or [])

    capacity = rail_capacity(recipe)
    max_rows = min(len(core), capacity)
    remaining = max(0, capacity - max_rows)
    extra_rows = min(len(extras), remaining)
    total_rows = max_rows + extra_rows
    # The heading costs the height of one row.
    heading_rows = 1 if extra_rows else 0

    # Rows keep a constant pitch and the panel is drawn to fit them, so a short
    # list gives a shorter panel rather than one with an empty lower half.
    # Only a list long enough to reach the bottom of the page compresses its
    # rows, and never below the readable minimum.
    panel_y = INGREDIENT_PANEL_TOP
    available_h = INGREDIENT_PANEL_MAX_BOTTOM - panel_y
    usable_h = available_h - 2 * INGREDIENT_PANEL_PADDING
    row_h = min(INGREDIENT_ROW_MAX_HEIGHT, usable_h / max(1, total_rows + heading_rows))
    row_h = max(row_h, INGREDIENT_ROW_MIN_HEIGHT)
    panel_h = min(
        available_h,
        row_h * (total_rows + heading_rows) + 2 * INGREDIENT_PANEL_PADDING,
    )

    panel = add_box(
        slide, 0.27, panel_y, LEFT_W - 0.54, panel_h, C["white"], C["blue_soft"], radius=True
    )
    add_soft_shadow(panel)
    ingredients = core
    start_y = panel_y + INGREDIENT_PANEL_PADDING

    for i in range(max_rows):
        add_ingredient_row(
            slide, ingredients[i], start_y + i * row_h, row_h, field=f"ingredients[{i}]"
        )
        # Hairlines between rows keep a tall, airy list easy to scan across.
        if i < max_rows - 1:
            add_rule(slide, 0.50, start_y + (i + 1) * row_h, LEFT_W - 1.00, C["grey"], 0.5)

    if extra_rows:
        heading_y = start_y + max_rows * row_h
        add_rule(slide, 0.42, heading_y + row_h * 0.30, LEFT_W - 0.84, C["border"], 0.7)
        add_text(
            slide,
            "FOR THE VARIATIONS",
            0.42,
            heading_y + row_h * 0.42,
            LEFT_W - 0.84,
            row_h * 0.40,
            font_size=8.4,
            color=C["dark_blue"],
            bold=True,
        )
        for i in range(extra_rows):
            add_ingredient_row(
                slide,
                extras[i],
                heading_y + (i + 1) * row_h,
                row_h,
                muted=True,
                field=f"variation_ingredients[{i}]",
            )

    if len(core) + len(extras) > total_rows:
        add_text(
            slide,
            "Ingredients continue on the next page",
            0.35,
            INGREDIENT_PANEL_MAX_BOTTOM + CONTINUES_NOTE_GAP,
            LEFT_W - 0.70,
            0.12,
            font_size=7,
            color=C["muted"],
            align="center",
        )


def add_customized_rail(slide, recipe):
    """Show base and alternative quantities together, before shared ingredients."""
    entries = ingredient_entries(recipe)
    shown = entries[: rail_capacity(recipe)]
    top = INGREDIENT_PANEL_TOP
    height = INGREDIENT_PANEL_MAX_BOTTOM - top
    # Header height is spent only where a group heading actually appears.
    # Reserving it on every row left uneven gaps above the shared ingredients
    # and squeezed their pictures.
    labels = [ingredient.get("_option", "") for ingredient, _, _ in shown]
    headers = _group_headers(shown)
    row_h = min(INGREDIENT_ROW_MAX_HEIGHT, max(0.42, _rail_row_height(recipe, shown)))
    panel_h = min(height, RAIL_HEADING_H + len(shown) * row_h + headers * RAIL_GROUP_HEADER_H)
    panel = add_box(
        slide, 0.27, top, LEFT_W - 0.54, panel_h, C["white"], C["blue_soft"], radius=True
    )
    add_soft_shadow(panel)
    add_text(
        slide,
        "CUSTOMIZED OPTIONS",
        0.42,
        top + 0.05,
        LEFT_W - 0.84,
        0.18,
        font_size=8.4,
        bold=True,
        color=C["dark_blue"],
    )
    y = top + 0.28
    for index, (ingredient, optional, field) in enumerate(shown):
        label = labels[index]
        previous = labels[index - 1] if index else None
        if label and label != previous:
            add_rule(slide, 0.42, y, LEFT_W - 0.84, C["border"], 0.5)
            add_text(
                slide,
                label.upper(),
                0.42,
                y + 0.02,
                LEFT_W - 0.84,
                0.14,
                font_size=7,
                bold=True,
                color=C["dark_blue"],
            )
            y += RAIL_GROUP_HEADER_H
        elif not label and previous:
            add_rule(slide, 0.42, y, LEFT_W - 0.84, C["border"], 0.5)
        elif index:
            # Hairlines between shared ingredients, as on the standard rail.
            add_rule(slide, 0.50, y, LEFT_W - 1.00, C["grey"], 0.5)
        add_ingredient_row(slide, ingredient, y, row_h, muted=optional, field=field)
        y += row_h
    if len(entries) > len(shown):
        add_text(
            slide,
            "Ingredients continue on the next page",
            0.35,
            INGREDIENT_PANEL_MAX_BOTTOM + CONTINUES_NOTE_GAP,
            LEFT_W - 0.70,
            0.12,
            font_size=7,
            color=C["muted"],
            align="center",
        )


# A few ingredients past the rail's twelve rows are set as a strip at the top of
# the first steps page. A page of their own held four ingredients and a page of
# white; only a longer overflow still gets continuation pages.
STRIP_MAX = 8
RAIL_GROUP_HEADER_H = 0.16
STRIP_COLUMNS = 4
STRIP_ROW_H = 0.66
STRIP_HEADING_H = 0.28
STRIP_BOTTOM_GAP = 0.18
# Past this a cell's picture and type grow with it and outsize the rail's.
STRIP_CELL_MAX_W = 2.6


def _leftover_ingredients(recipe):
    return ingredient_entries(recipe)[rail_capacity(recipe) :]


def ingredient_strip_height(recipe) -> float:
    """Height of the strip on the first steps page, or 0 when there is none."""
    leftover = _leftover_ingredients(recipe)
    if not leftover or len(leftover) > STRIP_MAX:
        return 0.0
    rows = math.ceil(len(leftover) / STRIP_COLUMNS)
    return STRIP_HEADING_H + rows * STRIP_ROW_H + STRIP_BOTTOM_GAP


def add_ingredient_strip(slide, recipe, y: float) -> None:
    """Set the rail's overflow across the page, four to a row."""
    leftover = _leftover_ingredients(recipe)
    add_text(
        slide,
        "MORE INGREDIENTS",
        0.40,
        y,
        4.0,
        0.20,
        font_size=8.4,
        bold=True,
        color=C["dark_blue"],
    )
    # Three items in four columns left the right quarter of the row empty, so
    # the columns follow the count.
    columns = min(STRIP_COLUMNS, len(leftover))
    width = min(STRIP_CELL_MAX_W, (9.22 - 0.12 * (columns - 1)) / columns)
    for index, (ingredient, optional, field) in enumerate(leftover):
        row, column = divmod(index, columns)
        # A short row is centred as a group: spread to the margins, two items
        # sat at opposite edges of the page with nothing between them.
        span = columns * width + (columns - 1) * 0.12
        x = 0.34 + (9.22 - span) / 2 + column * (width + 0.12)
        cell_y = y + STRIP_HEADING_H + row * STRIP_ROW_H
        # An optional ingredient says which variation it belongs to, as on the
        # continuation pages, so it never reads as required.
        if optional or ingredient.get("_option"):
            add_text(
                slide,
                ingredient.get("_option", "OPTIONAL VARIATION"),
                x,
                cell_y,
                width,
                0.12,
                font_size=6.5,
                bold=True,
                color=C["muted"],
            )
        add_ingredient_row(
            slide,
            ingredient,
            cell_y + 0.08,
            STRIP_ROW_H - 0.08,
            x=x,
            width=width,
            muted=optional,
            field=field,
        )
    rows = math.ceil(len(leftover) / STRIP_COLUMNS)
    add_rule(
        slide,
        0.34,
        y + STRIP_HEADING_H + rows * STRIP_ROW_H + 0.04,
        9.22,
        C["grey"],
        0.6,
    )


def add_ingredient_continuation_slides(prs, recipe) -> int:
    """Render every remaining ingredient in two readable columns per page."""
    remaining = _leftover_ingredients(recipe)
    if ingredient_strip_height(recipe):
        return 0
    pages = list(chunks(remaining, INGREDIENT_MAX_ROWS))
    for entries in pages:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        add_text(
            slide,
            recipe.get("title", ""),
            0.4,
            0.3,
            9.2,
            0.65,
            font_face=HEAD_FONT,
            font_size=28,
            color=C["dark_blue"],
        )
        add_text(
            slide,
            "INGREDIENTS CONTINUED",
            0.4,
            1.1,
            9.2,
            0.3,
            font_size=14,
            bold=True,
            color=C["dark_blue"],
        )
        rows_per_column = INGREDIENT_MAX_ROWS // 2
        row_h = 1.60
        for index, (ingredient, optional, field) in enumerate(entries):
            column, row = divmod(index, rows_per_column)
            x, y = 0.4 + column * 4.8, 1.9 + row * row_h
            if optional or ingredient.get("_option"):
                add_text(
                    slide,
                    ingredient.get("_option", "OPTIONAL VARIATION"),
                    x,
                    y,
                    4.3,
                    0.18,
                    font_size=8,
                    bold=True,
                    color=C["muted"],
                )
            add_ingredient_row(
                slide,
                ingredient,
                y + 0.20,
                row_h - 0.30,
                x=x,
                width=4.3,
                muted=optional,
                field=field,
            )
            add_rule(slide, x, y + row_h - 0.06, 4.3, C["border"], 0.5)
        add_footer(slide, recipe)
    return len(pages)
