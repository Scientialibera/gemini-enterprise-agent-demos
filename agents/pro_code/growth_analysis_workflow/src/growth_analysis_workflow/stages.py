"""The workflow's three stages: gather in code, diagnose in one model call, report in code.

    research_stage   reads the workbook and all five outside sources directly, in
                     parallel, and publishes one bundle to state["research_bundle"]
    diagnosis_agent  one structured-output model call over the bundle that fills
                     every section of every store's diagnosis (``Diagnosis``); the
                     TL;DR, outside-factors table and full report render from it
    report_stage     builds the PDF from that JSON and emails it

Each stage posts a short message as it finishes, so the chat still shows the run's
progress. The diagnosis instruction can be overridden live through
``stage_instructions["diagnosis_agent"]`` in the workflow's runtime parameter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import typing
from collections.abc import AsyncGenerator, Callable
from typing import Any

from gemini_shared import get_runtime_config, with_user_credentials
from gemini_shared.runtime import create_genai_client
from google.adk.agents import BaseAgent
from google.adk.agents.context import Context
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import BaseModel, Field, TypeAdapter

from .config import BOOTSTRAP, USER_AUTHORIZATION_ID
from .config_loader import load_prompt_config
from .tools.google_places_tool import fetch_google_reviews_batch
from .tools.local_news_tool import fetch_local_news_batch
from .tools.macro_labor_tool import fetch_macro_labor_batch
from .tools.qsr_news_tool import fetch_qsr_industry_news_batch
from .tools.report_pdf_tool import generate_sss_performance_report_pdf
from .tools.sheet_reader_tool import fetch_top_and_bottom_performing_stores
from .tools.weather_tool import fetch_weather_batch

logger = logging.getLogger(__name__)

SSS_COLUMN = "L6W SSS or YoY (Kitchen + MP)"
NAME_COLUMN = "Kitchen Name"
# The diagnosis writes a long report in one call; give it more room than the
# default per-call limit before the timeout-and-retry applies.
DIAGNOSIS_TIMEOUT_MS = 300_000

# Each outside source, the workbook key listing the stores it covers, and its label.
SOURCES: tuple[tuple[str, Callable[..., Any], str], ...] = (
    ("weather", fetch_weather_batch, "bottom_5_weather_agent_input"),
    ("reviews", fetch_google_reviews_batch, "bottom_5_google_reviews_agent_input"),
    ("macro_labor", fetch_macro_labor_batch, "bottom_5_macro_labor_agent_input"),
    ("industry_news", fetch_qsr_industry_news_batch, "bottom_5_qsr_market_research_agent_input"),
    ("local_news", fetch_local_news_batch, "bottom_5_local_news_agent_input"),
)


def _as_user(tool: Callable[..., object]) -> Callable[..., object]:
    """Bind the signed-in user's credentials when the workflow has an authorization.

    Without one, the tool runs as the runtime's own Agent Identity.
    """
    if not USER_AUTHORIZATION_ID:
        return tool
    return with_user_credentials(USER_AUTHORIZATION_ID)(tool)


def _message(agent: BaseAgent, ctx: InvocationContext, text: str, context: Context | None = None):
    """A progress message; pass the stage's context on its last one to commit its state.

    Gemini Enterprise joins a run's messages into one reply, so each ends with a
    blank line to keep them as separate paragraphs.
    """
    return Event(
        author=agent.name,
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
        content=types.Content(role="model", parts=[types.Part(text=text.rstrip() + "\n\n")]),
        actions=context.actions if context else EventActions(),
    )


def _store_inputs(tool: Callable[..., Any], stores: list[dict[str, Any]]) -> Any:
    """The workbook's store rows as the tool's own input model, with an id on each."""
    rows = [{**store, "store_id": store.get("store_name") or store.get("city")} for store in stores]
    annotation = typing.get_type_hints(tool).get("stores")
    return TypeAdapter(annotation).validate_python(rows) if annotation else rows


def _bottom_rows(workbook: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *(workbook.get("bottom_5_18mo_stores") or []),
        *(workbook.get("bottom_3_15mo_stores") or []),
    ]


def _tool_call(agent: BaseAgent, ctx: InvocationContext, call_id: str, name: str, args: dict):
    """A tool-call event, so the chat's thinking steps list each data fetch."""
    call = types.FunctionCall(id=call_id, name=name, args=args)
    return Event(
        author=agent.name,
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
        content=types.Content(role="model", parts=[types.Part(function_call=call)]),
    )


def _tool_result(agent: BaseAgent, ctx: InvocationContext, call_id: str, name: str, result):
    """The matching result event; the payload is what the fetch returned."""
    body = result if isinstance(result, dict) else {"result": result}
    response = types.FunctionResponse(id=call_id, name=name, response=body)
    return Event(
        author=agent.name,
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
        content=types.Content(role="user", parts=[types.Part(function_response=response)]),
    )


