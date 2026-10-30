from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import secrets
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gemini_shared.config.bootstrap import get_bootstrap_settings
from gemini_shared.config.runtime_config import RuntimeConfig, RuntimeConfigStore
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

DEV = Path(__file__).resolve().parents[1] / "deployment"
sys.path.insert(0, str(DEV))
bootstrap = importlib.import_module("config.bootstrap")
fixture = importlib.import_module("seed.kitchen_compliance")
registry = importlib.import_module("registry")
settings = importlib.import_module("config.settings")
sources = importlib.import_module("deploy.sources")
packaging = importlib.import_module("deploy.package_agent")
sys.path.remove(str(DEV))

# Cover newly registered agents automatically.
ALL_ENTRIES = sorted(registry.AGENTS)
# A workflow is deployed exactly like an agent but is composed rather than
# conversational: it has stages instead of tools, and each stage carries its own
# instruction rather than reading one from Parameter Manager. The checks that
# describe a conversational agent therefore run over the agents only.
ALL_AGENTS = [name for name in ALL_ENTRIES if not registry.AGENTS[name].is_workflow]
ALL_WORKFLOWS = [name for name in ALL_ENTRIES if registry.AGENTS[name].is_workflow]


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("DEV_", "CONFIG_", "GEMINI_", "GOOGLE_CLOUD_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("AGENT_INSTRUCTION", "Test instruction")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "unit-test-authorization")


@pytest.mark.parametrize("environment", ["", "staging", "production"])
def test_remote_boundary(monkeypatch, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(SystemExit, match="Refusing remote"):
        settings.require_deploy_environment()


@pytest.fixture
def deployable(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("DEV_STAGING_BUCKET", "gs://test-bucket")
    for name in (settings.CONFIRM_PROJECT_ENV, *settings.SANDBOX_ONLY):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("environment", ["qa", "prod"])
def test_a_shared_environment_needs_its_project_confirmed(monkeypatch, deployable, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(SystemExit, match="--confirm-project test-project"):
        settings.require_deploy_environment(require_parameter=False)
    monkeypatch.setenv(settings.CONFIRM_PROJECT_ENV, "another-project")
    with pytest.raises(SystemExit, match="without confirmation"):
        settings.require_deploy_environment(require_parameter=False)
    monkeypatch.setenv(settings.CONFIRM_PROJECT_ENV, "test-project")
    project, _, _ = settings.require_deploy_environment(require_parameter=False)
    assert project == "test-project"


@pytest.mark.parametrize("setting", sorted(settings.SANDBOX_ONLY))
def test_prod_refuses_sandbox_only_settings(monkeypatch, deployable, setting):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv(settings.CONFIRM_PROJECT_ENV, "test-project")
    monkeypatch.setenv(setting, "true")
    with pytest.raises(SystemExit, match=re.escape(settings.SANDBOX_ONLY[setting])):
        settings.require_deploy_environment(require_parameter=False)


def test_dev_needs_no_confirmation(monkeypatch, deployable):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("DEV_SEED_SAMPLE_DATA", "true")
    project, _, _ = settings.require_deploy_environment(require_parameter=False)
    assert project == "test-project"


def test_required_placeholder(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "REPLACE_WITH_PROJECT")
    with pytest.raises(RuntimeError, match="placeholder"):
        get_bootstrap_settings()


def test_project_creation_controls(monkeypatch):
    run = Mock()
    monkeypatch.setattr(bootstrap, "_run", run)
    monkeypatch.setattr(bootstrap, "_exists", lambda args: False)
    with pytest.raises(SystemExit, match="does not exist"):
        bootstrap.ensure_project("missing-project")
    run.assert_not_called()
    monkeypatch.setenv("DEV_CREATE_PROJECT_IF_MISSING", "true")
    with pytest.raises(SystemExit, match="DEV_BILLING_ACCOUNT_ID"):
        bootstrap.ensure_project("missing-project")
    monkeypatch.setenv("DEV_BILLING_ACCOUNT_ID", "test-billing")
    monkeypatch.setenv("DEV_PROJECT_FOLDER_ID", "123")
    monkeypatch.setenv("DEV_PROJECT_ORGANIZATION_ID", "456")
    with pytest.raises(SystemExit, match="at most one"):
        bootstrap.ensure_project("missing-project")
    run.assert_not_called()
    monkeypatch.delenv("DEV_PROJECT_ORGANIZATION_ID")
    bootstrap.ensure_project("missing-project")
    assert run.call_count == 2
    assert "--folder=123" in run.call_args_list[0].args[0]


def test_existing_project_and_bucket_are_reused(monkeypatch):
    run = Mock()
    monkeypatch.setattr(bootstrap, "_run", run)
    monkeypatch.setattr(bootstrap, "_exists", lambda args: True)
    bootstrap.ensure_project("test-project")
    bootstrap.ensure_staging_bucket("test-project", "us-central1", "gs://test-bucket")
    run.assert_not_called()


def test_missing_bucket_controls(monkeypatch):
    run = Mock()
    monkeypatch.setattr(bootstrap, "_run", run)
    monkeypatch.setattr(bootstrap, "_exists", lambda args: False)
    monkeypatch.setenv("DEV_CREATE_STAGING_BUCKET_IF_MISSING", "false")
    with pytest.raises(SystemExit, match="missing"):
        bootstrap.ensure_staging_bucket("test-project", "us-central1", "gs://test-bucket")
    run.assert_not_called()
    monkeypatch.setenv("DEV_CREATE_STAGING_BUCKET_IF_MISSING", "true")
    bootstrap.ensure_staging_bucket("test-project", "us-central1", "gs://test-bucket")
    assert "--uniform-bucket-level-access" in run.call_args.args[0]


def test_only_missing_services_enabled(monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout="\n".join(bootstrap.REQUIRED_DEV_SERVICES)))
    monkeypatch.setattr(bootstrap, "_run", run)
    bootstrap.ensure_required_services("test-project")
    assert run.call_count == 1
    extra = "bigquerydatatransfer.googleapis.com"
    bootstrap.ensure_required_services("test-project", (extra,))
    assert run.call_args.args[0][2] == extra
    monkeypatch.setenv("DEV_ENABLE_REQUIRED_APIS", "false")
    with pytest.raises(SystemExit, match="Required APIs are disabled"):
        bootstrap.ensure_required_services("test-project", (extra,))


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_packaging_excludes_cache_and_other_agent(tmp_path, monkeypatch, agent):
    source = tmp_path / agent
    source.mkdir()
    (source / "agent.py").write_text("x = 1\n")
    cache = source / "__pycache__"
    cache.mkdir()
    (cache / "agent.pyc").write_bytes(b"first")
    spec = SimpleNamespace(extra_packages=(agent,))
    monkeypatch.setattr(sources, "ROOT", tmp_path)
    monkeypatch.setattr(packaging, "export_requirements", lambda _: ("test==1",))
    monkeypatch.setattr(packaging, "ROOT", tmp_path)
    monkeypatch.setattr(packaging, "get_agent_spec", lambda name: spec)
    first = packaging.package_agent(agent, tmp_path / "one.tar.gz").read_bytes()
    (cache / "agent.pyc").write_bytes(b"changed cache")
    second = packaging.package_agent(agent, tmp_path / "different" / "two.tar.gz")
    assert first == second.read_bytes()
    with tarfile.open(second) as archive:
        assert set(archive.getnames()) == {"requirements.txt", agent, f"{agent}/agent.py"}


def test_kitchen_tables_are_off_unless_requested(monkeypatch):
    monkeypatch.delenv(fixture.SEED_ENV, raising=False)
    assert fixture.prepare_kitchen_compliance("test-project") is None


def test_kitchen_tables_need_a_source_project(monkeypatch):
    monkeypatch.setenv(fixture.SEED_ENV, "true")
    monkeypatch.delenv(fixture.SOURCE_PROJECT_ENV, raising=False)
    with pytest.raises(SystemExit, match=fixture.SOURCE_PROJECT_ENV):
        fixture.prepare_kitchen_compliance("test-project")


def test_kitchen_sql_placeholders_are_complete():
    """Terraform and the seeding script fill the same three names; no others."""
    for _, sql in fixture.statements():
        assert set(re.findall(r"\$\{([A-Z_]+)\}", sql)) <= {
            "SOURCE_PROJECT",
            "TARGET_PROJECT",
            "TARGET_DATASET",
        }
    with pytest.raises(SystemExit, match="OTHER"):
        fixture.render("${OTHER}", {})


def test_kitchen_statements_run_in_order_against_the_target(monkeypatch):
    """01_dim_kitchen builds the dimension the other three join, so it runs first."""
    monkeypatch.setenv(fixture.SEED_ENV, "true")
    monkeypatch.setenv(fixture.SOURCE_PROJECT_ENV, "source-project")
    client = Mock()
    client.get_dataset.side_effect = NotFound("missing")
    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: client)

    result = fixture.prepare_kitchen_compliance("test-project")

    client.create_dataset.assert_called_once()
    assert client.create_dataset.call_args.args[0].location == "US"
    sql = [c.args[0] for c in client.query.call_args_list]
    assert result.tables[0] == "01_dim_kitchen" and len(sql) == 4
    assert all("${" not in statement for statement in sql)
    assert all("`test-project.kitchen_compliance." in statement for statement in sql)
    assert all("source-project.hdr_analytics" in statement for statement in sql)


def test_runtime_ttl_reload_and_last_good(monkeypatch, caplog):
    monkeypatch.setenv("CONFIG_PARAMETER", "test-parameter")
    monkeypatch.setenv("CONFIG_REFRESH_SECONDS", "5")
    clock = [0.0]
    monkeypatch.setattr("gemini_shared.config.runtime_config.time.monotonic", lambda: clock[0])
    store = RuntimeConfigStore()
    one = RuntimeConfig(config_revision="one", model="model-one", instruction="test")
    two = one.model_copy(update={"config_revision": "two", "log_level": "ERROR"})
    load = Mock(side_effect=[one, two, ValueError("payload-that-must-not-be-logged")])
    monkeypatch.setattr(store, "_load_remote", load)
    assert store.get() == one
    assert store.get() == one
    assert load.call_count == 1
    assert load.call_args.args[0].endswith("/versions/latest")
    clock[0] = 6
    assert store.get() == two
    assert logging.getLogger().level == logging.ERROR
    clock[0] = 12
    assert store.get() == two
    assert "payload-that-must-not-be-logged" not in caplog.text


def test_model_callback(monkeypatch):
    """All agents use the shared model callback."""
    from gemini_shared import apply_runtime_model

    request = SimpleNamespace(model="old")
    apply_runtime_model(None, request)
    assert request.model == "test-model"

    for agent in ALL_AGENTS:
        module = importlib.import_module(f"{agent}.agent")
        assert module.root_agent.before_model_callback is apply_runtime_model


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_every_tool_is_described_to_the_model(agent):
    """Each local tool must expose a description to ADK."""
    from google.adk.tools.base_toolset import BaseToolset
    from google.adk.tools.function_tool import FunctionTool

    module = importlib.import_module(f"{agent}.agent")
    undescribed = []
    for tool in module.root_agent.tools:
        # Remote tool descriptions require a server connection.
        if isinstance(tool, BaseToolset):
            continue
        declaration = (
            tool._get_declaration()
            if hasattr(tool, "_get_declaration")
            else FunctionTool(tool)._get_declaration()
        )
        description = getattr(declaration, "description", None)
        if not (description and description.strip()):
            undescribed.append(getattr(declaration, "name", str(tool)))
    assert not undescribed, f"tools advertised to the model without a description: {undescribed}"


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_instruction_resolves_from_runtime_configuration(agent):
    """Each agent resolves its instruction through a callback."""
    module = importlib.import_module(f"{agent}.agent")
    assert callable(module.root_agent.instruction), (
        f"{agent} must resolve its instruction from runtime configuration"
    )


def test_delegated_scheme_rehydrates_from_shared_module():
    """ADK must rehydrate the shared scheme by its type_ default."""
    from google.adk.auth.auth_schemes import CustomAuthScheme
    from google.adk.auth.auth_tool import AuthConfig
    from google.adk.auth.credential_manager import CredentialManager

    importlib.import_module("gemini_shared.auth.delegated")

    deserialized = CustomAuthScheme.model_validate(
        {"type": "GeminiEnterpriseDelegatedAuthProviderScheme", "name": "unit-test-authorization"}
    )
    assert type(deserialized) is CustomAuthScheme

    manager = CredentialManager(auth_config=AuthConfig(auth_scheme=deserialized))
    token = secrets.token_urlsafe(16)
    session = SimpleNamespace(state={"unit-test-authorization": token})
    credential = asyncio.run(manager.get_auth_credential(SimpleNamespace(session=session)))
    assert credential.oauth2.access_token == token


def test_mcp_headers_carry_the_signed_in_users_token():
    """MCP requests carry the current user's delegated token."""
    from gemini_shared.mcp.mcp_auth import delegated_bearer_headers

    token = secrets.token_urlsafe(16)
    provider = delegated_bearer_headers("unit-test-authorization")
    context = SimpleNamespace(state={"unit-test-authorization": token})
    assert provider(context) == {"Authorization": f"Bearer {token}"}


def test_mcp_headers_fail_loudly_without_a_token():
    """Missing tokens must fail before an MCP request."""
    from gemini_shared.mcp.mcp_auth import delegated_bearer_headers

    provider = delegated_bearer_headers("unit-test-authorization")
    context = SimpleNamespace(state={"other-a": "1", "other-b": "2"})
    with pytest.raises(ValueError, match="No delegated token"):
        provider(context)


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_delegated_auth_detection_matches_the_spec(agent):
    """The source marker and declared auth requirements must agree."""
    spec = registry.get_agent_spec(agent)
    assert registry.detect_delegated_auth(spec) == spec.uses_delegated_auth


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_delegated_agents_name_their_own_oauth_client(agent):
    """Delegated agents have distinct client, secret and authorization names."""
    spec = registry.get_agent_spec(agent)
    if not spec.uses_delegated_auth:
        return
    others = [s for name, s in registry.AGENTS.items() if name != agent and s.uses_delegated_auth]
    for other in others:
        assert spec.oauth_client_id_env != other.oauth_client_id_env
        assert spec.default_oauth_secret_name != other.default_oauth_secret_name
        assert spec.authorization_id != other.authorization_id


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_oauth_scopes_cover_only_delegated_services(agent):
    """Each agent requests scopes only for its delegated tools."""
    spec = registry.get_agent_spec(agent)
    if not spec.uses_delegated_auth:
        assert spec.delegated_oauth_scopes == ()
        return
    assert spec.delegated_oauth_scopes, f"{agent} takes a user token but requests no scope"
    for scope in registry.IDENTITY_OAUTH_SCOPES:
        assert scope in spec.oauth_scopes
    # Broad scopes need explicit review. Ticket Guidance searches Discovery
    # Engine, which defines no narrower scope that covers search.
    if agent not in {"ticket_guidance_agent"}:
        assert registry.CLOUD_PLATFORM_SCOPE not in spec.delegated_oauth_scopes


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_every_agent_has_a_prompt(agent):
    """Each registered agent has a source prompt."""
    spec = registry.get_agent_spec(agent)
    prompt = spec.read_prompt()
    assert prompt, f"{agent} has no prompt.md at {spec.prompt_path}"
    assert len(prompt) > 40, f"{agent} prompt is too short to be a real instruction"


@pytest.mark.parametrize("agent", ALL_ENTRIES)
@pytest.mark.parametrize("already_deployed", [False, True])
def test_release_resolves_agent_defaults(monkeypatch, tmp_path, agent, already_deployed):
    monkeypatch.syspath_prepend(str(DEV))
    release = importlib.import_module("deploy.release")
    deploy = importlib.import_module("deploy.deploy_dev")
    update = importlib.import_module("deploy.update_dev")
    spec = registry.get_agent_spec(agent)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("DEV_STAGING_BUCKET", "gs://test-bucket")
    monkeypatch.setenv("GEMINI_ENTERPRISE_APP_ID", "test-app")
    monkeypatch.delenv(settings.AUTHORIZATION_ID_ENV)
    monkeypatch.setattr(sys, "argv", ["release_dev.py", "--agent", agent])
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release, "load_environment", Mock())
    monkeypatch.setattr(release, "ensure_dev_prerequisites", Mock())
    monkeypatch.setattr(release, "package_agent", Mock(return_value=tmp_path / "agent.tar.gz"))
    monkeypatch.setattr(
        release,
        "find_resource_name",
        lambda *args: (
            "projects/123/locations/us-central1/reasoningEngines/test" if already_deployed else None
        ),
    )
    create = Mock(return_value="new-runtime")
    change = Mock(return_value="existing-runtime")
    register = Mock()
    monkeypatch.setattr(deploy, "deploy_agent", create)
    monkeypatch.setattr(update, "update_agent", change)
    monkeypatch.setattr(release, "register_agent", register)

    release.main()

    assert os.environ[settings.CONFIG_PARAMETER_ENV] == spec.config_parameter_id
    if spec.uses_delegated_auth:
        assert os.environ[settings.AUTHORIZATION_ID_ENV] == spec.authorization_id
    else:
        assert settings.AUTHORIZATION_ID_ENV not in os.environ
    called, unused = (change, create) if already_deployed else (create, change)
    called.assert_called_once_with(agent, "test-project", "us-central1", "gs://test-bucket", spec)
    unused.assert_not_called()
    register.assert_called_once_with(agent, "test-app", "test-project", spec, called.return_value)


def test_runtime_cache_is_scoped_to_parameter(monkeypatch):
    monkeypatch.setenv("CONFIG_PARAMETER", "first")
    store = RuntimeConfigStore()
    first = RuntimeConfig(config_revision="one", model="model-one", instruction="first")
    second = first.model_copy(update={"config_revision": "two", "instruction": "second"})
    load = Mock(side_effect=[first, second])
    monkeypatch.setattr(store, "_load_remote", load)
    assert store.get() == first

    monkeypatch.setenv("CONFIG_PARAMETER", "second")
    assert store.get() == second
    assert load.call_count == 2
    assert load.call_args.args[0].endswith("/parameters/second/versions/latest")


def test_runtime_cache_does_not_mask_new_parameter_failure(monkeypatch):
    monkeypatch.setenv("CONFIG_PARAMETER", "first")
    store = RuntimeConfigStore()
    config = RuntimeConfig(config_revision="one", model="model-one", instruction="first")
    monkeypatch.setattr(store, "_load_remote", Mock(side_effect=[config, ValueError("unreadable")]))
    assert store.get() == config

    monkeypatch.setenv("CONFIG_PARAMETER", "second")
    with pytest.raises(ValueError, match="unreadable"):
        store.get()


def test_runtime_status_resets_when_switching_to_local(monkeypatch):
    monkeypatch.setenv("CONFIG_PARAMETER", "remote")
    store = RuntimeConfigStore()
    config = RuntimeConfig(config_revision="remote", model="model-one", instruction="remote")
    monkeypatch.setattr(store, "_load_remote", Mock(return_value=config))
    assert store.status()["source"] == "Google Cloud Parameter Manager"

    monkeypatch.delenv("CONFIG_PARAMETER")
    status = store.status()
    assert status["source"] == "local environment"
    assert status["resource"] is None
    assert status["loaded_at"] is None
    assert status["config_revision"] == "local"


@pytest.mark.parametrize("raw", ["true", "1", " YES ", "on", "false", "0", " NO ", "off"])
def test_dev_boolean_parsing(monkeypatch, raw):
    from config.environment import env_bool

    monkeypatch.setenv("DEV_TEST_FLAG", raw)
    expected = raw.strip().lower() in {"true", "1", "yes", "on"}
    assert env_bool("DEV_TEST_FLAG", not expected) is expected


def test_dev_boolean_defaults_and_invalid_values(monkeypatch):
    from config.environment import env_bool

    assert env_bool("DEV_TEST_FLAG", True) is True
    assert env_bool("DEV_TEST_FLAG", False) is False
    for raw in ("", "perhaps"):
        monkeypatch.setenv("DEV_TEST_FLAG", raw)
        with pytest.raises(SystemExit, match="DEV_TEST_FLAG must be true or false"):
            env_bool("DEV_TEST_FLAG", False)


@pytest.mark.parametrize("raw", ["", " ", "REPLACE_WITH_ID", "<project>"])
def test_dev_placeholder_parsing(monkeypatch, raw):
    from config.environment import configured_value

    monkeypatch.setenv("DEV_TEST_VALUE", raw)
    assert configured_value("DEV_TEST_VALUE") == ""
    assert settings.is_missing_or_placeholder("DEV_TEST_VALUE")


def test_dev_configured_value_is_stripped(monkeypatch):
    from config.environment import configured_value

    monkeypatch.setenv("DEV_TEST_VALUE", " real-value ")
    assert configured_value("DEV_TEST_VALUE") == "real-value"
    assert not settings.is_missing_or_placeholder("DEV_TEST_VALUE")


def test_no_agent_carries_the_status_tool():
    """report_runtime_config is a diagnostic, not part of any agent's job.

    Offered on every request, it is noise to the model. Add it to one agent
    from gemini_shared.config.tools only while diagnosing its configuration.
    """
    for agent in ALL_AGENTS:
        module = importlib.import_module(f"{agent}.agent")
        names = {
            getattr(tool, "__name__", getattr(tool, "name", "")) for tool in module.root_agent.tools
        }
        assert "report_runtime_config" not in names, agent


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS)
def test_workflow_stages_are_ordered_and_chained(workflow):
    """A workflow's value is that its order is fixed, so assert the chain.

    Each model stage must publish its result under an output_key, because that
    is how later stages receive it. A stage without one silently produces
    nothing for its successors to read. Parallel groups are walked into.
    """
    spec = registry.get_agent_spec(workflow)
    module = importlib.import_module(spec.module)

    def model_stages(agent):
        children = getattr(agent, "sub_agents", None) or []
        return [s for c in children for s in model_stages(c)] if children else [agent]

    assert len(module.root_agent.sub_agents) >= 2, "a workflow with one stage is just an agent"
    keys = [stage.output_key for stage in model_stages(module.root_agent)]
    assert all(keys), f"every stage needs an output_key, got {keys}"
    assert len(set(keys)) == len(keys), f"stages overwrite each other: {keys}"


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_identity_roles_are_declared_in_the_spec(agent):
    """IAM an agent needs is versioned, so a fresh clone deploys with it.

    Every secret an agent is told to read through runtime_env must also be one
    its identity is granted, or the runtime deploys and then cannot read it.
    """
    spec = registry.get_agent_spec(agent)
    for binding in spec.agent_identity_bucket_roles:
        assert binding.roles, f"{agent} names a bucket with no roles"
    granted = {
        binding.secret
        for binding in spec.agent_identity_secret_roles
        if registry.SECRET_ACCESSOR in binding.roles
    }
    named = {value for key, value in spec.runtime_env if key.endswith("_SECRET")}
    assert named == granted, f"{agent}: secrets read {named} but granted {granted}"


