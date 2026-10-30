"""Growth analysis: a store-performance diagnostic as a fixed three-stage pipeline.

    research_stage   -> state["research_bundle"]  (code: the store workbook, then
                        weather, reviews, macro/labor, industry and local news for
                        the stores behind, all at once)
    diagnosis_agent  -> state["diagnosis"]        (one structured-output model call
                        that fills every section of every store's diagnosis)
    report_generation-> PDF report (TL;DR, cohort tables, outside factors,
                        store-by-store detail), emailed to the growth team

One model call per run: everything else is computed in code, so every number is
exact and a run takes a few minutes. Each stage posts a short progress message.

Ported from the dev team's Growth Analytics V2: the tools, report layout and
per-stage settings under resources/ are theirs. The outside sources serve fixed
sample data unless GROWTH_LIVE_EXTERNAL_DATA=true (tools/sample_external.py).
"""

from __future__ import annotations

from gemini_shared.runtime import create_app
from google.adk.agents import SequentialAgent

from .config import BOOTSTRAP
from .stages import diagnosis_agent, report_generation_agent, research_stage

root_agent = SequentialAgent(
    name="growth_analysis_workflow",
    sub_agents=[research_stage, diagnosis_agent, report_generation_agent],
    description="End-to-end store performance diagnostic for the kitchen portfolio.",
)

# Agent Runtime serves the AdkApp wrapper, not a bare agent.
app = create_app(root_agent, BOOTSTRAP)
