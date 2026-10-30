"""Tools act as the signed-in user, and only for the duration of one call."""

from __future__ import annotations

import asyncio
import inspect
import secrets
from types import SimpleNamespace

import pytest
from gemini_shared import current_user_credentials, with_user_credentials
from gemini_shared.auth.workspace import MissingUserAuthorization
from google.adk.tools.function_tool import FunctionTool

AUTHORIZATION = "unit-test-authorization"


def _context(token: str | None) -> SimpleNamespace:
    return SimpleNamespace(state={AUTHORIZATION: token} if token else {})


def list_files(folder_id: str) -> dict:
    """List the files in a Drive folder.

    Args:
        folder_id: The folder to list.
    """
    return {"folder": folder_id, "token": current_user_credentials().token}


async def search(query: str, tool_context=None) -> dict:
    """Search as the user."""
    return {"query": query, "token": current_user_credentials().token, "ctx": tool_context}


def test_the_users_token_is_bound_for_the_call_only():
    tool = with_user_credentials(AUTHORIZATION)(list_files)
    token = secrets.token_urlsafe(16)
    result = asyncio.run(tool("folder-1", tool_context=_context(token)))
    assert result == {"folder": "folder-1", "token": token}
    with pytest.raises(MissingUserAuthorization):
        current_user_credentials()


def test_a_tool_that_wants_its_context_still_receives_it():
    tool = with_user_credentials(AUTHORIZATION)(search)
    context = _context("token")
    assert asyncio.run(tool("vpn", tool_context=context))["ctx"] is context


def test_a_missing_authorization_is_reported_to_the_model_not_raised():
    tool = with_user_credentials(AUTHORIZATION)(list_files)
    result = asyncio.run(tool("folder-1", tool_context=_context(None)))
    assert result["status"] == "error"
    assert AUTHORIZATION in result["message"]


def test_another_agents_token_is_never_used():
    tool = with_user_credentials(AUTHORIZATION)(list_files)
    context = SimpleNamespace(state={"some-other-authz": "not-yours"})
    assert asyncio.run(tool("folder-1", tool_context=context))["status"] == "error"


def test_the_model_sees_the_original_declaration():
    """ADK must still describe the tool by its own name, docstring and arguments."""
    tool = with_user_credentials(AUTHORIZATION)(list_files)
    assert "tool_context" in inspect.signature(tool).parameters
    declaration = FunctionTool(tool)._get_declaration()
    assert declaration.name == "list_files"
    assert declaration.description.startswith("List the files")
    schema = str(declaration.parameters_json_schema or declaration.parameters)
    assert "folder_id" in schema
    assert "tool_context" not in schema


def test_adk_runs_the_wrapped_tool_with_the_session_token():
    """End to end through FunctionTool, which supplies tool_context itself."""
    tool = FunctionTool(with_user_credentials(AUTHORIZATION)(list_files))
    token = secrets.token_urlsafe(16)
    context = SimpleNamespace(state={AUTHORIZATION: token}, function_call_id="1")
    result = asyncio.run(tool.run_async(args={"folder_id": "f"}, tool_context=context))
    assert result == {"folder": "f", "token": token}
