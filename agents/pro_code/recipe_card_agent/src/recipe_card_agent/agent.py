"""Agent that turns a dish into a finished, illustrated recipe card deck.

Tools browse stored cards, generate images and publish the fixed card template.
Storage calls use the agent's own Cloud Storage bucket under its Agent Identity.
The model runs inside ProgressAgent, which posts each step and each finished
image to the chat while the image calls are still working.
"""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP
from .progress import ProgressAgent
from .tools import (
    check_recipe,
    generate_recipe_images,
    list_folders,
    render_recipe_card,
    retrieve,
)

card_writer = Agent(
    name="recipe_card_writer",
    model=create_model(BOOTSTRAP),
    description=(
        "Produces print-ready recipe cards for a pantry business: writes the recipe, "
        "generates consistent food photography, and publishes an editable PowerPoint "
        "deck to Cloud Storage."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        list_folders,
        retrieve,
        check_recipe,
        generate_recipe_images,
        render_recipe_card,
    ],
    disallow_transfer_to_parent=True,
)

root_agent = ProgressAgent(
    name="recipe_card_agent",
    description=card_writer.description,
    sub_agents=[card_writer],
)

# Agent Runtime serves the AdkApp wrapper, not a bare Agent.
app = create_app(root_agent, BOOTSTRAP)
