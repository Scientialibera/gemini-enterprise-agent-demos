"""Vendor master-data governance: standardize vendor names against a master dictionary.

The orchestrator ingests vendor lists from chat attachments or a Shared Drive
folder, resolves them in chunks (dictionary lookup, then a parallel LLM
resolver), stages a review workbook in Drive and commits the approved
mappings. Every Drive call runs as the signed-in user.
"""

from __future__ import annotations

import logging

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP, MISSING_DRIVE_FOLDERS
from .tools import VENDOR_MATCH_TOOLS

if MISSING_DRIVE_FOLDERS:
    logging.getLogger(__name__).warning(
        "Drive folders not configured: %s. Batch runs from Drive will fail; "
        "chat attachments still work.",
        ", ".join(MISSING_DRIVE_FOLDERS),
    )

root_agent = Agent(
    name="vendor_master_data_governor",
    model=create_model(BOOTSTRAP),
    description=(
        "Standardizes vendor names against the master vendor dictionary in Google Drive, "
        "with a reviewed approval step before any change is committed."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=VENDOR_MATCH_TOOLS,
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
