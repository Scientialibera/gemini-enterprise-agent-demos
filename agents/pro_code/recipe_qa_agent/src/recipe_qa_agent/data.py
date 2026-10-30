"""Fetch everything a QA check needs in one call, with the tested queries built in.

Letting the model write each query one at a time cost five to ten round trips per
run and invited column guesses. These functions run the tested templates
server-side and return one record per recipe: identity, timing, the cycle and
slot for the run, the preparation steps (product steps, or the legacy ones when
those are missing) and the current customer-facing ingredient list.
"""

from __future__ import annotations

import re
from typing import Any

from demo_tools.bigquery import run_readonly_query

from .config import ALLOWED_DATASETS, LEGACY_DATASET, PRODUCT_DATASET

MAX_SKUS = 10
SKU_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,32}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _rows(sql: str) -> list[dict[str, Any]]:
    result = run_readonly_query(sql, ALLOWED_DATASETS, max_rows=2000)
    if result.get("status") != "success":
        raise RuntimeError(result.get("message", "query failed"))
    return result["rows"]


def _quoted(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def get_recipe_details(skus: list[str], cycle: str = "") -> dict[str, Any]:
    """Retrieve identity, timing, cycle and slot, steps and current ingredients for SKUs.

    Args:
        skus: Up to 10 recipe SKUs, as strings.
        cycle: Optional menu cycle date (YYYY-MM-DD) the run is for. When empty, each
            recipe's latest cycle that has already started is used.

    Returns:
        One record per SKU with every field the QA checks need, and a list of SKUs not
        found. Steps come from the product tables, or from the legacy tables when the
        product steps are missing (step_source says which).
    """
    skus = [str(sku).strip() for sku in skus if str(sku).strip()]
    if not skus:
        return {"status": "error", "message": "Give at least one SKU."}
    if len(skus) > MAX_SKUS:
        return {"status": "error", "message": f"At most {MAX_SKUS} SKUs per call; split the list."}
    bad = [sku for sku in skus if not SKU_PATTERN.fullmatch(sku)]
    if bad or (cycle and not DATE_PATTERN.fullmatch(cycle)):
        return {"status": "error", "message": f"Invalid SKU or cycle: {bad or cycle}"}

    try:
        identity = _rows(
            f"""
            SELECT sku AS recipe_sku, p.product_name, p.product_subtitle,
              p.customization_description, p.servings, p.active_cook_time, p.total_cook_time,
              p.recipe_url, p.is_deleted, l.recipe_id, l.recipe_title, l.recipe_sub_title,
              l.recipe_customization_variable
            FROM UNNEST([{_quoted(skus)}]) AS sku
            LEFT JOIN `{PRODUCT_DATASET}.culinary_products` AS p ON p.recipe_sku = sku
            LEFT JOIN `{LEGACY_DATASET}.legacy_recipes` AS l ON l.recipe_sku = sku
            """
        )
        ids = [str(r["recipe_id"]) for r in identity if r.get("recipe_id") is not None]
        slots = (
            _rows(
                f"""
                SELECT recipe_id, cycle_date, recipe_slot_short_code AS slot
                FROM `{LEGACY_DATASET}.legacy_cycle_recipe_slots`
                WHERE recipe_id IN ({", ".join(ids)})
                ORDER BY cycle_date
                """
            )
            if ids
            else []
        )
        steps = _rows(
            f"""
            SELECT recipe_sku, step_number, step_title, instruction
            FROM `{PRODUCT_DATASET}.culinary_product_preparation_steps`
            WHERE recipe_sku IN ({_quoted(skus)})
            ORDER BY recipe_sku, step_number
            """
        )
        legacy_steps = (
            _rows(
                f"""
                SELECT recipe_id, recipe_step_sort_order AS step_number, step_title,
                  step_text AS instruction
                FROM `{LEGACY_DATASET}.legacy_recipe_steps`
                WHERE recipe_id IN ({", ".join(ids)})
                ORDER BY recipe_id, recipe_step_sort_order
                """
            )
            if ids
            else []
        )
        ingredients = (
            _rows(
                f"""
                SELECT recipe_id,
                  recipe_ingredient_customer_facing_description AS description,
                  recipe_ingredient_customer_facing_amount AS amount,
                  recipe_ingredient_customer_facing_unit AS unit
                FROM `{LEGACY_DATASET}.legacy_recipe_ingredients`
                WHERE recipe_id IN ({", ".join(ids)})
                QUALIFY recipe_version_number
                  = MAX(recipe_version_number) OVER (PARTITION BY recipe_id)
                ORDER BY recipe_id, recipe_ingredient_id
                """
            )
            if ids
            else []
        )
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    from .config import today_iso

    today = today_iso()
    recipes, missing = [], []
    for row in identity:
        sku = row["recipe_sku"]
        if not row.get("product_name") and row.get("recipe_id") is None:
            missing.append(sku)
            continue
        recipe_id = row.get("recipe_id")
        runs = [s for s in slots if s["recipe_id"] == recipe_id]
        if cycle:
            match = [s for s in runs if s["cycle_date"] == cycle]
            resolved, slot = cycle, (match[0]["slot"] if match else None)
            note = "" if match else f"not slotted in {cycle}"
        else:
            started = [s for s in runs if s["cycle_date"] <= today] or runs
            chosen = started[-1] if started else None
            resolved = chosen["cycle_date"] if chosen else None
            slot = chosen["slot"] if chosen else None
            note = "" if chosen else "no cycle assigned"
        product_steps = [
            {k: s[k] for k in ("step_number", "step_title", "instruction")}
            for s in steps
            if s["recipe_sku"] == sku
        ]
        fallback = [
            {k: s[k] for k in ("step_number", "step_title", "instruction")}
            for s in legacy_steps
            if s["recipe_id"] == recipe_id
        ]
        recipes.append(
            {
                "sku": sku,
                "recipe_id": recipe_id,
                "title": row.get("product_name") or row.get("recipe_title"),
                "subtitle": row.get("product_subtitle") or row.get("recipe_sub_title") or "",
                "customization": row.get("customization_description")
                or row.get("recipe_customization_variable")
                or "",
                "recipe_url": row.get("recipe_url") or "",
                "servings": row.get("servings"),
                "active_cook_time_min": row.get("active_cook_time"),
                "total_cook_time_min": row.get("total_cook_time"),
                "cycle": resolved,
                "slot": slot,
                "cycle_note": note,
                "all_cycles": [f"{s['cycle_date']} slot {s['slot']}" for s in runs],
                "step_source": "product" if product_steps else ("legacy" if fallback else "none"),
                "steps": product_steps or fallback,
                "ingredients": [
                    {k: i[k] for k in ("description", "amount", "unit")}
                    for i in ingredients
                    if i["recipe_id"] == recipe_id
                ],
            }
        )
    return {"status": "success", "recipes": recipes, "not_found": missing}


def find_recipes(cycle: str = "", name: str = "") -> dict[str, Any]:
    """List recipes in a menu cycle, or recipes whose title matches a name.

    Args:
        cycle: A menu cycle date (YYYY-MM-DD); lists every recipe slotted in it.
        name: Part of a recipe title or subtitle, used when no cycle is given.

    Returns:
        Up to 50 rows of sku, title, subtitle, cycle and slot, ordered by cycle and slot.
    """
    if cycle and not DATE_PATTERN.fullmatch(cycle):
        return {"status": "error", "message": "cycle must be YYYY-MM-DD."}
    term = re.sub(r"[^a-z0-9 &-]", "", name.lower()).strip()
    if not cycle and not term:
        return {"status": "error", "message": "Give a cycle or a name."}
    where = (
        f"s.cycle_date = DATE '{cycle}'"
        if cycle
        else (
            f"(LOWER(l.recipe_title) LIKE '%{term}%' OR LOWER(l.recipe_sub_title) LIKE '%{term}%')"
        )
    )
    result = run_readonly_query(
        f"""
        SELECT l.recipe_sku AS sku, l.recipe_title AS title, l.recipe_sub_title AS subtitle,
          s.cycle_date AS cycle, s.recipe_slot_short_code AS slot
        FROM `{LEGACY_DATASET}.legacy_cycle_recipe_slots` AS s
        JOIN `{LEGACY_DATASET}.legacy_recipes` AS l ON l.recipe_id = s.recipe_id
        WHERE l.recipe_archived_at IS NULL AND {where}
        ORDER BY s.cycle_date DESC, SAFE_CAST(s.recipe_slot_short_code AS INT64), l.recipe_sku
        LIMIT 50
        """,
        ALLOWED_DATASETS,
    )
    return result
