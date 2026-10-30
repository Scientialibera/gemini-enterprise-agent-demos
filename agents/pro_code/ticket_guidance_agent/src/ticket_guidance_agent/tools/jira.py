"""Create, update and look up Jira tickets for the signed-in user.

Jira is called as a dedicated Atlassian service account whose API token lives
in Secret Manager and is read under this agent's own identity. Gemini
Enterprise does not reliably hold a per-user Atlassian token, so the person is
identified from their Google token instead: their email is resolved to an
Atlassian account and set as the ticket's reporter.

The service account can reach every ticket in the project, so these tools act
only on tickets the person may touch: one created in this chat session, or one
they reported. Ticket keys come from the model and are checked against Jira's
key format before they go into a request path.
"""

from __future__ import annotations

import functools
import logging
import re

import requests
from gemini_shared import current_user_credentials
from gemini_shared.secrets import read_secret
from google.adk.tools.tool_context import ToolContext

from ..config import (
    JIRA_ALLOWED_ISSUE_TYPES,
    JIRA_API_BASE_URL,
    JIRA_API_TOKEN_SECRET_ENV,
    JIRA_LABELS,
    JIRA_PARENT_ISSUE_KEY,
    JIRA_PROJECT_KEY,
    JIRA_SERVICE_ACCOUNT_EMAIL,
    JIRA_SITE_URL,
)

LOGGER = logging.getLogger(__name__)
# Takes the token in the Authorization header, so it never appears in a URL.
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REQUEST_TIMEOUT_SECONDS = 30
ISSUE_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")
# Session state: keys of the tickets created in this chat session.
SESSION_ISSUES_STATE_KEY = "ticket_guidance_issue_keys"


class JiraError(RuntimeError):
    """A Jira request failed; the message is safe to show the model."""


def _jira(method: str, path: str, **kwargs) -> dict | list:
    if not JIRA_API_BASE_URL or not JIRA_SERVICE_ACCOUNT_EMAIL:
        raise JiraError("JIRA_API_BASE_URL and JIRA_SERVICE_ACCOUNT_EMAIL must be configured.")
    response = requests.request(
        method,
        f"{JIRA_API_BASE_URL}/rest/api/2/{path.lstrip('/')}",
        auth=(JIRA_SERVICE_ACCOUNT_EMAIL, read_secret(JIRA_API_TOKEN_SECRET_ENV)),
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        **kwargs,
    )
    if not response.ok:
        raise JiraError(f"Jira {method} {path} failed with HTTP {response.status_code}.")
    return response.json() if response.content else {}


