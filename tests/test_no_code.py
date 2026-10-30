"""No-code agents: definitions, prompt rendering, connectors and the API payload."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

DEV = Path(__file__).resolve().parents[1] / "deployment"
sys.path.insert(0, str(DEV))
spec_module = importlib.import_module("deploy.no_code.spec")
connectors = importlib.import_module("deploy.no_code.connectors")
deploy = importlib.import_module("deploy.no_code.deploy_no_code")
sys.path.remove(str(DEV))

NAMES = spec_module.no_code_agent_names()

BIGQUERY_MCP = {
    "name": "projects/1/locations/global/collections/bigquery-mcp_1/dataConnector",
    "dataSource": "custom_mcp",
    "params": {"instance_uri": "https://bigquery.googleapis.com/mcp"},
    "state": "ACTIVE",
    "entities": [{"dataStore": "projects/1/.../dataStores/bigquery-mcp_1_mcp_data"}],
}
OTHER_MCP = {
    "name": "projects/1/locations/global/collections/other-mcp_2/dataConnector",
    "dataSource": "custom_mcp",
    "params": {"instance_uri": "https://example.com/mcp"},
    "state": "ACTIVE",
    "entities": [{"dataStore": "projects/1/.../dataStores/other-mcp_2_mcp_data"}],
}
GMAIL = {
    "name": "projects/1/locations/global/collections/mail_3/dataConnector",
    "dataSource": "google_mail",
    "state": "ACTIVE",
    "entities": [{"dataStore": "projects/1/.../dataStores/mail_3_google_mail"}],
}


@pytest.fixture
def prompt_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "target-project")
    monkeypatch.setenv("KITCHEN_COMPLIANCE_DATASET", "kitchen_compliance")
    monkeypatch.setenv("RECIPE_PRODUCT_DATASET", "target-project.recipe_products")
    monkeypatch.setenv("RECIPE_LEGACY_DATASET", "target-project.recipe_legacy")


def test_both_migrated_no_code_agents_are_defined():
    assert set(NAMES) == {"kitchen_sequencer", "recipe_editorial_agent"}


@pytest.mark.parametrize("name", NAMES)
def test_every_definition_loads_and_renders(name, prompt_env):
    spec = spec_module.load_spec(name)
    prompt = spec.render_prompt()
    assert len(prompt) > 200
    for variable in spec.prompt_variables:
        assert f"${{{variable}}}" not in prompt
    assert spec.connectors, f"{name} has no connectors"


def test_prompts_name_only_the_target_project(prompt_env):
    """Every project.dataset.table a prompt names comes from the environment.

    A project written into the prompt text would send queries to an environment
    the deployment does not own.
    """
    import re

    # Table paths are backticked, escaped as \` in markdown prompts.
    table = re.compile(r"\\?`([A-Za-z0-9_-]+)\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+\\?`")
    for name in NAMES:
        prompt = spec_module.load_spec(name).render_prompt()
        assert "target-project" in prompt
        # "project" is the prompt describing the format (`project.dataset.table`).
        projects = {m.group(1) for m in table.finditer(prompt)} - {"project"}
        assert projects == {"target-project"}, (name, projects)


def test_kitchen_sequencer_reads_bigquery_not_looker(prompt_env):
    spec = spec_module.load_spec("kitchen_sequencer")
    assert [c.data_source for c in spec.connectors] == ["custom_mcp"]
    assert "Looker" not in spec.render_prompt()
    assert "target-project.kitchen_compliance" in spec.render_prompt()


def test_an_unset_prompt_variable_stops_deployment(monkeypatch):
    monkeypatch.delenv("KITCHEN_COMPLIANCE_DATASET", raising=False)
    with pytest.raises(SystemExit, match="KITCHEN_COMPLIANCE_DATASET"):
        spec_module.load_spec("kitchen_sequencer").render_prompt()


def test_unknown_names_are_rejected():
    with pytest.raises(SystemExit, match="Unknown no-code agent"):
        spec_module.load_spec("not_an_agent")
    with pytest.raises(SystemExit, match="lowercase"):
        spec_module.load_spec("../etc")


def test_connectors_match_by_type_and_server():
    ref = spec_module.ConnectorRef("custom_mcp", "https://bigquery.googleapis.com/mcp")
    resolved = connectors.resolve(ref, [OTHER_MCP, BIGQUERY_MCP, GMAIL], "agent")
    assert resolved.collection == "collections/bigquery-mcp_1"
    assert resolved.data_stores == ("projects/1/.../dataStores/bigquery-mcp_1_mcp_data",)


def test_a_missing_connector_explains_what_to_create():
    ref = spec_module.ConnectorRef("google_mail")
    with pytest.raises(SystemExit, match="google_mail connector"):
        connectors.resolve(ref, [BIGQUERY_MCP], "agent")


def test_ambiguous_connectors_must_be_chosen(monkeypatch):
    second = {**GMAIL, "name": GMAIL["name"].replace("mail_3", "gmail_4")}
    ref = spec_module.ConnectorRef("google_mail", collection_env="NO_CODE_GMAIL_CONNECTOR_ID")
    monkeypatch.delenv("NO_CODE_GMAIL_CONNECTOR_ID", raising=False)
    with pytest.raises(SystemExit, match="NO_CODE_GMAIL_CONNECTOR_ID"):
        connectors.resolve(ref, [GMAIL, second], "agent")
    monkeypatch.setenv("NO_CODE_GMAIL_CONNECTOR_ID", "gmail_4")
    assert connectors.resolve(ref, [GMAIL, second], "agent").collection == "collections/gmail_4"


def test_an_optional_connector_that_is_missing_is_skipped(monkeypatch, prompt_env, capsys):
    """Recipe Editorial still deploys without Gmail, e.g. on a non-Workspace account."""
    monkeypatch.setattr(deploy, "group_config", lambda *a: None)
    monkeypatch.setattr(deploy, "prepare_access_group", lambda *a: None)
    monkeypatch.setattr(deploy, "list_connectors", lambda project: [BIGQUERY_MCP])
    monkeypatch.setattr(deploy, "iter_resources", lambda *a: iter([]))
    request = Mock(side_effect=[{"name": "projects/1/agents/new"}, {"lowCodeAgentDefinition": {}}])
    monkeypatch.setattr(deploy, "request", request)
    deploy.deploy_no_code_agent("recipe_editorial_agent", "p", "app")
    node = request.call_args_list[0].args[3]["lowCodeAgentDefinition"]["nodes"][0]["llmAgentNode"]
    assert [c["dataSource"] for c in node["dataConnectors"]] == ["custom_mcp"]
    assert "optional connector skipped" in capsys.readouterr().out


def test_payload_matches_the_designers_shape(prompt_env):
    spec = spec_module.load_spec("recipe_editorial_agent")
    resolved = (
        connectors.resolve(spec.connectors[0], [BIGQUERY_MCP, GMAIL], spec.name),
        connectors.resolve(spec.connectors[1], [BIGQUERY_MCP, GMAIL], spec.name),
    )
    agent = deploy.build_agent(spec, resolved)
    definition = agent["lowCodeAgentDefinition"]
    node = definition["nodes"][0]["llmAgentNode"]
    assert definition["rootAgentId"] == definition["nodes"][0]["id"] == "root_agent"
    # Draft only: a written deployedNodes hides the change from the designer's Update.
    assert "deployedNodes" not in definition
    assert node["model"] == spec.model
    assert node["googleSearchDisabled"] is True
    assert [c["dataSource"] for c in node["dataConnectors"]] == ["custom_mcp", "google_mail"]
    assert node["dataConnectors"][0]["name"] == "collections/bigquery-mcp_1/dataConnector"
    assert len(node["dataStoreSpecs"]["specs"]) == 2


def test_an_existing_code_agent_with_the_same_name_is_not_overwritten(monkeypatch):
    monkeypatch.setattr(
        deploy,
        "iter_resources",
        lambda *a: iter([{"displayName": "Kitchen Sequencer", "adkAgentDefinition": {}}]),
    )
    with pytest.raises(SystemExit, match="not a no-code agent"):
        deploy._find_existing("p", "app", "Kitchen Sequencer")


def test_deploy_creates_then_reports_an_unpublished_draft(monkeypatch, prompt_env, capsys):
    monkeypatch.setattr(deploy, "group_config", lambda *a: None)
    monkeypatch.setattr(deploy, "prepare_access_group", lambda *a: None)
    monkeypatch.setattr(deploy, "list_connectors", lambda project: [BIGQUERY_MCP])
    monkeypatch.setattr(deploy, "iter_resources", lambda *a: iter([]))
    request = Mock(
        side_effect=[
            {"name": "projects/1/agents/new"},
            {"lowCodeAgentDefinition": {"nodes": []}},
        ]
    )
    monkeypatch.setattr(deploy, "request", request)

    assert deploy.deploy_no_code_agent("kitchen_sequencer", "p", "app") == "projects/1/agents/new"
    assert request.call_args_list[0].args[0] == "POST"
    assert "ACTION_REQUIRED" in capsys.readouterr().out


def test_recreate_deletes_the_existing_agent_first(monkeypatch, prompt_env, capsys):
    """Connector changes only take effect on an agent's first publish."""
    existing = {
        "name": "projects/1/agents/old",
        "displayName": "Kitchen Sequencer",
        "lowCodeAgentDefinition": {},
    }
    monkeypatch.setattr(deploy, "group_config", lambda *a: None)
    monkeypatch.setattr(deploy, "prepare_access_group", lambda *a: None)
    monkeypatch.setattr(deploy, "list_connectors", lambda project: [BIGQUERY_MCP])
    monkeypatch.setattr(deploy, "iter_resources", lambda *a: iter([existing]))
    request = Mock(side_effect=[{}, {"name": "projects/1/agents/new"}])
    monkeypatch.setattr(deploy, "request", request)

    deploy.deploy_no_code_agent("kitchen_sequencer", "p", "app", recreate=True)
    methods = [call.args[0] for call in request.call_args_list]
    assert methods == ["DELETE", "POST"]
    assert request.call_args_list[0].args[1].endswith("projects/1/agents/old")
    assert "click Create" in capsys.readouterr().out


