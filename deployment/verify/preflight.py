"""Preflight: what a deployment needs that only a person or the console can provide.

Each check prints OK or ACTION with where to fix it, and never changes
anything. The deploy still runs past an ACTION (everything is idempotent); the
summary lists what is left, which on a first run is usually console work.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from config.environment import configured_value
from deploy.register.api_http import discovery_url, request
from registry import AGENTS

ORG_POLICY = "discoveryengine.managed.disableCustomMcpServerConnector"
GUIDE = "docs/deployment-guide.md"


@dataclass(frozen=True, slots=True)
class Finding:
    ok: bool
    name: str
    detail: str


def _engine(project: str, app: str) -> dict:
    return request(
        "GET",
        discovery_url(
            f"projects/{project}/locations/global/collections/default_collection/engines/{app}"
        ),
        project,
    )


def check_app(project: str) -> Finding:
    app = configured_value("GEMINI_ENTERPRISE_APP_ID")
    if not app:
        return Finding(False, "Gemini Enterprise app", "set gemini_enterprise.app_id (step 2)")
    try:
        _engine(project, app)
    except SystemExit as exc:
        return Finding(False, "Gemini Enterprise app", f"{app} not found: {str(exc)[:120]}")
    return Finding(True, "Gemini Enterprise app", app)


def check_org_policy(project: str) -> Finding:
    url = (
        f"https://orgpolicy.googleapis.com/v2/projects/{project}/policies/{ORG_POLICY}"
        ":getEffectivePolicy"
    )
    try:
        policy = request("GET", url, project)
    except SystemExit as exc:
        return Finding(False, "Custom MCP org policy", f"cannot read it: {str(exc)[:120]}")
    enforced = any(rule.get("enforce") for rule in (policy.get("spec") or {}).get("rules", []))
    if enforced:
        return Finding(
            False, "Custom MCP org policy", f"enforced; set enforce: false ({GUIDE}, step 4)"
        )
    return Finding(True, "Custom MCP org policy", "not enforced")


def check_connectors(project: str) -> list[Finding]:
    from deploy.no_code.connectors import list_connectors

    connectors = list_connectors(project)
    sources = {c.get("dataSource") for c in connectors}
    findings = [
        Finding(
            "custom_mcp" in sources,
            "BigQuery MCP connector",
            "present" if "custom_mcp" in sources else f"create it ({GUIDE}, step 8)",
        )
    ]
    app = configured_value("GEMINI_ENTERPRISE_APP_ID")
    if app and "custom_mcp" in sources:
        linked = set(_engine(project, app).get("dataStoreIds", []))
        stores = {
            str(e.get("dataStore", "")).rsplit("/", 1)[-1]
            for c in connectors
            if c.get("dataSource") == "custom_mcp"
            for e in c.get("entities", [])
        }
        findings.append(
            Finding(
                bool(stores & linked),
                "BigQuery MCP data store in the app",
                "connected"
                if stores & linked
                else "Connected data stores > Add existing data stores",
            )
        )
    if os.getenv("TICKET_CONFLUENCE_SEARCH_BACKEND", "connector") == "connector":
        has = "confluence" in sources
        findings.append(
            Finding(
                has, "Confluence connector", "present" if has else f"create it ({GUIDE}, step 8)"
            )
        )
    return findings


def check_oauth_clients() -> list[Finding]:
    findings = []
    for name, spec in AGENTS.items():
        if not spec.uses_delegated_auth:
            continue
        from deploy.register.oauth import oauth_client_id_for

        client = oauth_client_id_for(name, spec)
        findings.append(
            Finding(
                bool(client),
                f"OAuth client: {name}",
                "configured" if client else f"add oauth_clients.{name} ({GUIDE}, step 5)",
            )
        )
    return findings


def check_secrets(project: str) -> list[Finding]:
    from google.cloud import secretmanager
    from seed.secrets import _has_version, declared_secret_ids

    client = secretmanager.SecretManagerServiceClient()
    findings = []
    for secret in declared_secret_ids():
        try:
            ok = _has_version(client, f"projects/{project}/secrets/{secret}")
        except Exception:
            ok = False
        findings.append(
            Finding(ok, f"Secret {secret}", "has a value" if ok else "missing or empty; run seed")
        )
    return findings


def check_no_code_drift(project: str) -> list[Finding]:
    """Whether each no-code agent users chat with matches the repository."""
    from deploy.no_code.deploy_no_code import live_agent
    from deploy.no_code.spec import load_spec, no_code_agent_names
    from deploy.no_code.sync import differences

    app = configured_value("GEMINI_ENTERPRISE_APP_ID")
    if not app:
        return []
    findings = []
    for name in no_code_agent_names():
        spec = load_spec(name)
        live = live_agent(spec, project, app)
        label = f"No-code agent {name}"
        if live is None:
            findings.append(Finding(False, label, "not published yet; run deploy, then Create"))
            continue
        changed = differences(spec, live)
        detail = (
            "published copy matches the repository"
            if not changed
            else f"published copy differs in {', '.join(changed)}: deploy and click Update to "
            f"push the repository, or `deploy_no_code.py --export --agent {name}` to pull "
            "designer edits into it"
        )
        findings.append(Finding(not changed, label, detail))
    return findings


def run_preflight(project: str) -> list[Finding]:
    groups: list[Callable[[], Finding | list[Finding]]] = [
        lambda: check_app(project),
        lambda: check_org_policy(project),
        lambda: check_connectors(project),
        check_oauth_clients,
        lambda: check_secrets(project),
        lambda: check_no_code_drift(project),
    ]
    findings: list[Finding] = []
    for group in groups:
        try:
            result = group()
        except Exception as exc:
            result = Finding(
                False, getattr(group, "__name__", "check"), f"{type(exc).__name__}: {exc}"
            )
        findings.extend(result if isinstance(result, list) else [result])
    for finding in findings:
        print(f"{'OK    ' if finding.ok else 'ACTION'}  {finding.name}: {finding.detail}")
    return findings
