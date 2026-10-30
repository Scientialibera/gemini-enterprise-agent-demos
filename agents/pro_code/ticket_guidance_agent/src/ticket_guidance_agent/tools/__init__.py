"""Ticket Guidance tools, each run with the signed-in user's Google token bound."""

from gemini_shared import with_user_credentials

from ..config import GEMINI_ENTERPRISE_AUTHORIZATION_ID
from .confluence_search import search_confluence_kb_tool
from .jira import create_jira_ticket_tool, get_jira_ticket_status_tool, update_jira_ticket_tool

_as_user = with_user_credentials(GEMINI_ENTERPRISE_AUTHORIZATION_ID)

TICKET_GUIDANCE_TOOLS = [
    _as_user(search_confluence_kb_tool),
    _as_user(create_jira_ticket_tool),
    _as_user(update_jira_ticket_tool),
    _as_user(get_jira_ticket_status_tool),
]

__all__ = ["TICKET_GUIDANCE_TOOLS"]