def test_an_update_asks_for_the_designers_update_button(monkeypatch, prompt_env, capsys):
    existing = {
        "name": "projects/1/agents/old",
        "displayName": "Kitchen Sequencer",
        "lowCodeAgentDefinition": {},
    }
    monkeypatch.setattr(deploy, "group_config", lambda *a: None)
    monkeypatch.setattr(deploy, "prepare_access_group", lambda *a: None)
    monkeypatch.setattr(deploy, "list_connectors", lambda project: [BIGQUERY_MCP])
    monkeypatch.setattr(deploy, "iter_resources", lambda *a: iter([existing]))
    request = Mock(return_value={"name": "projects/1/agents/old"})
    monkeypatch.setattr(deploy, "request", request)

    deploy.deploy_no_code_agent("kitchen_sequencer", "p", "app")
    assert request.call_args_list[0].args[0] == "PATCH"
    assert "click Update" in capsys.readouterr().out


def _published(spec_name):
    """An agent resource whose published copy is exactly what the repository builds."""
    spec = spec_module.load_spec(spec_name)
    agent = deploy.build_agent(
        spec, (connectors.resolve(spec.connectors[0], [BIGQUERY_MCP], spec.name),)
    )
    definition = agent["lowCodeAgentDefinition"]
    definition["deployedNodes"] = definition["nodes"]
    return {"name": "projects/1/agents/old", **agent}