def test_bucket_placeholder_resolves_from_the_environment(monkeypatch):
    """A spec names its bucket by variable, so no project's bucket is committed."""
    monkeypatch.setenv("SOME_OUTPUT_BUCKET", "some-bucket")
    binding = registry.BucketRoles("${SOME_OUTPUT_BUCKET}", ("roles/storage.objectAdmin",))
    assert binding.resolved_bucket() == "gs://some-bucket"

    # Unset resolves to nothing rather than to a guessed name.
    monkeypatch.delenv("SOME_OUTPUT_BUCKET", raising=False)
    assert binding.resolved_bucket() == ""


def test_environment_overrides_the_declared_roles(monkeypatch):
    """An environment can still grant something the repository should not name."""
    import sys

    sys.path.insert(0, str(DEV))
    from deploy.iam.apply_agent_identity_iam import requested_project_roles

    spec = registry.get_agent_spec("vendor_match_agent")
    monkeypatch.setenv(f"{spec.env_prefix}_AGENT_IDENTITY_PROJECT_ROLES", "roles/logging.logWriter")
    assert requested_project_roles(spec) == ("roles/logging.logWriter",)


def test_every_environment_variable_is_documented():
    """A setting the code reads but no example mentions cannot be configured.

    Someone deploying from a clean clone has only the example files to work
    from, so an undocumented variable is a silent gap in the setup.
    """

    repo = DEV.parent
    roots = [repo / d for d in ("deployment", "packages", "agents")]
    pattern = re.compile(r'os\.(?:getenv|environ)(?:\.get)?\(\s*"([A-Z][A-Z0-9_]+)"')
    used: set[str] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            used.update(pattern.findall(path.read_text(encoding="utf-8")))

    from config.main_config import SETTINGS

    documented: set[str] = {setting.env for setting in SETTINGS}
    # Set inside each runtime from config.yaml values, by the registry.
    documented.update(key for spec in registry.AGENTS.values() for key, _ in spec.runtime_env)
    for name in ("config.example.yaml", ".env.local.example"):
        text = (DEV / name).read_text(encoding="utf-8")
        documented.update(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.MULTILINE))
        # Names shown inside prose, such as the <AGENT>_ prefixed families.
        documented.update(re.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", text))

    # Supplied by Agent Runtime rather than by the operator.
    supplied_by_platform = {"GOOGLE_CLOUD_AGENT_ENGINE_ID"}
    # Per-agent variables are derived from a package name at runtime.
    derived = {name for name in used if name.startswith("DEV_")}

    missing = used - documented - supplied_by_platform - derived
    assert not missing, f"environment variables the code reads but no example documents: {missing}"


def test_the_example_config_lists_every_setting_and_loads():
    """config.example.yaml is the schema people copy; it must cover and match the loader."""
    from config.main_config import SETTINGS, read_main_config

    example = DEV / "config.example.yaml"
    config = read_main_config(example)
    text = example.read_text(encoding="utf-8")
    for setting in SETTINGS:
        leaf = setting.path.rsplit(".", 1)[-1]
        assert f"{leaf}:" in text, f"{setting.path} is missing from config.example.yaml"
    assert set(config.oauth_clients) <= set(registry.AGENTS)


def test_unknown_config_keys_are_rejected(tmp_path):
    from config.main_config import read_main_config

    path = tmp_path / "config.yaml"
    path.write_text("environment:\n  projectid: typo\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"environment\.projectid"):
        read_main_config(path)


def test_a_structured_setting_reaches_the_runtime_as_json(tmp_path):
    """settings_override is a mapping in config.yaml and one JSON variable at runtime."""
    import json

    from config.main_config import read_main_config

    path = tmp_path / "config.yaml"
    path.write_text(
        "agents:\n"
        "  growth_analysis_workflow:\n"
        "    settings_override:\n"
        "      sheet_reader_agent:\n"
        "        column_aliases: {Kitchen Name: Store}\n",
        encoding="utf-8",
    )
    value = read_main_config(path).values["GROWTH_SETTINGS_OVERRIDE"]
    expected = {"sheet_reader_agent": {"column_aliases": {"Kitchen Name": "Store"}}}
    assert json.loads(value) == expected


def test_the_shell_overrides_the_config_file(tmp_path, monkeypatch):
    from config.main_config import load_main_config

    path = tmp_path / "config.yaml"
    path.write_text(
        "environment:\n  project_id: from-file\n  region: us-east1\n"
        "atlassian:\n  site_url: https://x.atlassian.net\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "from-shell")
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.delenv("JIRA_API_BASE_URL", raising=False)
    load_main_config(path)
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "from-shell"
    assert os.environ["GOOGLE_CLOUD_LOCATION"] == "us-east1"
    assert os.environ["JIRA_API_BASE_URL"] == "https://x.atlassian.net"


def test_baseline_roles_match_the_platform_stack():
    from deploy.iam.apply_agent_identity_iam import BASELINE_AGENT_IDENTITY_ROLES

    policy = json.loads((DEV.parent / "infrastructure/runtime_iam_policy.json").read_text())
    assert set(BASELINE_AGENT_IDENTITY_ROLES) == set(policy["baseline_project_roles"])
    assert "roles/storage.objectViewer" not in BASELINE_AGENT_IDENTITY_ROLES


def test_every_secret_an_agent_reads_is_created_by_terraform():
    """A drifted secret ID deploys cleanly and only fails when the tool runs."""
    example = (DEV.parent / "infrastructure/terraform.tfvars.example").read_text()
    created = set(re.findall(r'secret_id\s*=\s*"([^"]+)"', example))
    read = {
        grant.secret
        for spec in registry.AGENTS.values()
        for grant in spec.agent_identity_secret_roles
    }
    assert read, "no agent declares a secret; this test would prove nothing"
    assert read <= created, f"secrets agents read but Terraform does not create: {read - created}"


def test_baseline_grant_is_off_unless_requested(monkeypatch):
    """A managed project must never be granted IAM behind Terraform's back."""
    import sys

    sys.path.insert(0, str(DEV))
    import deploy.iam.apply_agent_identity_iam as agent_iam

    monkeypatch.delenv(agent_iam.BASELINE_ROLES_ENV, raising=False)
    calls = Mock()
    monkeypatch.setattr(agent_iam, "_run_gcloud", calls)
    assert agent_iam.ensure_baseline_roles("test-project") == ()
    calls.assert_not_called()


def test_baseline_grant_targets_every_agent_identity(monkeypatch):
    """The grant must reach runtimes that do not exist yet.

    Granting to one runtime's identity would mean every new agent needed an IAM
    change, which is the coupling the principal set exists to avoid.
    """
    import sys

    sys.path.insert(0, str(DEV))
    import deploy.iam.apply_agent_identity_iam as agent_iam

    monkeypatch.setattr(agent_iam, "_project_number", lambda project: "123456789")
    monkeypatch.setattr(agent_iam, "_organization_id", lambda project: None)
    principal_set = agent_iam.agent_identity_principal_set("test-project")

    assert principal_set.startswith("principalSet://")
    # Orgless uses "proj-": IAM rejects the documented "project-" spelling.
    assert "agents.global.proj-123456789.system.id.goog" in principal_set
    assert "attribute.platformContainer" in principal_set


def test_declared_runtime_env_resolves_placeholders(monkeypatch):
    """A spec names an environment's IDs by variable; empty ones are left out."""
    monkeypatch.setenv("SOME_FOLDER", "folder-123")
    monkeypatch.setenv("UNSET_FOLDER", "REPLACE_WITH_FOLDER")
    declared = (
        ("FOLDER", "${SOME_FOLDER}"),
        ("OTHER", "${UNSET_FOLDER}"),
        ("FIXED", "literal"),
    )
    assert settings.resolve_declared_env(declared) == {"FOLDER": "folder-123", "FIXED": "literal"}


def test_unresolved_runtime_env_is_reported(monkeypatch):
    spec = registry.get_agent_spec("vendor_match_agent")
    for _, value in spec.runtime_env:
        monkeypatch.delenv(value[2:-1], raising=False)
    assert "VENDOR_MATCH_DRIVE_SOURCE_FOLDER_ID" in settings.unresolved_declared_env(spec)
    monkeypatch.setenv("VENDOR_MATCH_DRIVE_SOURCE_FOLDER_ID", "abc")
    assert "VENDOR_MATCH_DRIVE_SOURCE_FOLDER_ID" not in settings.unresolved_declared_env(spec)
