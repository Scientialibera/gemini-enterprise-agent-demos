"""Kitchen Sequencer: answers kitchen compliance questions from curated BigQuery tables.

Ranks kitchens on a 100-point compliance score, breaks a score down into the
pillars and operational drivers behind it, and turns the analysis into a pre-shift
huddle plan. Reads the tables as its own Agent Identity with read-only queries.
"""

from __future__ import annotations

import os
from typing import Any

from demo_tools.bigquery import run_readonly_query
from demo_tools.instructions import environment_instruction
from demo_tools.models import FAST_CHAT
from gemini_shared import apply_runtime_model, get_bootstrap_settings
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

BOOTSTRAP = get_bootstrap_settings()
DATASET = os.getenv("KITCHEN_COMPLIANCE_DATASET", "kitchen_compliance").strip()
# Exported for the instruction's ${KITCHEN_DATASET_PATH} placeholder.
os.environ.setdefault("KITCHEN_DATASET_PATH", f"{BOOTSTRAP.project_id}.{DATASET}")


def query_kitchen_compliance(sql: str) -> dict[str, Any]:
    """Run one read-only BigQuery SELECT against the kitchen compliance tables.

    Args:
        sql: A single SELECT statement. Wrap every table path in backticks.

    Returns:
        status, row_count, truncated and rows, or status "error" with a message to
        read and fix before retrying once.
    """
    return run_readonly_query(sql, (os.environ["KITCHEN_DATASET_PATH"],))


root_agent = Agent(
    name="kitchen_sequencer",
    model=create_model(BOOTSTRAP),
    description=(
        "Ranks kitchens on compliance, explains what is driving a score and turns it into a "
        "pre-shift huddle plan, from the kitchen compliance tables."
    ),
    instruction=environment_instruction,
    before_model_callback=apply_runtime_model,
    generate_content_config=FAST_CHAT,
    tools=[query_kitchen_compliance],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
