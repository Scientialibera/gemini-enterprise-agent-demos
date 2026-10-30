"""Steps are packed onto pages by height, and every tip still appears once."""

from recipe_cards.rendering.content import cooking_tip_for_steps
from recipe_cards.rendering.steps import paginate_steps


def _steps(count, bullets=2):
    return [
        {"title": f"Step {i + 1}", "bullets": ["Stir the pot gently for a minute."] * bullets}
        for i in range(count)
    ]


def test_each_tip_appears_on_the_page_carrying_its_first_step():
    recipe = {"cooking_tip": ["About steps one to four.", "About steps five to eight."]}

    assert cooking_tip_for_steps(recipe, 0, 6) == (
        "About steps one to four. About steps five to eight."
    )
    assert cooking_tip_for_steps(recipe, 0, 4) == "About steps one to four."
    assert cooking_tip_for_steps(recipe, 4, 4) == "About steps five to eight."
    assert cooking_tip_for_steps(recipe, 2, 2) == ""


def test_a_plain_tip_appears_on_the_first_page_only():
    recipe = {"cooking_tip": "Keep the wok hot."}

    assert cooking_tip_for_steps(recipe, 0, 4) == "Keep the wok hot."
    assert cooking_tip_for_steps(recipe, 4, 2) == ""


def test_short_steps_are_never_stranded_one_to_a_page():
    recipe = {"steps": _steps(6), "variations": ["Add chili."]}

    _, pages = paginate_steps(recipe, recipe["steps"])

    assert sum(count for _, count in pages) == 6
    assert all(count != 1 for _, count in pages if count)


def test_every_step_is_placed_exactly_once_in_order():
    recipe = {"steps": _steps(11, bullets=4), "variations": ["Add chili."]}

    _, pages = paginate_steps(recipe, recipe["steps"])

    placed = [index for start, count in pages for index in range(start, start + count)]
    assert placed == list(range(11))
