"""One end-to-end check per agent. Each returns a short evidence line or raises CheckFailed."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable

import requests
from config.environment import env_bool
from config.settings import SHARED_ENVIRONMENTS, current_environment
from deploy.state import find_resource_name
from registry import get_agent_spec

from .session import Conversation, user_token

BIGQUERY_MCP = "https://bigquery.googleapis.com/mcp"
DOC_URL = re.compile(r"https://docs\.google\.com/document/d/[\w-]+")


class CheckFailed(RuntimeError):
    """The agent did not do what the check expects; the message says what happened."""


class CheckSkipped(RuntimeError):
    """The check is disabled in config.yaml or cannot run here; the message says why."""


def _conversation(agent: str) -> Conversation:
    project, region = os.environ["GOOGLE_CLOUD_PROJECT"], os.environ["GOOGLE_CLOUD_LOCATION"]
    resource = find_resource_name(agent, project, region)
    if not resource:
        raise CheckFailed(
            f"{agent} has no deployed runtime in {project}/{region}; deploy it first."
        )
    return Conversation(resource, get_agent_spec(agent).authorization_id)


def _require(condition: object, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


# Code agents


def vendor_match() -> str:
    # A vendor the environment's master dictionary holds; the sample one has Sysco Corp.
    vendor = os.getenv("TEST_VENDOR_LOOKUP", "").strip() or "Sysco Corp"
    turn = _conversation("vendor_match_agent").send(
        f"Look up the vendor '{vendor}' in the master vendor dictionary."
    )
    result = turn.result_of("lookup_master_dictionary_vendor")
    _require(result, f"the lookup tool was not called. Agent said: {turn.text[:300]}")
    status = result.get("status") if isinstance(result, dict) else None
    _require(status in {"found", "partial_matches_found"}, f"lookup returned {str(result)[:300]}")
    return f"dictionary lookup for '{vendor}': {status}"


def ticket_guidance() -> str:
    if current_environment() in SHARED_ENVIRONMENTS:
        # It creates a real ticket; in qa and prod check by hand (docs/prod-runbook.md).
        raise CheckSkipped("creates a real Jira ticket; not run in qa or prod")
    if not env_bool("TEST_TICKET_GUIDANCE_CREATES_TICKETS", True):
        raise CheckSkipped("tests.ticket_guidance_creates_tickets is false")
    chat = _conversation("ticket_guidance_agent")
    first = chat.send(
        "My VPN keeps saying authentication failed when I connect from home on my Windows laptop."
    )
    search = first.result_of("search_confluence_kb_tool")
    _require(
        isinstance(search, dict) and search.get("status") == "Success",
        f"knowledge base search failed: {str(search)[:300]}",
    )
    created = first.result_of("create_jira_ticket_tool")
    _require(
        isinstance(created, dict) and created.get("status") == "Success",
        f"no ticket was created: {str(created)[:300]}. Agent said: {first.text[:200]}",
    )
    key = created["issue_key"]
    second = chat.send("Yes, signing out and back in with my company email fixed it, thanks.")
    updated = second.result_of("update_jira_ticket_tool")
    _require(
        isinstance(updated, dict) and updated.get("status_transitioned_to"),
        f"{key} was not moved to Done: {str(updated)[:300]}",
    )
    articles = [a.get("title", "") for a in search.get("articles", [])]
    return (
        f"KB returned {len(articles)} article(s); ticket {key} created "
        f"(reporter {created.get('reporter')}) and moved to {updated['status_transitioned_to']}"
    )


REPORT_STATE_KEY = "report_generation_agent"
REPORT_WAIT_SECONDS = 30 * 60
REPORT_POLL_SECONDS = 30


def _await_report(conversation: Conversation) -> str:
    """The report stage's output, read from session state once the run finishes.

    A full run takes many minutes, and the stream to the workstation can drop
    while the runtime carries on. The run is judged by what it wrote, not by
    whether this connection stayed open.
    """
    deadline = time.monotonic() + REPORT_WAIT_SECONDS
    while True:
        report = str(conversation.state().get(REPORT_STATE_KEY) or "")
        if report or time.monotonic() >= deadline:
            return report
        time.sleep(REPORT_POLL_SECONDS)


def growth_analysis() -> str:
    if not env_bool("TEST_GROWTH_FULL_RUN", True):
        raise CheckSkipped("tests.growth_full_run is false")
    conversation = _conversation("growth_analysis_workflow")
    try:
        turn = conversation.send("Run the pipeline")
        output = str(turn.result_of("generate_sss_performance_report_doc") or "") + turn.text
    except Exception as exc:  # the stream, not the run: check what the run wrote
        print(f"NOTE=the stream ended early ({type(exc).__name__}); waiting for the report.")
        output = _await_report(conversation)
    match = DOC_URL.search(output)
    _require(
        match,
        "no report Doc was produced (see the runtime's logs for a 429 or a tool error). "
        f"Last output: {output[-300:]}",
    )
    return f"report written: {match.group(0)}"


def prompt_manager() -> str:
    """Read-only: list the agents' live configurations. Changing one needs a confirmation."""
    turn = _conversation("parameter_updater").send("List the agent configurations in this project.")
    result = turn.result_of("list_runtime_parameters")
    _require(
        isinstance(result, dict) and result.get("status") == "ok",
        f"listing failed: {str(result)[:300]}. Agent said: {turn.text[:200]}",
    )
    configs = [p["parameter"] for p in result.get("parameters", []) if p.get("runtime_config")]
    _require(configs, "no agent runtime configurations were found")
    return f"{len(configs)} agent configuration(s) readable: {', '.join(sorted(configs))}"


