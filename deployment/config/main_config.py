"""The main deployment configuration: deployment/config.yaml.

One YAML file describes an environment: the project and app, each agent's
settings, what to seed and what the end-to-end tests may touch. The deployment
code reads environment variables, so this module validates the file against a
fixed schema and exports it as those variables. An unknown key is an error
rather than a silently ignored setting, and a variable already set in the
shell wins, so CI can override one value without editing the file.

No secret values belong in the file. OAuth clients point at the JSON file the
console downloads; API keys and tokens live in Secret Manager (see ``secrets``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from paths import DEV_DIR

MAIN_CONFIG_ENV = "DEPLOYMENT_CONFIG"
DEFAULT_MAIN_CONFIG = DEV_DIR / "config.yaml"


@dataclass(frozen=True, slots=True)
class Setting:
    path: str  # dotted YAML path
    env: str  # environment variable the deployment code reads
    description: str


SETTINGS: tuple[Setting, ...] = (
    # Environment
    Setting(
        "environment.name", "ENVIRONMENT", "dev, qa or prod; qa and prod need --confirm-project."
    ),
    Setting("environment.project_id", "GOOGLE_CLOUD_PROJECT", "Google Cloud project ID."),
    Setting("environment.region", "GOOGLE_CLOUD_LOCATION", "Agent Engine region."),
    Setting("environment.staging_bucket", "DEV_STAGING_BUCKET", "gs:// bucket for packages."),
    Setting(
        "environment.staging_bucket_location",
        "DEV_STAGING_BUCKET_LOCATION",
        "Location for a new staging bucket; defaults to the region.",
    ),
    Setting(
        "environment.create_staging_bucket",
        "DEV_CREATE_STAGING_BUCKET_IF_MISSING",
        "Create the staging bucket if it does not exist.",
    ),
    Setting(
        "environment.enable_required_apis",
        "DEV_ENABLE_REQUIRED_APIS",
        "Enable the APIs the agents need.",
    ),
    Setting(
        "environment.grant_agent_identity_baseline",
        "DEV_GRANT_AGENT_IDENTITY_BASELINE",
        "Grant the baseline Agent Identity roles (sandbox without Terraform).",
    ),
    Setting(
        "environment.create_project.enabled",
        "DEV_CREATE_PROJECT_IF_MISSING",
        "Create the project if it does not exist.",
    ),
    Setting(
        "environment.create_project.billing_account_id",
        "DEV_BILLING_ACCOUNT_ID",
        "Billing account for a new project.",
    ),
    Setting(
        "environment.create_project.folder_id", "DEV_PROJECT_FOLDER_ID", "Folder for a new project."
    ),
    Setting(
        "environment.create_project.organization_id",
        "DEV_PROJECT_ORGANIZATION_ID",
        "Organization for a new project.",
    ),
    # Gemini Enterprise
    Setting("gemini_enterprise.app_id", "GEMINI_ENTERPRISE_APP_ID", "The app's engine ID."),
    Setting(
        "gemini_enterprise.web_app_url",
        "GEMINI_ENTERPRISE_WEB_APP_URL",
        "https://vertexaisearch.cloud.google.com/home/cid/<cid>, for links in instructions.",
    ),
    Setting(
        "gemini_enterprise.bigquery_mcp_connector_id",
        "NO_CODE_BIGQUERY_MCP_CONNECTOR_ID",
        "Collection ID, only when the app has more than one BigQuery MCP connector.",
    ),
    Setting(
        "gemini_enterprise.gmail_connector_id",
        "NO_CODE_GMAIL_CONNECTOR_ID",
        "Collection ID, only when the app has more than one Gmail connector.",
    ),
    # Models and runtime configuration
    Setting("models.bootstrap_model", "BOOTSTRAP_MODEL", "Model a runtime starts with."),
    Setting("models.model_location", "GEMINI_MODEL_LOCATION", "Vertex AI location of the model."),
    Setting(
        "runtime.parameter_location",
        "CONFIG_PARAMETER_LOCATION",
        "Parameter Manager location for runtime configuration.",
    ),
    Setting(
        "runtime.refresh_seconds",
        "CONFIG_REFRESH_SECONDS",
        "How often a runtime re-reads its parameter.",
    ),
    # Agent access groups
    Setting("access_groups.enabled", "GEMINI_AGENT_GROUPS_ENABLED", "Create per-agent groups."),
    Setting(
        "access_groups.customer_id", "GEMINI_AGENT_GROUP_CUSTOMER_ID", "Directory customer ID."
    ),
    Setting("access_groups.domain", "GEMINI_AGENT_GROUP_DOMAIN", "Domain for group emails."),
    Setting("access_groups.owner_email", "GEMINI_AGENT_GROUP_OWNER_EMAIL", "Group owner."),
    Setting("access_groups.prefix", "GEMINI_AGENT_GROUP_PREFIX", "Group name prefix."),
    # Agents
    Setting(
        "agents.growth_analysis_workflow.spreadsheet_id",
        "GROWTH_SPREADSHEET_ID",
        "Store performance Google Sheet; seed.drive can create it.",
    ),
    Setting(
        "agents.growth_analysis_workflow.report_folder_id",
        "GROWTH_REPORT_FOLDER_ID",
        "Drive folder the report Doc is filed in.",
    ),
    Setting(
        "agents.growth_analysis_workflow.settings_override",
        "GROWTH_SETTINGS_OVERRIDE",
        "Mapping by stage merged over the packaged stage settings: column_aliases for a "
        "sheet's own headers, the Places search brand.",
    ),
    Setting(
        "agents.growth_analysis_workflow.report_recipients",
        "GROWTH_REPORT_RECIPIENTS",
        "Comma-separated addresses the PDF report is emailed to.",
    ),
    # Demo agents running on their own identity
    Setting(
        "demo.data_bucket",
        "DEMO_DATA_BUCKET",
        "gs:// bucket holding the demo performance workbook; the runtimes read it.",
    ),
    Setting(
        "demo.gmail_sender",
        "GMAIL_SENDER",
        "Gmail address the reports are sent from; its app password is in Secret Manager.",
    ),
    Setting("demo.gmail_sender_name", "GMAIL_SENDER_NAME", "Display name on report emails."),
    Setting(
        "agents.vendor_match_agent.source_folder_id",
        "VENDOR_MATCH_DRIVE_SOURCE_FOLDER_ID",
        "Drive folder of incoming vendor lists.",
    ),
    Setting(
        "agents.vendor_match_agent.master_dictionary_folder_id",
        "VENDOR_MATCH_DRIVE_MASTER_DICT_FOLDER_ID",
        "Drive folder holding the master vendor dictionary.",
    ),
    Setting(
        "agents.vendor_match_agent.processed_folder_id",
        "VENDOR_MATCH_DRIVE_PROCESSED_FOLDER_ID",
        "Drive folder for processed files and staged batches.",
    ),
    Setting(
        "agents.ticket_guidance_agent.confluence_search_backend",
        "TICKET_CONFLUENCE_SEARCH_BACKEND",
        "connector (per-user permissions) or api (as the Atlassian service account).",
    ),
    Setting(
        "agents.ticket_guidance_agent.confluence_connector_id",
        "TICKET_CONFLUENCE_CONNECTOR_ID",
        "Collection ID of the Confluence connector (connector backend).",
    ),
    Setting(
        "agents.ticket_guidance_agent.confluence_space",
        "TICKET_CONFLUENCE_SPACE",
        "Knowledge base space key.",
    ),
    Setting(
        "agents.recipe_editorial_agent.product_dataset",
        "RECIPE_PRODUCT_DATASET",
        "project.dataset of the product recipe tables.",
    ),
    Setting(
        "agents.recipe_editorial_agent.legacy_dataset",
        "RECIPE_LEGACY_DATASET",
        "project.dataset of the legacy recipe tables.",
    ),
    Setting(
        "agents.recipe_card_agent.bucket",
        "RECIPE_CARD_BUCKET",
        "Bucket name the recipe card decks and photos are written to; it must already exist.",
    ),
    Setting(
        "agents.kitchen_sequencer.dataset",
        "KITCHEN_COMPLIANCE_DATASET",
        "Dataset of the curated kitchen compliance tables.",
    ),
    Setting(
        "agents.kitchen_sequencer.dataset_location",
        "KITCHEN_COMPLIANCE_LOCATION",
        "BigQuery location of that dataset.",
    ),
    Setting(
        "agents.kitchen_sequencer.source_project",
        "KITCHEN_COMPLIANCE_SOURCE_PROJECT",
        "Project holding hdr_analytics; empty with sample data.",
    ),
    # Atlassian (Ticket Guidance)
    Setting("atlassian.site_url", "JIRA_SITE_URL", "https://<site>.atlassian.net"),
    Setting(
        "atlassian.api_base_url",
        "JIRA_API_BASE_URL",
        "Jira REST base; the site URL for a classic token.",
    ),
    Setting(
        "atlassian.service_account_email",
        "JIRA_SERVICE_ACCOUNT_EMAIL",
        "Atlassian account the API token belongs to.",
    ),
    Setting("atlassian.jira_project_key", "JIRA_PROJECT_KEY", "Project tickets are raised in."),
    Setting(
        "atlassian.jira_parent_issue_key",
        "JIRA_PARENT_ISSUE_KEY",
        "Optional epic tickets are created under.",
    ),
    # Seeding
    Setting(
        "seed.bigquery.sample_data",
        "DEV_SEED_SAMPLE_DATA",
        "Load the synthetic source tables into the project.",
    ),
    Setting(
        "seed.bigquery.sample_data_location",
        "SAMPLE_DATA_LOCATION",
        "BigQuery location of the sample datasets.",
    ),
    Setting(
        "seed.bigquery.kitchen_compliance",
        "DEV_SEED_KITCHEN_COMPLIANCE",
        "Build the Kitchen Sequencer tables once from the source data.",
    ),
    Setting("seed.drive.enabled", "SEED_DRIVE", "Upload the sample Drive files."),
    Setting(
        "seed.drive.performance_sheet_folder_id",
        "SEED_DRIVE_PERFORMANCE_SHEET_FOLDER_ID",
        "Folder for the sample performance sheet; defaults to the report folder.",
    ),
    Setting(
        "seed.atlassian.enabled",
        "SEED_ATLASSIAN",
        "Create the knowledge base space and sample pages; check the Jira project.",
    ),
    # End-to-end tests
    Setting(
        "tests.growth_full_run",
        "TEST_GROWTH_FULL_RUN",
        "Run the full Growth pipeline (several minutes; writes a Doc).",
    ),
    Setting(
        "tests.ticket_guidance_creates_tickets",
        "TEST_TICKET_GUIDANCE_CREATES_TICKETS",
        "Let the Ticket Guidance test create and close a real ticket.",
    ),
    Setting(
        "tests.vendor_lookup",
        "TEST_VENDOR_LOOKUP",
        "A vendor the master dictionary holds; the Vendor Match check looks it up.",
    ),
)

SETTINGS_BY_PATH = {setting.path: setting for setting in SETTINGS}
# Sections whose keys are not fixed settings.
FREE_SECTIONS = ("oauth_clients", "secrets")


@dataclass(frozen=True, slots=True)
class MainConfig:
    path: Path
    values: dict[str, str]  # environment variable -> value
    oauth_clients: dict[str, dict[str, str]]
    secrets: dict[str, dict[str, str]]


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and path not in SETTINGS_BY_PATH:
            flat |= _flatten(value, path)
        else:
            flat[path] = value
    return flat


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        # A structured setting reaches the runtime as one JSON environment variable.
        return json.dumps(value, separators=(",", ":")) if value else ""
    return str(value).strip()


def config_path() -> Path:
    raw = os.getenv(MAIN_CONFIG_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_MAIN_CONFIG


def read_main_config(path: Path | None = None) -> MainConfig | None:
    """Parse and validate the config file; None when it does not exist."""
    path = path or config_path()
    if not path.exists():
        return None
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise SystemExit(f"{path} must be a YAML mapping.")
    free = {name: document.pop(name, None) or {} for name in FREE_SECTIONS}
    flat = _flatten(document)
    unknown = sorted(key for key in flat if key not in SETTINGS_BY_PATH)
    if unknown:
        raise SystemExit(
            f"{path}: unknown settings {', '.join(unknown)}. "
            "See deployment/config.example.yaml for the schema."
        )
    values = {SETTINGS_BY_PATH[key].env: _text(value) for key, value in flat.items()}
    return MainConfig(
        path=path,
        values={env: value for env, value in values.items() if value},
        oauth_clients={str(k): dict(v or {}) for k, v in free["oauth_clients"].items()},
        secrets={str(k): dict(v or {}) for k, v in free["secrets"].items()},
    )


def _oauth_client_values(agent: str, entry: dict[str, str], base: Path) -> dict[str, str]:
    """client_id directly, or both ID and secret from the console's JSON download."""
    from registry import get_agent_spec

    spec = get_agent_spec(agent)
    values: dict[str, str] = {}
    if entry.get("client_id"):
        values[spec.oauth_client_id_env] = str(entry["client_id"]).strip()
    if entry.get("client_json"):
        path = Path(entry["client_json"])
        path = path if path.is_absolute() else (base / path)
        if not path.exists():
            raise SystemExit(f"oauth_clients.{agent}.client_json: {path} does not exist.")
        web = json.loads(path.read_text(encoding="utf-8"))["web"]
        values[spec.oauth_client_id_env] = web["client_id"]
        # Read only to import it into Secret Manager on first registration.
        values[spec.oauth_client_secret_env] = web["client_secret"]
    return values


def load_main_config(path: Path | None = None) -> MainConfig | None:
    """Export the config file as environment variables, without overriding the shell."""
    config = read_main_config(path)
    if config is None:
        return None
    exported = dict(config.values)
    for agent, entry in config.oauth_clients.items():
        exported |= _oauth_client_values(agent, entry, config.path.parent)
    # The Jira REST base is the site itself for a classic API token.
    if exported.get("JIRA_SITE_URL") and not exported.get("JIRA_API_BASE_URL"):
        exported["JIRA_API_BASE_URL"] = exported["JIRA_SITE_URL"]
    for env, value in exported.items():
        os.environ.setdefault(env, value)
    return config
