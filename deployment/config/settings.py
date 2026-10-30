"""Environment loading and the deployment boundary for dev, qa and prod."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from gemini_shared.config.bootstrap import (
    AUTHORIZATION_ID_ENV,
    CONFIG_PARAMETER_ENV,
    LOCATION_ENV,
    PROJECT_ENV,
)
from paths import DEV_DIR

from .environment import configured_value, env_bool

if TYPE_CHECKING:
    from registry import AgentSpec

GCS_URI_PREFIX = "gs://"

ENVIRONMENTS = ("dev", "qa", "prod")
# Shared environments: a deploy names its target project explicitly, and the
# sandbox conveniences below are refused there.
SHARED_ENVIRONMENTS = ("qa", "prod")
CONFIRM_PROJECT_ENV = "DEPLOY_CONFIRM_PROJECT"
# Settings for a personal sandbox only. In a shared environment Terraform owns
# the project and its IAM, the data is real, and tests must not write to Jira.
SANDBOX_ONLY = {
    "DEV_CREATE_PROJECT_IF_MISSING": "environment.create_project.enabled",
    "DEV_GRANT_AGENT_IDENTITY_BASELINE": "environment.grant_agent_identity_baseline",
    "DEV_SEED_SAMPLE_DATA": "seed.bigquery.sample_data",
    "SEED_DRIVE": "seed.drive.enabled",
    "SEED_ATLASSIAN": "seed.atlassian.enabled",
    "TEST_TICKET_GUIDANCE_CREATES_TICKETS": "tests.ticket_guidance_creates_tickets",
}

STAGING_BUCKET_ENV = "DEV_STAGING_BUCKET"

ENVIRONMENT_ENV = "ENVIRONMENT"

COMMON_REQUIRED_REMOTE_ENV = (
    PROJECT_ENV,
    LOCATION_ENV,
    STAGING_BUCKET_ENV,
)

RUNTIME_ENV_KEYS = (
    CONFIG_PARAMETER_ENV,
    "CONFIG_PARAMETER_LOCATION",
    "CONFIG_REFRESH_SECONDS",
    "BOOTSTRAP_MODEL",
    "GEMINI_MODEL_LOCATION",
    AUTHORIZATION_ID_ENV,
)

PLACEHOLDER = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")


def load_environment(filename: str) -> None:
    """Load deployment settings: the shell, then config.yaml, then the env file.

    Each source only fills what the ones before it left unset. ``.env.dev`` is
    still read for a one-off override; ``.env.local`` serves local runs.
    """
    if filename == ".env.dev":
        from .main_config import load_main_config

        load_main_config()
    path = DEV_DIR / filename
    if path.exists():
        load_dotenv(path, override=False)


def is_missing_or_placeholder(name: str) -> bool:
    return not configured_value(name)


def current_environment() -> str:
    return os.getenv(ENVIRONMENT_ENV, "").strip().lower()


def _require_shared_environment_guards(environment: str, project_id: str) -> None:
    """In qa and prod, the target project must be confirmed and sandbox settings off."""
    confirmed = os.getenv(CONFIRM_PROJECT_ENV, "").strip()
    if confirmed != project_id:
        raise SystemExit(
            f"Refusing to deploy to the shared '{environment}' environment without "
            f"confirmation. Rerun with --confirm-project {project_id} "
            f"(or set {CONFIRM_PROJECT_ENV}={project_id})."
        )
    enabled = [path for name, path in SANDBOX_ONLY.items() if env_bool(name, False)]
    if enabled:
        raise SystemExit(
            f"'{environment}' is a shared environment; turn these sandbox-only settings off "
            f"in its config file: {', '.join(enabled)}. Terraform owns its project, IAM "
            "and data (docs/prod-runbook.md)."
        )


def require_deploy_environment(
    *,
    require_parameter: bool = True,
    spec: AgentSpec | None = None,
) -> tuple[str, str, str]:
    environment = current_environment()
    if environment not in ENVIRONMENTS:
        raise SystemExit(
            f"Refusing remote deployment: {ENVIRONMENT_ENV} (environment.name) must be one "
            f"of {', '.join(ENVIRONMENTS)}, not {environment or 'empty'!r}."
        )

    # Resolve per-agent defaults before building the runtime environment.
    if spec is not None:
        if require_parameter and is_missing_or_placeholder(CONFIG_PARAMETER_ENV):
            os.environ[CONFIG_PARAMETER_ENV] = spec.config_parameter_id
        if AUTHORIZATION_ID_ENV in spec.required_remote_bootstrap_env and (
            is_missing_or_placeholder(AUTHORIZATION_ID_ENV)
        ):
            os.environ[AUTHORIZATION_ID_ENV] = spec.authorization_id

    required = list(COMMON_REQUIRED_REMOTE_ENV)
    if require_parameter:
        required.append(CONFIG_PARAMETER_ENV)
    missing = [name for name in required if is_missing_or_placeholder(name)]
    if missing:
        raise SystemExit(
            f"Missing required settings: {', '.join(missing)}. Fill them in deployment/config.yaml."
        )

    project_id = os.environ[PROJECT_ENV].strip()
    if environment in SHARED_ENVIRONMENTS:
        _require_shared_environment_guards(environment, project_id)
    location = os.environ[LOCATION_ENV].strip()
    staging_bucket = os.environ[STAGING_BUCKET_ENV].strip()
    if not staging_bucket.startswith(GCS_URI_PREFIX):
        raise SystemExit(f"{STAGING_BUCKET_ENV} must be a {GCS_URI_PREFIX} bucket URI.")
    return project_id, location, staging_bucket


def validate_agent_remote_environment(spec: AgentSpec) -> None:
    missing = [
        name for name in spec.required_remote_bootstrap_env if is_missing_or_placeholder(name)
    ]
    if missing:
        raise SystemExit(
            f"{spec.package_name} requires additional bootstrap settings: {', '.join(missing)}."
        )


def resolve_declared_env(declared: tuple[tuple[str, str], ...]) -> dict[str, str]:
    """Substitute ${NAME} values from the environment, dropping any left empty.

    A spec names an environment's Drive folder or Jira site this way instead of
    committing it. An empty value is omitted rather than baked in, so the agent
    sees the setting as absent and reports it, not an empty string.
    """
    resolved: dict[str, str] = {}
    for key, value in declared:
        match = PLACEHOLDER.fullmatch(value)
        if match:
            value = configured_value(match.group(1))
        if value:
            resolved[key] = value
    return resolved


def unresolved_declared_env(spec: AgentSpec) -> tuple[str, ...]:
    """Environment variables a spec refers to that are not set, for a preflight warning."""
    names = (PLACEHOLDER.fullmatch(value) for _, value in spec.runtime_env)
    return tuple(m.group(1) for m in names if m and not configured_value(m.group(1)))


def runtime_env(spec: AgentSpec | None = None) -> dict[str, str]:
    """Environment baked into one runtime: the agent's own settings, then the shell.

    RUNTIME_ENV_KEYS is a shared forwarding list, so a value set for one agent
    reaches whichever agent is released next. A spec's own ``runtime_env`` is
    scoped to that entry. The environment is applied last so a single run can
    still override a declared value.
    """
    # require_deploy_environment must resolve per-agent defaults first.
    declared = resolve_declared_env(spec.runtime_env) if spec else {}
    forwarded = {
        key: os.environ[key] for key in RUNTIME_ENV_KEYS if not is_missing_or_placeholder(key)
    }
    return declared | forwarded