def test_an_unchanged_agent_is_left_alone(monkeypatch, prompt_env, capsys):
    """Nothing to publish means no draft and no request to click Update."""
    monkeypatch.setattr(deploy, "group_config", lambda *a: None)
    monkeypatch.setattr(deploy, "prepare_access_group", lambda *a: None)
    monkeypatch.setattr(deploy, "list_connectors", lambda project: [BIGQUERY_MCP])
    monkeypatch.setattr(
        deploy, "iter_resources", lambda *a: iter([_published("kitchen_sequencer")])
    )
    request = Mock()
    monkeypatch.setattr(deploy, "request", request)
    monkeypatch.setattr(deploy, "PENDING_PUBLISH", [])

    deploy.deploy_no_code_agent("kitchen_sequencer", "p", "app")
    request.assert_not_called()
    assert deploy.PENDING_PUBLISH == []
    assert "NO_CODE_UP_TO_DATE" in capsys.readouterr().out


def test_a_changed_agent_is_saved_and_listed_for_publishing(monkeypatch, prompt_env, capsys):
    published = _published("kitchen_sequencer")
    published["lowCodeAgentDefinition"]["deployedNodes"][0]["llmAgentNode"]["model"] = "older-model"
    monkeypatch.setattr(deploy, "group_config", lambda *a: None)
    monkeypatch.setattr(deploy, "prepare_access_group", lambda *a: None)
    monkeypatch.setattr(deploy, "list_connectors", lambda project: [BIGQUERY_MCP])
    monkeypatch.setattr(deploy, "iter_resources", lambda *a: iter([published]))
    request = Mock(return_value={"name": "projects/1/agents/old"})
    monkeypatch.setattr(deploy, "request", request)
    monkeypatch.setattr(deploy, "PENDING_PUBLISH", [])
    monkeypatch.setenv("GEMINI_ENTERPRISE_WEB_APP_URL", "https://example.test/home/cid/abc")

    deploy.deploy_no_code_agent("kitchen_sequencer", "p", "app")
    assert request.call_args_list[0].args[0] == "PATCH"
    assert deploy.PENDING_PUBLISH == ["Kitchen Sequencer"]
    assert "https://example.test/home/cid/abc/r/agent-builder/old" in capsys.readouterr().out
