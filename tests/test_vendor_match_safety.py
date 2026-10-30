"""Vendor Match keeps staged batches in one process for every user; keys must not cross users."""

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def orchestration(monkeypatch):
    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")
    module = importlib.import_module("vendor_match_agent.tools.orchestration_tools")
    monkeypatch.setattr(module, "load_staged_payload_from_drive", lambda key, folder: None)
    monkeypatch.setattr(module, "_STAGED_RESOLUTION_CACHE", {})
    return module


def _context(user, session="abcdef123456"):
    return SimpleNamespace(user_id=f"{user}@example.com", session_id=session)


def test_the_key_combines_the_short_session_id_and_the_user(orchestration):
    assert orchestration._session_cache_key(_context("ana")) == "abcdef12_ana"


def test_a_key_naming_another_user_is_ignored(orchestration):
    orchestration._STAGED_RESOLUTION_CACHE["zzzzzzzz_bob"] = {"manifest": {"owner": "bob"}}

    key, staged = orchestration._resolve_session_state(_context("ana"), "zzzzzzzz_bob")

    assert key == "abcdef12_ana"
    assert staged is None


def test_a_user_can_resume_their_own_other_session(orchestration):
    orchestration._STAGED_RESOLUTION_CACHE["99999999_ana"] = {"manifest": {"owner": "ana"}}

    key, staged = orchestration._resolve_session_state(_context("ana"), "99999999_ana")

    assert key == "99999999_ana"
    assert staged == {"manifest": {"owner": "ana"}}


def test_drive_query_literals_survive_quotes(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")
    drive = importlib.import_module("vendor_match_agent.tools.drive_tools")
    assert drive._literal("Joe's vendors.xlsx") == r"'Joe\'s vendors.xlsx'"
    assert drive._literal("x' or name contains '") == r"'x\' or name contains \''"
