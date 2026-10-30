import importlib


def _base_env(monkeypatch):
    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("AGENT_INSTRUCTION", "test instruction")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")


def test_vendor_match_agent_imports(monkeypatch):
    _base_env(monkeypatch)
    module = importlib.import_module("vendor_match_agent.agent")
    assert module.root_agent.name == "vendor_master_data_governor"
    assert len(module.root_agent.tools) == 4


def test_ticket_guidance_agent_imports(monkeypatch):
    _base_env(monkeypatch)
    module = importlib.import_module("ticket_guidance_agent.agent")
    assert module.root_agent.name == "ticket_guidance_agent"
    assert len(module.root_agent.tools) == 4


def test_growth_analysis_workflow_imports(monkeypatch):
    _base_env(monkeypatch)
    module = importlib.import_module("growth_analysis_workflow.workflow")
    assert module.root_agent.name == "growth_analysis_workflow"
    assert [stage.name for stage in module.root_agent.sub_agents] == [
        "sheet_reader_agent",
        "external_intelligence_stage",
        "insights_agent",
        "report_generation_agent",
    ]


def test_vendor_match_reference_data_loads(monkeypatch):
    """The resources directory replaces the old project-root config/ and data/."""
    _base_env(monkeypatch)
    from vendor_match_agent.pipeline_config import load_config_set, load_prompt, load_yaml_config

    assert load_yaml_config()["orchestrator_agent"]["batching"]["chunk_size"] == 1000
    assert load_config_set("corporate_extensions.json")
    assert "{input_payload}" in load_prompt("resolution_user_prompt")
