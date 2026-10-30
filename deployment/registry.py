"""Agent metadata and declared capabilities, shared by every developer command."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gemini_shared.config.bootstrap import AUTHORIZATION_ID_ENV
from paths import ROOT

ENVIRONMENT_LABEL = "dev"

GCS_URI_PREFIX = "gs://"

DELEGATED_AUTH_MARKER = AUTHORIZATION_ID_ENV

IDENTITY_OAUTH_SCOPES = ("openid", "email", "profile")

# Google Workspace scopes for tools that act on the signed-in user's own files.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

DOCUMENTS_SCOPE = "https://www.googleapis.com/auth/documents"

SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

# Discovery Engine search of a Gemini Enterprise connector's data stores. The
# API defines no narrower scope that covers search.
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

SECRET_ACCESSOR = "roles/secretmanager.secretAccessor"
# Prompt Manager: list parameters and versions, and add a version. Neither role can
# delete, disable or rewrite a version, so every change stays in the history.
PARAMETER_VIEWER = "roles/parametermanager.parameterViewer"
PARAMETER_VERSION_ADDER = "roles/parametermanager.parameterVersionAdder"

# Secret Manager secrets the agents read under their own identity. Terraform
# creates them (infrastructure/terraform.tfvars.example lists the same IDs);
# each agent is granted accessor on its own secrets only.
GROWTH_SECRETS = {
    "BLS_API_KEY_SECRET": "growth-bls-api-key",
    "FRED_API_KEY_SECRET": "growth-fred-api-key",
    "NYT_API_KEY_SECRET": "growth-nyt-api-key",
    "GOOGLE_PLACES_API_KEY_SECRET": "growth-google-places-api-key",
}

JIRA_API_TOKEN_SECRET = "ticket-guidance-jira-api-token"


@dataclass(frozen=True, slots=True)
class BucketRoles:
    """Roles this agent's identity needs on one bucket.

    ``bucket`` may name an environment variable as ``${NAME}``, so a spec can
    say which bucket without committing a project's actual bucket name.
    """

    bucket: str
    roles: tuple[str, ...]

    def resolved_bucket(self) -> str:
        """Return the bucket URI, substituting a ${NAME} placeholder."""
        name = self.bucket
        if name.startswith("${") and name.endswith("}"):
            name = os.getenv(name[2:-1], "").strip()
        if not name:
            return ""
        return name if name.startswith(GCS_URI_PREFIX) else f"{GCS_URI_PREFIX}{name}"


@dataclass(frozen=True, slots=True)
class SecretRoles:
    """Roles this agent's identity needs on one Secret Manager secret.

    Scoped to the secret rather than the project, so an agent can read its own
    API keys and no other agent's.
    """

    secret: str
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgentSpec:
    package_name: str
    module: str
    display_name: str
    extra_packages: tuple[str, ...]
    required_remote_bootstrap_env: tuple[str, ...] = ()
    # Service scopes beyond the identity scopes; exclude Agent Identity tools.
    # These are what the signed-in user consents to, so add a service here only
    # when a tool calls it with the user's own token.
    delegated_oauth_scopes: tuple[str, ...] = ()
    # Roles this agent's own runtime identity needs, beyond the baseline every
    # Agent Identity in the project already has from Terraform. Declared here
    # rather than in the environment so a fresh clone deploys with the access
    # its tools require. The per-agent environment variables still override.
    agent_identity_project_roles: tuple[str, ...] = ()
    agent_identity_bucket_roles: tuple[BucketRoles, ...] = ()
    agent_identity_secret_roles: tuple[SecretRoles, ...] = ()
    # Runtime environment this entry needs, beyond the shared forwarding list.
    # Declared here rather than in the environment because RUNTIME_ENV_KEYS is
    # one shared value per key: a flag left in the environment for one agent would be
    # baked into whichever agent is released next. These are per-entry and
    # versioned, so a fresh clone deploys with the settings its tools require.
    # The environment still wins, so a single run can override one. A value
    # written as ${NAME} is read from deployment/config.yaml at deploy time, so the spec
    # can say which setting an entry needs without committing an environment's
    # IDs; one that resolves to nothing is left out of the runtime.
    runtime_env: tuple[tuple[str, str], ...] = ()
    # Gemini Enterprise registration metadata, used by register_agent.py.
    registration_description: str = ""
    invocation_description: str = ""
    starter_prompts: tuple[str, ...] = ()
    # Directory holding this entry's source package.
    source_root: str = "agents/pro_code"
    # A workflow is deployed exactly like an agent (same runtime, identity and
    # parameter); it differs only in what it composes internally, and in being
    # registered behind a native workflow wrapper.
    is_workflow: bool = False

    @property
    def config_parameter_id(self) -> str:
        """Default Parameter Manager name for this agent."""
        return f"{self.package_name}-config"

    @property
    def authorization_id(self) -> str:
        """Default Gemini Enterprise authorization name for this agent."""
        return f"{self.package_name}-authz"

    @property
    def uses_delegated_auth(self) -> bool:
        """Whether the spec requires a delegated user token."""
        return AUTHORIZATION_ID_ENV in self.required_remote_bootstrap_env

    @property
    def oauth_client_name(self) -> str:
        """Suggested OAuth client name in the console."""
        return f"{self.display_name} ({ENVIRONMENT_LABEL})"

    @property
    def oauth_client_id_env(self) -> str:
        """Per-agent OAuth client ID override."""
        return f"{self.env_prefix}_OAUTH_CLIENT_ID"

    @property
    def oauth_client_secret_name_env(self) -> str:
        """Environment variable naming the Secret Manager secret for that client."""
        return f"{self.env_prefix}_OAUTH_CLIENT_SECRET_NAME"

    @property
    def oauth_client_secret_env(self) -> str:
        """Environment variable for importing the initial client secret."""
        return f"{self.env_prefix}_OAUTH_CLIENT_SECRET"

    @property
    def default_oauth_secret_name(self) -> str:
        """Secret Manager secret this agent's OAuth client secret belongs in."""
        return f"{self.package_name}-oauth-client-secret"

    @property
    def oauth_scopes(self) -> tuple[str, ...]:
        """Full scope list for this agent's authorization, identity included."""
        return IDENTITY_OAUTH_SCOPES + self.delegated_oauth_scopes

    @property
    def env_prefix(self) -> str:
        """Per-agent prefix for environment variables, derived from the package."""
        return self.package_name.upper().replace("-", "_")

    @property
    def prompt_path(self) -> Path:
        """Source prompt published to Parameter Manager during deployment."""
        return ROOT / self.source_root / self.module.split(".")[0] / "prompt.md"

    def read_prompt(self) -> str:
        """Return the agent's instruction, or empty when it has no prompt file."""
        path = self.prompt_path
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""