# No-code agents


def _published_definition(display_name: str) -> dict:
    from deploy.no_code.deploy_no_code import LOW_CODE_KEY, _find_existing

    project, app = os.environ["GOOGLE_CLOUD_PROJECT"], os.environ["GEMINI_ENTERPRISE_APP_ID"]
    agent = _find_existing(project, app, display_name)
    _require(agent, f"'{display_name}' is not in the app; run deploy.")
    nodes = agent.get(LOW_CODE_KEY, {}).get("deployedNodes") or []
    _require(nodes, f"'{display_name}' has never been published; click Create in the designer.")
    node = nodes[0].get("llmAgentNode", {})
    _require(node.get("dataConnectors"), f"'{display_name}' was published without its connector.")
    return node


def _bigquery_mcp(sql: str) -> list[dict]:
    """Run read-only SQL through the BigQuery MCP server, as the agents do."""
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    headers = {
        "Authorization": f"Bearer {user_token()}",
        "Accept": "application/json, text/event-stream",
        "x-goog-user-project": project,
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "execute_sql_readonly",
            "arguments": {"projectId": project, "query": sql},
        },
    }
    response = requests.post(BIGQUERY_MCP, headers=headers, json=body, timeout=120)
    _require(response.ok, f"BigQuery MCP returned HTTP {response.status_code}")
    text = response.text
    if "data:" in text:
        text = "\n".join(line[5:] for line in text.splitlines() if line.startswith("data:"))
    payload = json.loads(text)
    _require(not payload.get("error"), f"BigQuery MCP error: {str(payload.get('error'))[:300]}")
    result = payload.get("result", {})
    _require(not result.get("isError"), f"query failed: {str(result.get('content'))[:300]}")
    rows = (result.get("structuredContent") or {}).get("rows", [])
    return [[cell.get("v") for cell in row.get("f", [])] for row in rows]


def kitchen_sequencer() -> str:
    _published_definition("Kitchen Sequencer")
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    dataset = os.getenv("KITCHEN_COMPLIANCE_DATASET", "kitchen_compliance")
    # Project and dataset come from config.yaml, not from user input.
    table = f"`{project}.{dataset}.kitchen_compliance_scorecard_weekly`"
    rows = _bigquery_mcp(
        f"SELECT week_start, COUNT(*) FROM {table} "  # noqa: S608
        "GROUP BY week_start ORDER BY week_start DESC LIMIT 1"
    )
    _require(rows, "the scorecard table is empty")
    return (
        f"published with BigQuery MCP; latest scorecard week {rows[0][0]} has {rows[0][1]} kitchens"
    )


def recipe_editorial() -> str:
    _published_definition("Recipe Editorial Agent")
    dataset = os.getenv("RECIPE_PRODUCT_DATASET", "")
    _require(dataset, "agents.recipe_editorial_agent.product_dataset is not set")
    # The dataset comes from config.yaml, not from user input.
    rows = _bigquery_mcp(f"SELECT COUNT(*) FROM `{dataset}.culinary_products`")  # noqa: S608
    _require(rows and int(rows[0][0]) > 0, "the recipe product table is empty")
    return f"published with BigQuery MCP; {rows[0][0]} recipes readable"


CHECKS: dict[str, Callable[[], str]] = {
    "kitchen_sequencer": kitchen_sequencer,
    "recipe_editorial_agent": recipe_editorial,
    "vendor_match_agent": vendor_match,
    "ticket_guidance_agent": ticket_guidance,
    "growth_analysis_workflow": growth_analysis,
    "parameter_updater": prompt_manager,
}