class ResearchStage(BaseAgent):
    """Reads the workbook, then all five outside sources at once; no model involved.

    The fetches are made in code, not chosen by a model, but each is still posted
    as a tool call and its result so the chat's thinking steps show every API used.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        context = Context(ctx)
        read_name = fetch_top_and_bottom_performing_stores.__name__
        read_id = f"{ctx.invocation_id}-{read_name}"
        yield _tool_call(self, ctx, read_id, read_name, {})
        read = _as_user(fetch_top_and_bottom_performing_stores)
        raw = await asyncio.to_thread(read, tool_context=context)
        workbook = json.loads(raw)
        yield _tool_result(self, ctx, read_id, read_name, workbook)
        if workbook.get("status") != "success":
            raise RuntimeError(f"Could not read the store workbook: {workbook.get('message')}")

        bottom = _bottom_rows(workbook)
        lagging = ", ".join(f"{row.get(NAME_COLUMN)} ({row.get(SSS_COLUMN)})" for row in bottom)
        yield _message(
            self,
            ctx,
            f"Read the store workbook: {len(bottom)} stores are behind last year: {lagging}.",
        )

        calls = []
        for _, tool, key in SOURCES:
            stores = workbook.get(key) or []
            call_id = f"{ctx.invocation_id}-{tool.__name__}"
            calls.append((call_id, tool.__name__))
            names = [s.get("store_name") or s.get("city") for s in stores]
            yield _tool_call(self, ctx, call_id, tool.__name__, {"stores": names})
        results = await asyncio.gather(
            *(
                asyncio.to_thread(tool, _store_inputs(tool, workbook.get(key) or []))
                for _, tool, key in SOURCES
            )
        )
        for (call_id, name), result in zip(calls, results, strict=True):
            yield _tool_result(self, ctx, call_id, name, result)
        outside = {name: result for (name, _, _), result in zip(SOURCES, results, strict=True)}
        bundle = {
            "underperforming_stores": workbook.get("tldr_store_evaluations", []),
            "cohort_tables": {
                "bottom_18_month": workbook.get("bottom_5_18mo_stores", []),
                "bottom_15_month": workbook.get("bottom_3_15mo_stores", []),
                "top_18_month": workbook.get("top_5_18mo_stores", []),
            },
            "outside_data": outside,
        }
        context.state["research_bundle"] = json.dumps(bundle, default=str)

        weather_days = max(
            (w.get("total_anomalous_days", 0) for w in outside["weather"].values()), default=0
        )
        yield _message(
            self,
            ctx,
            f"Gathered outside data for {len(bottom)} stores: weather (up to {weather_days} "
            f"unusual days), Google reviews for {len(outside['reviews'])} stores, state labor "
            f"data, {outside['industry_news'].get('total_articles_ingested', 0)} industry "
            f"articles and {outside['local_news'].get('total_articles_found', 0)} local stories.",
            context,
        )


class Finding(BaseModel):
    summary: str = Field(description="One short sentence for the executive summary.")
    detail: str = Field(description="Two or three sentences of evidence-based analysis.")


class StoreDiagnosis(BaseModel):
    """Every section of one store's diagnosis, as the report lays them out."""

    store_name: str = Field(
        description='Store name exactly as in the bundle, e.g. "Uptown Kitchen".'
    )
    location: str = Field(description='City and state, e.g. "Dallas, TX".')
    tldr_funnel: str = Field(
        description="TL;DR bullet: addressable households, 1P digital traffic and conversion; "
        "benchmark inline for any deficit metric; bold numbers; ends with owner tags like @growth."
    )
    tldr_channel_mix: str = Field(
        description="TL;DR bullet: 3P GOV share, marketplace mix, new brand mix; same rules."
    )
    tldr_sentiment_sla: str = Field(
        description="TL;DR bullet: Google rating and each named operational deficit vs benchmark; "
        "bold numbers; ends with owner tags."
    )
    external_analysis: str = Field(description="One sentence: the 1-2 key outside headwinds.")
    recommendation: str = Field(description="One actionable line.")
    internal_metrics: Finding
    customer_sentiment: Finding
    weather: Finding
    unemployment: Finding
    qsr_trends: Finding
    fast_casual_trends: Finding
    local_news: Finding
    local_restaurant_news: Finding
    actions: list[str] = Field(description="Two or three specific actions, each one sentence.")


class Diagnosis(BaseModel):
    stores: list[StoreDiagnosis] = Field(description="One entry per underperforming store.")