# The demo agents run as their own Agent Identity: BigQuery and Cloud Storage reads,
# secrets and email need no user consent, connector or Google Workspace account.
BIGQUERY_JOB_USER = "roles/bigquery.jobUser"
BIGQUERY_DATA_VIEWER = "roles/bigquery.dataViewer"
STORAGE_OBJECT_VIEWER = "roles/storage.objectViewer"
STORAGE_OBJECT_ADMIN = "roles/storage.objectAdmin"
GMAIL_APP_PASSWORD_SECRET = "demo-gmail-app-password"
PLACES_API_KEY_SECRET = GROWTH_SECRETS["GOOGLE_PLACES_API_KEY_SECRET"]
EMAIL_ENV = (
    ("GMAIL_SENDER", "${GMAIL_SENDER}"),
    ("GMAIL_SENDER_NAME", "${GMAIL_SENDER_NAME}"),
    ("GMAIL_APP_PASSWORD_SECRET", GMAIL_APP_PASSWORD_SECRET),
)
DEMO_TOOLS = "packages/demo_tools/src/demo_tools"
GEMINI_SHARED = "packages/gemini_shared/src/gemini_shared"

AGENTS: dict[str, AgentSpec] = {
    "growth_analysis_workflow": AgentSpec(
        package_name="growth-analysis-workflow",
        module="growth_analysis_workflow.workflow",
        display_name="Growth Analysis",
        is_workflow=True,
        extra_packages=(
            "agents/pro_code/growth_analysis_workflow/src/growth_analysis_workflow",
            DEMO_TOOLS,
            GEMINI_SHARED,
        ),
        runtime_env=(
            ("GROWTH_SPREADSHEET_ID", "${GROWTH_SPREADSHEET_ID}"),
            ("GROWTH_SETTINGS_OVERRIDE", "${GROWTH_SETTINGS_OVERRIDE}"),
            ("GROWTH_REPORT_RECIPIENTS", "${GROWTH_REPORT_RECIPIENTS}"),
            ("GOOGLE_PLACES_API_KEY_SECRET", PLACES_API_KEY_SECRET),
            *EMAIL_ENV,
        ),
        agent_identity_bucket_roles=(BucketRoles("${DEMO_DATA_BUCKET}", (STORAGE_OBJECT_VIEWER,)),),
        agent_identity_secret_roles=(
            SecretRoles(PLACES_API_KEY_SECRET, (SECRET_ACCESSOR,)),
            SecretRoles(GMAIL_APP_PASSWORD_SECRET, (SECRET_ACCESSOR,)),
        ),
        registration_description=(
            "Diagnoses store performance: ranks the top and bottom stores from the performance "
            "workbook, gathers weather, reviews, labor data and industry and local news for the "
            "stores behind plan, and emails an executive PDF report."
        ),
        invocation_description=(
            "Run the end-to-end store performance diagnostic and email the PDF report."
        ),
        starter_prompts=("Run the weekly store performance diagnostic",),
    ),
    "kitchen_sequencer": AgentSpec(
        package_name="kitchen-sequencer",
        module="kitchen_sequencer.agent",
        display_name="Kitchen Sequencer",
        extra_packages=(
            "agents/pro_code/kitchen_sequencer/src/kitchen_sequencer",
            DEMO_TOOLS,
            GEMINI_SHARED,
        ),
        agent_identity_project_roles=(BIGQUERY_JOB_USER, BIGQUERY_DATA_VIEWER),
        runtime_env=(("KITCHEN_COMPLIANCE_DATASET", "${KITCHEN_COMPLIANCE_DATASET}"),),
        registration_description=(
            "Kitchen compliance insights: ranks kitchens on a 100-point compliance score, "
            "explains what is driving a score, and turns it into a pre-shift huddle plan."
        ),
        invocation_description=(
            "Ask about kitchen compliance rankings, root causes or a huddle plan."
        ),
        starter_prompts=(
            "Show me this week's compliance ranking across all kitchens: top 5 and bottom 5.",
            "Why is the lowest kitchen at the bottom? Break the score down by pillar.",
            "Turn this into a 5-minute pre-shift huddle plan for the kitchen manager.",
        ),
        source_root="agents/pro_code",
    ),
    "recipe_qa_agent": AgentSpec(
        package_name="recipe-qa-agent",
        module="recipe_qa_agent.agent",
        display_name="Recipe QA Agent",
        extra_packages=(
            "agents/pro_code/recipe_qa_agent/src/recipe_qa_agent",
            DEMO_TOOLS,
            GEMINI_SHARED,
        ),
        agent_identity_project_roles=(BIGQUERY_JOB_USER, BIGQUERY_DATA_VIEWER),
        agent_identity_secret_roles=(SecretRoles(GMAIL_APP_PASSWORD_SECRET, (SECRET_ACCESSOR,)),),
        runtime_env=(
            ("RECIPE_PRODUCT_DATASET", "${RECIPE_PRODUCT_DATASET}"),
            ("RECIPE_LEGACY_DATASET", "${RECIPE_LEGACY_DATASET}"),
            *EMAIL_ENV,
        ),
        registration_description=(
            "Checks recipes for ingredient usage, cooking logic and timing consistency, and "
            "emails a PDF QA report with an Excel findings extract."
        ),
        invocation_description=(
            "Run editorial QA on recipe SKUs or a whole menu cycle and email the report."
        ),
        starter_prompts=(
            "Run QA on all recipes in this week's cycle.",
            "Check SKU 810020005.",
        ),
    ),
    "recipe_card_agent": AgentSpec(
        package_name="recipe-card-agent",
        module="recipe_card_agent.agent",
        display_name="Recipe Card Agent",
        extra_packages=(
            "agents/pro_code/recipe_card_agent/src/recipe_card_agent",
            "packages/recipe_cards/src/recipe_cards",
            GEMINI_SHARED,
        ),
        # Cards live under one use-case prefix, so the bucket can serve more
        # than this agent and a dish's versions are discoverable together.
        runtime_env=(
            ("RECIPE_CARD_BUCKET", "${RECIPE_CARD_BUCKET}"),
            ("RECIPE_CARD_PREFIX", "recipe-cards"),
            # Best image model for the hero and step photos; ingredients and
            # the sketch stay on the faster default image model.
            ("RECIPE_PHOTO_IMAGE_MODEL", "gemini-3-pro-image"),
        ),
        # The output bucket must already exist before granting object access.
        agent_identity_bucket_roles=(
            BucketRoles("${RECIPE_CARD_BUCKET}", (STORAGE_OBJECT_ADMIN,)),
        ),
        registration_description=(
            "Produces print-ready recipe cards: writes the recipe, generates consistent "
            "unbranded food photography, and publishes an editable PowerPoint deck to "
            "Cloud Storage."
        ),
        invocation_description=(
            "Create a recipe card for a dish: it writes the recipe, generates the "
            "photography and returns a link to the finished deck."
        ),
        starter_prompts=(
            "Create a recipe card for chicken tikka masala.",
            "Make a card for a vegetarian lentil soup, 6 servings.",
            "Build a recipe card for classic beef chili.",
        ),
    ),
    "parameter_updater": AgentSpec(
        package_name="parameter-updater",
        module="parameter_updater.agent",
        display_name="Prompt Manager",
        extra_packages=(
            "agents/pro_code/parameter_updater/src/parameter_updater",
            GEMINI_SHARED,
        ),
        # Project-wide because Parameter Manager has no per-parameter IAM. Render
        # comes from the baseline every Agent Identity already holds. A managed
        # project other than this one needs the same two roles granted there.
        agent_identity_project_roles=(PARAMETER_VIEWER, PARAMETER_VERSION_ADDER),
        registration_description=(
            "Inspect and change the live runtime configuration of this project's code agents: "
            "model, instruction and limits in Parameter Manager. Every change is previewed "
            "as a diff and published only after confirmation."
        ),
        invocation_description=(
            "Use this to see or change a code agent's model, prompt or limits without a redeploy."
        ),
        starter_prompts=(
            "List the agent configurations in this project.",
            "Show the Recipe Card Agent's live instruction and its recent versions.",
            "Switch Kitchen Sequencer's model to gemini-4-argon.",
        ),
    ),
}


def detect_delegated_auth(spec: AgentSpec) -> bool:
    """Check source for the authorization marker without importing the agent."""
    return any(
        DELEGATED_AUTH_MARKER in path.read_text(encoding="utf-8")
        for path in ROOT.glob(f"{spec.source_root}/{_package_dir(spec)}/**/*.py")
    )


def _package_dir(spec: AgentSpec) -> str:
    """Directory under source_root holding this agent, derived from its module."""
    return spec.module.split(".")[0]


def get_agent_spec(agent_name: str) -> AgentSpec:
    try:
        return AGENTS[agent_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(AGENTS))
        raise SystemExit(f"Unknown agent '{agent_name}'. Choose one of: {allowed}") from exc
