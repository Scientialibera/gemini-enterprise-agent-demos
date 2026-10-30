"""Model selection follows live configuration without reconstructing agents."""

import asyncio
from types import SimpleNamespace

from gemini_shared.config.runtime_config import RuntimeConfig
from gemini_shared.limits import RuntimeLimitsPlugin
from google.adk.models.llm_request import LlmRequest


def config(model="text-a", image_model="image-a", **kwargs):
    return RuntimeConfig(
        config_revision="test", model=model, image_model=image_model, instruction="test", **kwargs
    )


def test_workflow_and_compaction_follow_live_model(monkeypatch):
    from gemini_shared import limits

    current = config()
    monkeypatch.setattr(limits, "get_runtime_config", lambda: current)
    plugin = RuntimeLimitsPlugin()
    for model in ("text-a", "text-b"):
        current = config(model=model)
        context = SimpleNamespace(run_config=None)
        asyncio.run(plugin.before_run_callback(invocation_context=context))
        assert context.events_compaction_config.summarizer._llm.model == model
        for name in ("sheet_reader_agent", "insights_agent", "report_generation_agent"):
            request = LlmRequest(model="bootstrap")
            asyncio.run(
                plugin.before_model_callback(
                    callback_context=SimpleNamespace(agent_name=name), llm_request=request
                )
            )
            assert request.model == model
