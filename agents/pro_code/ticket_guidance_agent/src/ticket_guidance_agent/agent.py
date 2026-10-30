"""IT service desk guidance: one issue per session, grounded in the Confluence KB.

Searches the knowledge base as the signed-in user, answers only from what it
finds, opens a Jira ticket in the background and moves it to done or in
progress once the user says whether the guidance worked.
"""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP
from .tools import TICKET_GUIDANCE_TOOLS

root_agent = Agent(
    name="ticket_guidance_agent",
    model=create_model(BOOTSTRAP),
    description=(
        "IT Service Desk Ticket Guidance Agent. Searches the Confluence knowledge base, "
        "gives strictly KB-grounded guidance, creates a background Jira ticket and tracks "
        "its resolution within a single chat session."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=TICKET_GUIDANCE_TOOLS,
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
