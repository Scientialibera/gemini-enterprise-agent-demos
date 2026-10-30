"""Check a written recipe before any image is made, and list the images it needs.

Nothing used to look at the recipe until the deck was rendered, the last step.
By then every photograph had been paid for, a card written with legacy one-line
variations had no pictures for their ingredients, and each over-long field cost
a full render and retry. Checking first catches all of it in one pass, while a
fix is only an edit, and hands the image step an exact list to generate from.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from .rendering.content import STEPS_PER_TIP, split_instructions
from .runs import safe_slug
from .schema import MAX_IMAGES_PER_BATCH, load_recipes

# Longest each field may be, in characters, matched to the space the card
# gives it at its fixed type size. Under these the renderer never cuts a word.
TEXT_BUDGETS = {
    "title": 30,
    "subtitle": 40,
    "card_title": 40,
    "seasonal_blurb": 70,
    "description": 200,
    "chef_note.text": 220,
}
TIP_MAX = 150
STEP_TITLE_MAX = 30
INSTRUCTION_MAX = 120
INSTRUCTIONS_PER_STEP = 5
INGREDIENT_ITEM_MAX = 26
BANNER_LINE_MAX = 22
BRAND_LINE_MAX = 20
CUSTOMIZATIONS = (2, 3)


def _value(recipe: dict[str, Any], field: str) -> str:
    value: Any = recipe
    for part in field.split("."):
        value = value.get(part, "") if isinstance(value, dict) else ""
    return str(value or "")


def _too_long(field: str, text: str, limit: int) -> dict[str, str]:
    return {
        "field": field,
        "problem": f"{len(text)} characters; the card holds {limit - 1} at most.",
        "fix": f"Rewrite {field} in under {limit} characters, keeping its meaning.",
    }


def _problems(recipe: dict[str, Any]) -> list[dict[str, str]]:
    problems = []
    for field, limit in TEXT_BUDGETS.items():
        text = _value(recipe, field)
        if len(text) >= limit:
            problems.append(_too_long(field, text, limit))

    steps = recipe.get("steps") or []
    tips = recipe.get("cooking_tip")
    if isinstance(tips, list):
        wanted = math.ceil(len(steps) / STEPS_PER_TIP)
        if len(tips) != wanted:
            problems.append(
                {
                    "field": "cooking_tip",
                    "problem": f"{len(tips)} tips for {len(steps)} steps.",
                    "fix": f"Write exactly {wanted}: one per four steps, about those steps.",
                }
            )
        tips = list(tips)
    else:
        tips = [tips] if tips else []
    for index, tip in enumerate(tips):
        if len(tip) >= TIP_MAX:
            problems.append(_too_long(f"cooking_tip[{index}]", tip, TIP_MAX))

    for index, step in enumerate(steps):
        if len(step.get("title", "")) >= STEP_TITLE_MAX:
            problems.append(_too_long(f"steps[{index}].title", step["title"], STEP_TITLE_MAX))
        instructions = split_instructions(step)
        if len(instructions) > INSTRUCTIONS_PER_STEP:
            problems.append(
                {
                    "field": f"steps[{index}]",
                    "problem": f"{len(instructions)} instructions.",
                    "fix": (
                        f"Keep at most {INSTRUCTIONS_PER_STEP} instructions, or split the "
                        "step in two."
                    ),
                }
            )
        for line, text in enumerate(instructions):
            if len(text) >= INSTRUCTION_MAX:
                problems.append(
                    _too_long(f"steps[{index}] instruction {line + 1}", text, INSTRUCTION_MAX)
                )

    for index, ingredient in enumerate(recipe.get("ingredients") or []):
        if len(ingredient["item"]) >= INGREDIENT_ITEM_MAX:
            problems.append(
                _too_long(f"ingredients[{index}].item", ingredient["item"], INGREDIENT_ITEM_MAX)
            )

    for field, limit in (("bottom_banner_text", BANNER_LINE_MAX), ("brand_line", BRAND_LINE_MAX)):
        text = _value(recipe, field)
        if not text:
            continue
        lines = text.split("\n")
        if len(lines) != 2 or any(len(line) >= limit for line in lines):
            problems.append(
                {
                    "field": field,
                    "problem": f"{len(lines)} line(s): {text!r}.",
                    "fix": (
                        f"Write exactly two lines, each under {limit} characters, joined by "
                        "a newline (\\n) with no bullet or separator."
                    ),
                }
            )

    options = recipe.get("customizations") or []
    low, high = CUSTOMIZATIONS
    if not low <= len(options) <= high:
        legacy = (
            " The one-line variations are for legacy cards only."
            if recipe.get("variations")
            else ""
        )
        problems.append(
            {
                "field": "customizations",
                "problem": f"{len(options)} customizations.{legacy}",
                "fix": (
                    f"Write {low} or {high} customizations, each with name, replaces, the "
                    "full replacement ingredients with quantities, and the steps it changes. "
                    "Remove variations and variation_ingredients."
                ),
            }
        )
    return problems


def _ingredient_images(recipe: dict[str, Any]) -> list[dict[str, str]]:
    """Every ingredient picture the card shows, core list first, each once."""
    images: dict[str, dict[str, str]] = {}
    sources = [("core", recipe.get("ingredients") or [])] + [
        (option["name"], option.get("ingredients") or [])
        for option in recipe.get("customizations") or []
    ]
    for source, ingredients in sources:
        for ingredient in ingredients:
            key = ingredient["item"].casefold().strip()
            if key not in images:
                images[key] = {
                    "name": safe_slug(f"ingredient-{ingredient['item']}", "ingredient"),
                    "item": ingredient["item"],
                    "for": source,
                }
    return list(images.values())


def check_recipe(recipe_json: str) -> dict[str, object]:
    """Check the written recipe and list every image it needs. Call before any image.

    Checks every text field against the space the card gives it, the cooking
    tip count, the instructions per step, the banner lines and that there are
    two or three full customizations. All problems come back together. When it
    returns `ready`, generate exactly the images it lists.

    Args:
        recipe_json: The recipe as a JSON string, in the shape render_recipe_card
            takes, with no image paths yet.
    """
    try:
        data = load_recipes(recipe_json)
    except (ValidationError, ValueError) as invalid:
        if isinstance(invalid, ValidationError):
            first = invalid.errors()[0]
            field = ".".join(str(part) for part in first.get("loc", ())) or "recipes"
            detail = f"{first.get('msg', 'invalid')} at {field}."
        else:
            field, detail = "recipes", str(invalid)
        return {
            "status": "needs_correction",
            "problems": [{"field": field, "problem": detail, "fix": "Correct it."}],
            "next_step": "Fix every problem and call check_recipe again.",
        }

    recipe = data["recipes"][0]
    problems = _problems(recipe)
    if problems:
        return {
            "status": "needs_correction",
            "problems": problems,
            "next_step": (
                "Fix every problem listed, then call check_recipe again with the whole "
                "recipe. Generate no images until it returns ready."
            ),
        }

    ingredients = _ingredient_images(recipe)
    steps = len(recipe.get("steps") or [])
    return {
        "status": "ready",
        "slug": safe_slug(str(recipe.get("slug") or recipe["title"])),
        "sketch": "sketch",
        "photographs": ["hero", *(f"step-{n}" for n in range(1, steps + 1))],
        "ingredient_images": ingredients,
        "next_step": (
            "Generate exactly these images: the sketch first, then the ingredient_images "
            "and the photographs together, using each name as given. Split the ingredients "
            f"into calls of at most {MAX_IMAGES_PER_BATCH}. Then put each returned path in "
            "the matching image field, including every customization's ingredients."
        ),
    }


__all__ = ["check_recipe"]
