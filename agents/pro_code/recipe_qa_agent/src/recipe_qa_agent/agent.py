"""Recipe QA: checks recipes for editorial consistency and emails the report.

Reads the recipe tables in BigQuery with read-only queries, runs ingredient,
cooking-logic and timing checks, shows the findings in chat, and on request
sends a designed PDF report and an Excel extract by email. Sending is confirmed
by the user in a card first.
"""

from __future__ import annotations

from demo_tools.instructions import environment_instruction
from demo_tools.models import FAST_CHAT
from gemini_shared import apply_runtime_model
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from .config import BOOTSTRAP
from .data import find_recipes, get_recipe_details
from .tools import prepare_recipe_qa_report, query_recipe_data, send_recipe_qa_email

root_agent = Agent(
    name="recipe_qa_agent",
    model=create_model(BOOTSTRAP),
    description=(
        "Checks recipes for ingredient usage, cooking logic and timing consistency against "
        "the recipe tables, and emails a PDF report with an Excel findings extract."
    ),
    instruction=environment_instruction,
    before_model_callback=apply_runtime_model,
    generate_content_config=FAST_CHAT,
    tools=[
        get_recipe_details,
        find_recipes,
        query_recipe_data,
        prepare_recipe_qa_report,
        FunctionTool(send_recipe_qa_email, require_confirmation=True),
    ],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
