"""Seed Secret Manager: every secret the agents read exists, with a value where one is given.

The main config's ``secrets`` section names each secret and, optionally, an
environment variable holding its first value (``from_env``). A secret that
already has a version is left alone, so rotating a value in Secret Manager is
never undone by a rerun. Values are never printed.
"""

from __future__ import annotations

import os

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import secretmanager
from registry import AGENTS


def declared_secret_ids() -> tuple[str, ...]:
    """Every secret an agent's identity is granted, so none can be forgotten."""
    return tuple(
        dict.fromkeys(
            grant.secret for spec in AGENTS.values() for grant in spec.agent_identity_secret_roles
        )
    )


def _has_version(client: secretmanager.SecretManagerServiceClient, name: str) -> bool:
    versions = client.list_secret_versions(
        request={"parent": name, "filter": "state:ENABLED", "page_size": 1}
    )
    return any(True for _ in versions)


def seed_secrets(project_id: str, configured: dict[str, dict[str, str]]) -> list[str]:
    """Ensure each secret exists; return the ones still without a value."""
    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{project_id}"
    empty = []
    for secret_id in dict.fromkeys([*declared_secret_ids(), *configured]):
        name = f"{parent}/secrets/{secret_id}"
        try:
            client.create_secret(
                parent=parent,
                secret_id=secret_id,
                secret={"replication": {"automatic": {}}},
            )
            print(f"SECRET_CREATED={secret_id}")
        except AlreadyExists:
            pass
        try:
            if _has_version(client, name):
                continue
        except NotFound:
            pass
        source = (configured.get(secret_id) or {}).get("from_env", "")
        value = os.getenv(source, "").strip() if source else ""
        if not value:
            empty.append(secret_id)
            continue
        client.add_secret_version(parent=name, payload={"data": value.encode("utf-8")})
        del value
        print(f"SECRET_VERSION_ADDED={secret_id} (from ${source})")
    for secret_id in empty:
        print(
            f"ACTION_REQUIRED=secret {secret_id} has no value. Add one with: "
            f"gcloud secrets versions add {secret_id} --data-file=- "
            "(paste the value, then Ctrl+Z Enter on Windows or Ctrl+D)."
        )
    return empty
