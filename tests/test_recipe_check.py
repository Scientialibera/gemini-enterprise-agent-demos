"""The recipe is checked, and its image list made, before any image is generated."""

import json
from copy import deepcopy

from recipe_cards.check import check_recipe

RECIPE = {
    "title": "Shrimp Pad Thai",
    "slug": "shrimp-pad-thai",
    "subtitle": "Tamarind rice noodles",
    "card_title": "Street-Food Classic",
    "description": "Chewy rice noodles in a sweet-tangy tamarind sauce.",
    "ingredients": [
        {"quantity": "8 oz", "item": "Large shrimp"},
        {"quantity": "8 oz", "item": "Rice noodles"},
        {"quantity": "4 oz", "item": "Firm tofu"},
    ],
    "steps": [
        {"title": "Soak the noodles", "body": "Soak in warm water for 25 minutes."},
        {"title": "Sear the shrimp", "body": "Sear the shrimp for 2 minutes."},
    ],
    "cooking_tip": ["Keep the wok hot."],
    "customizations": [
        {
            "name": "Chicken",
            "replaces": ["Large shrimp"],
            "ingredients": [{"quantity": "8 oz", "item": "Sliced chicken"}],
            "steps": [{"step": 2, "instructions": ["Sear the chicken for 4 minutes."]}],
        },
        {
            "name": "Crispy Tofu",
            "replaces": ["Large shrimp"],
            "ingredients": [{"quantity": "8 oz", "item": "Firm tofu"}],
            "steps": [{"step": 2, "instructions": ["Sear the tofu until crisp."]}],
        },
    ],
    "bottom_banner_text": "Fresh Pantry Kits\nAuthentic Flavors",
}


def _check(recipe):
    return check_recipe(json.dumps(recipe))


def test_a_good_recipe_lists_every_image_once():
    result = _check(RECIPE)

    assert result["status"] == "ready"
    assert result["photographs"] == ["hero", "step-1", "step-2"]
    names = [image["name"] for image in result["ingredient_images"]]
    # The customization's chicken is listed; its tofu duplicates the core tofu.
    assert names == [
        "ingredient-large-shrimp",
        "ingredient-rice-noodles",
        "ingredient-firm-tofu",
        "ingredient-sliced-chicken",
    ]


def test_legacy_variations_are_sent_back_for_customizations():
    recipe = deepcopy(RECIPE)
    del recipe["customizations"]
    recipe["variations"] = ["Spicy: add chili."]

    result = _check(recipe)

    assert result["status"] == "needs_correction"
    assert [p["field"] for p in result["problems"]] == ["customizations"]
    assert "legacy" in result["problems"][0]["problem"]


def test_every_over_long_field_is_reported_at_once():
    recipe = deepcopy(RECIPE)
    recipe["subtitle"] = "x" * 45
    recipe["description"] = "y" * 210
    recipe["bottom_banner_text"] = "One line only • with a separator"

    fields = [p["field"] for p in _check(recipe)["problems"]]

    assert fields == ["subtitle", "description", "bottom_banner_text"]


def test_the_tip_count_follows_the_steps():
    recipe = deepcopy(RECIPE)
    recipe["cooking_tip"] = ["One.", "Two."]

    assert [p["field"] for p in _check(recipe)["problems"]] == ["cooking_tip"]


def test_an_invalid_payload_is_a_correction_not_a_crash():
    result = check_recipe("not json")

    assert result["status"] == "needs_correction"
