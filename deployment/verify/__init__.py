"""End-to-end checks against a deployed environment, one per agent.

Code agents are exercised as Gemini Enterprise would run them: a session on the
deployed runtime with the caller's Google token in state, so their tools act as
that person. No-code agents have no runtime to call; their checks confirm the
published definition carries its connector and that the BigQuery MCP server
answers the queries their prompts rely on.

Some checks touch real systems and are controlled by config.yaml (``tests``):
the Growth run writes a Doc, and the Ticket Guidance run creates a ticket and
moves it to Done.
"""
