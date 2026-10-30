"""Designer edits come back into the repository, environment-free, with comments intact."""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

DEPLOYMENT = Path(__file__).resolve().parents[1] / "deployment"
sys.path.insert(0, str(DEPLOYMENT))
spec_module = importlib.import_module("deploy.no_code.spec")
sync = importlib.import_module("deploy.no_code.sync")


@pytest.fixture
def kitchen(tmp_path, monkeypatch):
    """A writable copy of the Kitchen Sequencer definition."""
    shutil.copytree(spec_module.NO_CODE_DIR / "kitchen_sequencer", tmp_path / "kitchen_sequencer")
    monkeypatch.setattr(spec_module, "NO_CODE_DIR", tmp_path)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "acme-prod")
    monkeypatch.setenv("KITCHEN_COMPLIANCE_DATASET", "kitchen_compliance")
    return spec_module.load_spec("kitchen_sequencer")


def _resource(spec, **node_overrides):
    node = {
        "description": spec.description,
        "model": spec.model,
        "instruction": spec.render_prompt(),
        "googleSearchDisabled": not spec.google_search,
        "dataConnectors": [{"dataSource": "custom_mcp"}],
        **node_overrides,
    }
    return {
        "description": spec.description,
        "starterPrompts": [{"text": p} for p in spec.starter_prompts],
        "lowCodeAgentDefinition": {"deployedNodes": [{"llmAgentNode": node}]},
    }


def test_a_matching_agent_has_no_drift(kitchen):
    live = sync.live_definition(_resource(kitchen))
    assert sync.differences(kitchen, live) == []


def test_drift_names_the_fields_that_changed(kitchen):
    live = sync.live_definition(
        _resource(kitchen, model="gemini-9-pro", instruction="Something else", dataConnectors=[])
    )
    assert sync.differences(kitchen, live) == ["model", "instruction", "connectors"]


def test_unpublished_agents_have_no_live_definition(kitchen):
    resource = _resource(kitchen)
    resource["lowCodeAgentDefinition"] = {"nodes": [{"llmAgentNode": {}}]}
    assert sync.live_definition(resource) is None
    assert sync.live_definition(resource, draft=True) is not None


def test_placeholders_are_restored_without_touching_lookalikes(kitchen):
    text = "Use `acme-prod.kitchen_compliance` and set projectId to acme-prod, never acme-prod-old."
    restored = sync.unrender(kitchen, text)
    assert restored == (
        "Use `${GOOGLE_CLOUD_PROJECT}.${KITCHEN_COMPLIANCE_DATASET}` and set projectId to "
        "${GOOGLE_CLOUD_PROJECT}, never acme-prod-old."
    )


def test_export_writes_designer_edits_and_keeps_comments(kitchen):
    edited = kitchen.render_prompt() + "\n\nAlways answer in a table."
    resource = _resource(kitchen, model="gemini-3.9-flash", instruction=edited)
    resource["starterPrompts"] = [{"text": "Show this week's scorecard."}]
    changed = sync.export_definition(kitchen, sync.live_definition(resource))
    assert changed == ["prompt.md", "agent.yaml"]

    prompt = kitchen.prompt_path.read_text(encoding="utf-8")
    assert prompt.rstrip().endswith("Always answer in a table.")
    assert "${GOOGLE_CLOUD_PROJECT}" in prompt and "acme-prod" not in prompt

    settings = (kitchen.folder / "agent.yaml").read_text(encoding="utf-8")
    assert settings.startswith("# No-code agent")  # comments survive
    reloaded = spec_module.load_spec("kitchen_sequencer")
    assert reloaded.model == "gemini-3.9-flash"
    assert reloaded.starter_prompts == ("Show this week's scorecard.",)
    assert reloaded.connectors == kitchen.connectors
    # The exported files describe the live agent exactly.
    assert sync.differences(reloaded, sync.live_definition(resource)) == []
