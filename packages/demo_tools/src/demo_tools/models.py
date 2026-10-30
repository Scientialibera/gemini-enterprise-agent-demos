"""Model call settings shared by the chat agents.

The default thinking depth makes every turn of a chat agent take half a minute or
more. These agents follow tested query templates, so a low thinking level keeps
answers accurate and the conversation fast enough to use live. Thought summaries
are included so Gemini Enterprise can show the agent's reasoning as it works.
"""

from __future__ import annotations

from google.genai import types

FAST_CHAT = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(
        thinking_level=types.ThinkingLevel.LOW,
        include_thoughts=True,
    ),
)
