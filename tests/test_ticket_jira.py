"""Ticket Guidance acts on Jira as a service account, so it limits itself to the user's tickets."""

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def jira(monkeypatch):
    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")
    module = importlib.import_module("ticket_guidance_agent.tools.jira")
    calls = []

    def fake_jira(method, path, **kwargs):
        calls.append((method, path))
        if method == "GET" and path.startswith("issue/") and path.count("/") == 1:
            reporter = "someone-else" if path == "issue/AGENT-9" else "me"
            return {"fields": {"reporter": {"accountId": reporter}, "status": {"name": "Open"}}}
        if path.endswith("/transitions") and method == "GET":
            return {"transitions": [{"id": "31", "to": {"name": "Done"}}]}
        if method == "POST" and path == "issue":
            return {"key": "AGENT-12"}
        return {}

    monkeypatch.setattr(module, "_jira", fake_jira)
    monkeypatch.setattr(module, "_issue_type", lambda project, requested: requested)
    monkeypatch.setattr(
        module,
        "_current_user",
        lambda: {"accountId": "me", "displayName": "Me", "emailAddress": "me@example.com"},
    )
    module.calls = calls
    return module


def _context(issues=()):
    return SimpleNamespace(state={"ticket_guidance_issue_keys": list(issues)})


@pytest.mark.parametrize(
    "key", ["AGENT-1/../../user/search", "AGENT-1?x=1", "../myself", "1-AGENT"]
)
def test_a_malformed_key_never_reaches_jira(jira, key):
    result = jira.get_jira_ticket_status_tool(key, _context())
    assert result["status"] == "Error"
    assert jira.calls == []


def test_another_users_ticket_cannot_be_updated(jira):
    result = jira.update_jira_ticket_tool("AGENT-9", _context(), new_status="Done")
    assert result["status"] == "Error"
    assert "different user" in result["message"]
    assert not any(method in {"PUT", "POST"} for method, _ in jira.calls)


def test_the_users_own_ticket_can_be_updated(jira):
    result = jira.update_jira_ticket_tool("agent-5", _context(), new_status="done")
    assert result == {"status": "Success", "status_transitioned_to": "done"}
    assert ("POST", "issue/AGENT-5/transitions") in jira.calls


def test_a_ticket_created_in_this_session_is_usable_without_a_matching_reporter(jira, monkeypatch):
    """If the reporter could not be set, the session that created the ticket still owns it."""
    monkeypatch.setattr(jira, "_current_user", lambda: None)
    context = _context()
    created = jira.create_jira_ticket_tool("Printer", "It jams", "Service Request", context)
    assert created["issue_key"] == "AGENT-12"
    assert context.state["ticket_guidance_issue_keys"] == ["AGENT-12"]

    result = jira.update_jira_ticket_tool("AGENT-12", context, updated_description="Fixed")
    assert result["status"] == "Success"
    assert jira.get_jira_ticket_status_tool("AGENT-9", context)["status"] == "Error"


def test_issue_type_falls_back_to_one_the_project_has(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")
    module = importlib.import_module("ticket_guidance_agent.tools.jira")

    def types(*names):
        return lambda method, path, **kwargs: {"issueTypes": [{"name": n} for n in names]}

    monkeypatch.setattr(module, "_jira", types("Task", "Service Request"))
    assert module._issue_type("KAN", "Incident Request") == "Service Request"
    monkeypatch.setattr(module, "_jira", types("Task", "Bug"))
    assert module._issue_type("KAN", "Incident Request") == "Task"


def test_confluence_api_query_is_scoped_to_the_space_and_safe(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")
    search = importlib.import_module("ticket_guidance_agent.tools.confluence_search")
    monkeypatch.setattr(search, "CONFLUENCE_SPACE", "ETSDKB")

    cql = search._cql('My VPN says "auth failed") OR space = "HR')
    assert cql.startswith('space = "ETSDKB" AND type in (page, blogpost) AND (')
    assert 'text ~ "vpn"' in cql and 'text ~ "failed"' in cql
    # Quotes and operators in the user's text cannot reach the query as syntax.
    assert cql.count('space = "') == 1


def test_confluence_backend_is_chosen_by_setting(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")
    search = importlib.import_module("ticket_guidance_agent.tools.confluence_search")
    monkeypatch.setattr(
        search, "_api_articles", lambda q: [("VPN", "https://x/wiki/v", "<b>x</b>")]
    )
    monkeypatch.setattr(search, "_connector_articles", lambda q: [])

    monkeypatch.setattr(search, "CONFLUENCE_SEARCH_BACKEND", "api")
    assert search.search_confluence_kb_tool("vpn")["articles"][0]["content_snippet"] == "x"
    monkeypatch.setattr(search, "CONFLUENCE_SEARCH_BACKEND", "connector")
    assert search.search_confluence_kb_tool("vpn")["total_results"] == 0
