"""Instructions that name environment-specific resources without hard-coding them.

A prompt.md is published to Parameter Manager as written, so it cannot carry one
environment's dataset names. It writes ``${NAME}`` instead, and this resolves
each placeholder from the runtime's environment when the model is called.
"""

from __future__ import annotations

import os
import re

from gemini_shared import get_runtime_config
from google.adk.agents.readonly_context import ReadonlyContext

PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def fill_placeholders(text: str) -> str:
    """Replace ${NAME} with the environment value; leave unknown names visible."""
    return PLACEHOLDER.sub(lambda match: os.getenv(match.group(1), match.group(0)), text)


def environment_instruction(readonly_context: ReadonlyContext) -> str:
    """The live instruction with its ${NAME} placeholders filled in."""
    del readonly_context
    return fill_placeholders(get_runtime_config().instruction)
