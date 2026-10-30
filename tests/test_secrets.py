"""Secrets are read from Secret Manager by name, never from the environment value."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gemini_shared import secrets as runtime_secrets


@pytest.fixture(autouse=True)
def fresh_cache():
    runtime_secrets.clear_secret_cache()
    yield
    runtime_secrets.clear_secret_cache()


def _client(monkeypatch, value="payload"):
    from google.cloud import secretmanager

    client = Mock()
    client.access_secret_version.return_value = SimpleNamespace(
        payload=SimpleNamespace(data=value.encode())
    )
    monkeypatch.setattr(secretmanager, "SecretManagerServiceClient", lambda: client)
    return client


def test_a_secret_id_resolves_in_the_runtime_project(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY_SECRET", "growth-fred-api-key")
    client = _client(monkeypatch)
    assert runtime_secrets.read_secret("FRED_API_KEY_SECRET") == "payload"
    name = client.access_secret_version.call_args.kwargs["name"]
    assert name == "projects/test-project/secrets/growth-fred-api-key/versions/latest"


def test_payloads_are_cached(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY_SECRET", "growth-fred-api-key")
    client = _client(monkeypatch)
    runtime_secrets.read_secret("FRED_API_KEY_SECRET")
    runtime_secrets.read_secret("FRED_API_KEY_SECRET")
    assert client.access_secret_version.call_count == 1


def test_a_local_value_short_circuits_secret_manager(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY_SECRET_VALUE", "local-only")
    client = _client(monkeypatch)
    assert runtime_secrets.read_secret("FRED_API_KEY_SECRET") == "local-only"
    client.access_secret_version.assert_not_called()


def test_an_unnamed_secret_is_an_error(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="FRED_API_KEY_SECRET"):
        runtime_secrets.read_secret("FRED_API_KEY_SECRET")


def test_optional_secret_degrades_without_leaking(monkeypatch, caplog):
    monkeypatch.delenv("NYT_API_KEY_SECRET", raising=False)
    assert runtime_secrets.optional_secret("NYT_API_KEY_SECRET") is None

    from google.cloud import secretmanager

    monkeypatch.setenv("NYT_API_KEY_SECRET", "growth-nyt-api-key")
    failing = Mock()
    failing.access_secret_version.side_effect = PermissionError("denied: s3cr3t-detail")
    monkeypatch.setattr(secretmanager, "SecretManagerServiceClient", lambda: failing)
    assert runtime_secrets.optional_secret("NYT_API_KEY_SECRET") is None
    assert "s3cr3t-detail" not in caplog.text