def _signed_in_email() -> str | None:
    """Email of the signed-in user, from their Google token."""
    response = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {current_user_credentials().token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return response.json().get("email") if response.ok else None


@functools.lru_cache(maxsize=512)
def _atlassian_account(email: str) -> dict | None:
    matches = _jira("GET", "user/search", params={"query": email})
    for account in matches if isinstance(matches, list) else []:
        if str(account.get("emailAddress", "")).lower() == email.lower() or len(matches) == 1:
            return {
                "accountId": account.get("accountId"),
                "displayName": account.get("displayName"),
                "emailAddress": email,
            }
    return None


def _current_user() -> dict | None:
    email = _signed_in_email()
    if not email:
        return None
    return _atlassian_account(email) or {
        "accountId": None,
        "displayName": email,
        "emailAddress": email,
    }


def _session_issues(tool_context: ToolContext) -> list[str]:
    return list(tool_context.state.get(SESSION_ISSUES_STATE_KEY) or [])


def _permitted_issue(issue_key: str, tool_context: ToolContext) -> tuple[str, dict]:
    """The checked key and the ticket's fields, if the signed-in user may act on it."""
    key = issue_key.strip().upper()
    if not ISSUE_KEY_PATTERN.fullmatch(key):
        raise JiraError(f"'{issue_key}' is not a Jira ticket key, e.g. AGENT-230.")
    fields = _jira("GET", f"issue/{key}", params={"fields": "status,reporter,summary"}).get(
        "fields", {}
    )
    if key in _session_issues(tool_context):
        return key, fields
    account_id = (_current_user() or {}).get("accountId")
    if not account_id:
        raise JiraError(
            "Your Atlassian account could not be identified, so only tickets created in "
            "this chat can be used."
        )
    if (fields.get("reporter") or {}).get("accountId") != account_id:
        raise JiraError("Access denied: this ticket was reported by a different user.")
    return key, fields


def _browse_link(issue_key: str) -> str:
    return f"{JIRA_SITE_URL}/browse/{issue_key}" if JIRA_SITE_URL else issue_key


def _issue_type(project_key: str, requested: str) -> str:
    try:
        meta = _jira("GET", f"issue/createmeta/{project_key}/issuetypes")
        available = [item["name"] for item in meta.get("issueTypes", meta.get("values", []))]
    except JiraError:
        available = []
    if requested in available:
        return requested
    for allowed in JIRA_ALLOWED_ISSUE_TYPES:
        if allowed in available:
            return allowed
    # A project without the service-desk types (e.g. a plain Jira project) still gets
    # a ticket rather than a failed request.
    if "Task" in available:
        return "Task"
    return requested


def create_jira_ticket_tool(
    summary: str, description: str, issue_type: str, tool_context: ToolContext
) -> dict:
    """Create a Jira ticket for the IT issue the signed-in user reported.

    Args:
        summary: A clear title inferred from the user's issue.
        description: The user's problem, environment details, the knowledge base
            URLs used (or that none was found) and every affected user.
        issue_type: Exactly "Service Request" or "Incident Request".
    """
    try:
        user = _current_user()
        final_description = description
        if not user or not user.get("accountId"):
            final_description += (
                "\n\nNote: the reporter could not be identified automatically. This ticket "
                "was created by the AI agent; please set the reporter manually."
            )
            if user:
                final_description += f" Requested by: {user['emailAddress']}."
        fields: dict[str, object] = {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
            "description": final_description,
            "issuetype": {"name": _issue_type(JIRA_PROJECT_KEY, issue_type)},
            "labels": list(JIRA_LABELS),
        }
        if JIRA_PARENT_ISSUE_KEY:
            fields["parent"] = {"key": JIRA_PARENT_ISSUE_KEY}
        if user and user.get("accountId"):
            fields["reporter"] = {"accountId": user["accountId"]}
        created = _jira("POST", "issue", json={"fields": fields})
        key = created["key"]
        # Reassign rather than mutate, so ADK records the change in the session.
        tool_context.state[SESSION_ISSUES_STATE_KEY] = [*_session_issues(tool_context), key]
        LOGGER.info("Jira ticket created: %s reporter_resolved=%s", key, bool(user))
        return {
            "status": "Success",
            "issue_key": key,
            "link": _browse_link(key),
            "reporter": (user or {}).get("displayName") or "not identified",
        }
    except (JiraError, KeyError) as exc:
        return {"status": "Error", "message": str(exc)}


def update_jira_ticket_tool(
    issue_key: str,
    tool_context: ToolContext,
    new_status: str | None = None,
    updated_description: str | None = None,
) -> dict:
    """Update the status and/or description of this session's Jira ticket.

    Args:
        issue_key: The ticket key, e.g. AGENT-230.
        new_status: Target status name, e.g. "DONE" or "IN PROGRESS".
        updated_description: Full conversation summary to store as the description.
    """
    try:
        issue_key, _ = _permitted_issue(issue_key, tool_context)
        results: dict[str, object] = {}
        if updated_description is not None:
            user = _current_user()
            if user:
                updated_description += (
                    f"\n\nUpdated by: {user['displayName']} ({user['emailAddress']})"
                )
            _jira(
                "PUT", f"issue/{issue_key}", json={"fields": {"description": updated_description}}
            )
            results["description_updated"] = True
        if new_status is not None:
            transitions = _jira("GET", f"issue/{issue_key}/transitions").get("transitions", [])
            match = next(
                (t for t in transitions if t["to"]["name"].lower() == new_status.lower()), None
            )
            if match:
                _jira(
                    "POST",
                    f"issue/{issue_key}/transitions",
                    json={"transition": {"id": match["id"]}},
                )
                results["status_transitioned_to"] = new_status
            else:
                results["status_transition_warning"] = (
                    f"Status '{new_status}' not available. "
                    f"Available: {[t['to']['name'] for t in transitions]}"
                )
        return {"status": "Success", **results}
    except (JiraError, KeyError) as exc:
        return {"status": "Error", "message": str(exc)}


def get_jira_ticket_status_tool(issue_key: str, tool_context: ToolContext) -> dict:
    """Look up the status of a Jira ticket the signed-in user reported.

    Answers only for tickets created in this session or reported by the signed-in user.

    Args:
        issue_key: The ticket key, e.g. AGENT-230.
    """
    try:
        issue_key, fields = _permitted_issue(issue_key, tool_context)
        reporter = fields.get("reporter") or {}
        return {
            "status": "Success",
            "issue_key": issue_key,
            "current_status": fields.get("status", {}).get("name"),
            "reporter_display_name": reporter.get("displayName"),
            "summary": fields.get("summary"),
            "link": _browse_link(issue_key),
        }
    except (JiraError, KeyError) as exc:
        return {"status": "Error", "message": str(exc)}