# (heading in the report, StoreDiagnosis field)
FINDINGS = (
    ("Internal Metrics", "internal_metrics"),
    ("Customer Sentiment & Reviews", "customer_sentiment"),
    ("Weather trends", "weather"),
    ("Unemployment", "unemployment"),
    ("QSR Trends in Region", "qsr_trends"),
    ("Fast Casual Trends", "fast_casual_trends"),
    ("Local news", "local_news"),
    ("Local Restaurant news", "local_restaurant_news"),
)


def _bullet(text: str) -> str:
    return "• " + text.strip().lstrip("•*- ").strip()


def render_report_inputs(diagnosis: Diagnosis) -> dict[str, Any]:
    """The TL;DR markdown, the outside-factors rows and the full report, from the sections."""
    tldr, summary, detailed, rows = [], [], [], []
    for store in diagnosis.stores:
        title = f"{store.store_name} ({store.location})"
        tldr += [
            f"### {store.store_name}",
            f"  • {store.tldr_funnel}",
            f"  • {store.tldr_channel_mix}",
            f"  • {store.tldr_sentiment_sla}",
            f"  • **External Analysis:** {store.external_analysis}",
            f"  • **Recommendation:** {store.recommendation}",
            "",
        ]
        summary += [f"### {title}"]
        summary += [f"* **{h}**: {getattr(store, f).summary}" for h, f in FINDINGS]
        summary += [f"* **Recommendations**: {store.recommendation}", ""]
        detailed += [f"## {title}", "### Key Insights"]
        detailed += [f"* **{h}**: {getattr(store, f).detail}" for h, f in FINDINGS]
        detailed += ["### Recommendations", *(f"* {a}" for a in store.actions), ""]
        rows.append(
            {
                "store_name": title,
                "qsr_trends": _bullet(store.qsr_trends.summary),
                "weather_trends": _bullet(store.weather.summary),
                "unemployment": _bullet(store.unemployment.summary),
                "customer_sentiment": _bullet(store.customer_sentiment.summary),
                "recommendations": _bullet(store.recommendation),
            }
        )
    report = "\n".join(
        [
            "## Executive Summary (Concise Diagnosis)",
            *summary,
            "## Detailed Store Diagnostics",
            *detailed,
        ]
    )
    return {
        "tldr_markdown": "\n".join(tldr).strip(),
        "macro_rows": rows,
        "full_markdown_report": report,
    }


class DiagnosisAgent(BaseAgent):
    """One structured-output model call fills every section of every store's diagnosis."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        context = Context(ctx)
        bundle = ctx.session.state.get("research_bundle", "{}")
        stores = len(json.loads(bundle).get("underperforming_stores", []))
        yield _message(self, ctx, f"Diagnosing all {stores} stores in one pass...")

        config = get_runtime_config()
        instruction = config.stage_instructions.get(self.name, "").strip() or (
            load_prompt_config().get(self.name, {}).get("instruction", "")
        )
        response = await create_genai_client(BOOTSTRAP).aio.models.generate_content(
            model=config.model,
            contents=f"{instruction}\n\nRESEARCH BUNDLE:\n{bundle}",
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=Diagnosis,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
                http_options=types.HttpOptions(timeout=DIAGNOSIS_TIMEOUT_MS),
            ),
        )
        parsed = response.parsed
        diagnosis = (
            parsed
            if isinstance(parsed, Diagnosis)
            else Diagnosis.model_validate_json(response.text)
        )
        context.state["diagnosis"] = render_report_inputs(diagnosis)

        actions = "\n".join(
            f"- **{store.store_name}**: {store.recommendation}" for store in diagnosis.stores
        )
        yield _message(self, ctx, f"Diagnosis ready. Recommended actions:\n{actions}", context)


class ReportStage(BaseAgent):
    """Builds the executive PDF from the diagnosis and emails it; no model involved."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        context = Context(ctx)
        diagnosis = ctx.session.state.get("diagnosis") or {}
        report = _as_user(generate_sss_performance_report_pdf)
        result = await report(
            macro_insights_text=diagnosis.get("full_markdown_report", ""),
            tool_context=context,
            tldr_text=diagnosis.get("tldr_markdown", ""),
            macro_rows=diagnosis.get("macro_rows") or [],
        )
        yield _message(self, ctx, str(result), context)


def _description(name: str) -> str:
    return load_prompt_config().get(name, {}).get("description", "")


research_stage = ResearchStage(
    name="research_stage",
    description="Reads the store workbook and every outside source for the stores behind.",
)
diagnosis_agent = DiagnosisAgent(
    name="diagnosis_agent", description=_description("diagnosis_agent")
)
report_generation_agent = ReportStage(
    name="report_generation_agent", description=_description("report_generation_agent")
)
