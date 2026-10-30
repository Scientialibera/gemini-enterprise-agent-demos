"""Create or update no-code agents in a Gemini Enterprise app from agents/no_code/."""

from __future__ import annotations

import sys
from pathlib import Path

# Runnable directly as well as imported by run.py, so deployment/ has to be
# on sys.path either way: running this file puts only its own folder there.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import os

from config.settings import load_environment, require_deploy_environment
from paths import ROOT

from deploy.no_code.connectors import ResolvedConnector, list_connectors, resolve
from deploy.no_code.spec import LOW_CODE_KEY, NoCodeSpec, load_spec, no_code_agent_names
from deploy.register.access_groups import prepare_access_group
from deploy.register.agent_sharing import check_sharing, share_agent
from deploy.register.api_http import discovery_url, iter_resources, request
from deploy.register.group_config import group_config
from deploy.register.register_agent import APP_ENGINE_ID_ENV, _agents_url

ROOT_NODE_ID = "root_agent"
# Display names of agents this process saved a change for that still needs publishing.
PENDING_PUBLISH: list[str] = []


def build_agent(spec: NoCodeSpec, connectors: tuple[ResolvedConnector, ...]) -> dict:
    """The agent resource, in the shape the agent designer itself saves."""
    node: dict[str, object] = {
        "description": spec.description,
        "model": spec.model,
        "instruction": spec.render_prompt(),
        "googleSearchDisabled": not spec.google_search,
    }
    stores = [store for connector in connectors for store in connector.data_stores]
    if stores:
        node["dataStoreSpecs"] = {"specs": [{"dataStore": store} for store in stores]}
    if connectors:
        node["dataConnectors"] = [
            {"name": f"{c.collection}/dataConnector", "dataSource": c.data_source}
            for c in connectors
        ]
    nodes = [{"id": ROOT_NODE_ID, "displayName": spec.display_name, "llmAgentNode": node}]
    prompts = [{"text": prompt} for prompt in spec.starter_prompts]
    agent: dict[str, object] = {
        "displayName": spec.display_name,
        "description": spec.description,
        LOW_CODE_KEY: {
            "nodes": nodes,
            "rootAgentId": ROOT_NODE_ID,
            # Draft only: the API cannot publish. The designer's Create/Update copies
            # the draft to deployedNodes; writing deployedNodes here too would make
            # the draft look already published, and the designer would offer nothing.
            "draftDisplayName": spec.display_name,
            "draftDescription": spec.description,
            "draftStarterPrompts": prompts,
        },
    }
    if prompts:
        agent["starterPrompts"] = prompts
    return agent


def _find_existing(project_id: str, app_id: str, display_name: str) -> dict | None:
    for agent in iter_resources(_agents_url(project_id, app_id), project_id, "agents"):
        if agent.get("displayName") != display_name:
            continue
        if LOW_CODE_KEY not in agent:
            raise SystemExit(
                f"An agent named '{display_name}' already exists and is not a no-code agent. "
                "Rename one of them; refusing to overwrite it."
            )
        return agent
    return None


def deploy_no_code_agent(name: str, project_id: str, app_id: str, recreate: bool = False) -> str:
    """Create or update one no-code agent and return its resource name.

    recreate deletes an existing agent of the same name first. Use it after changing
    an agent's connectors: Gemini Enterprise keeps the connectors an agent had when it
    was first published, and later updates change only its instruction and model.
    """
    spec = load_spec(name)
    group_name = spec.name.replace("_", "-")
    group_config(project_id, app_id, group_name)
    access_group = prepare_access_group(project_id, app_id, group_name)

    available = list_connectors(project_id)
    resolved = []
    for ref in spec.connectors:
        try:
            resolved.append(resolve(ref, available, spec.name))
        except SystemExit as missing:
            if not ref.optional:
                raise
            print(f"WARNING=optional connector skipped: {missing}")
    connectors = tuple(resolved)
    for connector in connectors:
        print(f"CONNECTOR={spec.name}:{connector.data_source}:{connector.collection}")

    agent = build_agent(spec, connectors)
    if access_group:
        agent["sharingConfig"] = {"scope": "RESTRICTED"}

    existing = _find_existing(project_id, app_id, spec.display_name)
    if existing and recreate:
        old = discovery_url(existing["name"])
        request("DELETE", old, project_id)
        print(f"DELETED_NO_CODE_AGENT={existing['name']}")
        existing = None
    if existing:
        url = discovery_url(existing["name"])
        if access_group:
            check_sharing(url, project_id)
        from deploy.no_code.sync import differences, live_definition

        published = live_definition(existing)
        if published is not None and not differences(spec, published):
            # Nothing to publish: leave the agent untouched rather than saving a
            # draft that would only ask someone to click Update for no change.
            print(f"NO_CODE_UP_TO_DATE={spec.display_name}: published copy matches the repository.")
            if access_group:
                share_agent(url, project_id, access_group)
            return str(existing["name"])
        result = request("PATCH", url, project_id, agent)
        print(f"UPDATED_NO_CODE_AGENT={result.get('name')}")
    else:
        result = request("POST", _agents_url(project_id, app_id), project_id, agent)
        print(f"REGISTERED_NO_CODE_AGENT={result.get('name')}")
    resource = result.get("name")
    if not isinstance(resource, str) or "/agents/" not in resource:
        raise ValueError("The agents API returned no agent resource; inspect before retrying.")

    url = discovery_url(resource)
    # Chat keeps serving the last published version until the draft is published.
    # Google exposes no API for that: the designer's Create/Update button calls an
    # endpoint only its own web session can reach. So a real change ends here.
    button = "Update" if existing else "Create"
    web_app = os.getenv("GEMINI_ENTERPRISE_WEB_APP_URL", "").rstrip("/")
    where = (
        f"{web_app}/r/agent-builder/{resource.rsplit('/', 1)[-1]}"
        if web_app
        else f"Gemini Enterprise > Agents > {spec.display_name} > Edit"
    )
    PENDING_PUBLISH.append(spec.display_name)
    print(
        f"ACTION_REQUIRED={spec.display_name}: publish the change: open {where} and click {button}."
    )
    if access_group:
        share_agent(url, project_id, access_group)
    return resource


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or update no-code agents in a Gemini Enterprise app."
    )
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--agent", help="Folder name under agents/no_code/.")
    choice.add_argument("--all", action="store_true", help="Every folder under agents/no_code/.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate an existing agent. Needed after changing its connectors.",
    )
    parser.add_argument(
        "--app-id",
        default=None,
        help=f"Gemini Enterprise app (engine) id. Defaults to ${APP_ENGINE_ID_ENV}.",
    )
    sync = parser.add_mutually_exclusive_group()
    sync.add_argument(
        "--diff",
        action="store_true",
        help="Report where the live agent differs from the repository; change nothing.",
    )
    sync.add_argument(
        "--export",
        action="store_true",
        help="Write the live agent (designer edits) into agent.yaml and prompt.md.",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="With --diff or --export, use the unpublished draft instead of the published copy.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, _, _ = require_deploy_environment(require_parameter=False)
    app_id = (args.app_id or os.getenv(APP_ENGINE_ID_ENV, "")).strip()
    if not app_id:
        raise SystemExit(
            f"Set {APP_ENGINE_ID_ENV} (gemini_enterprise.app_id in deployment/config.yaml) "
            "or pass --app-id."
        )

    names = no_code_agent_names() if args.all else (args.agent,)
    for name in names:
        if args.diff or args.export:
            sync_no_code_agent(name, project_id, app_id, export=args.export, draft=args.draft)
        else:
            deploy_no_code_agent(name, project_id, app_id, recreate=args.recreate)


def live_agent(spec: NoCodeSpec, project_id: str, app_id: str, *, draft: bool = False):
    """The agent's live definition in the app, or None if it is not there or unpublished."""
    from deploy.no_code.sync import live_definition

    existing = _find_existing(project_id, app_id, spec.display_name)
    return live_definition(existing, draft=draft) if existing else None


def sync_no_code_agent(
    name: str, project_id: str, app_id: str, *, export: bool, draft: bool = False
) -> list[str]:
    """Report drift between the app and the repository; with export, pull it into the repo."""
    from deploy.no_code.sync import differences, export_definition

    spec = load_spec(name)
    copy = "draft" if draft else "published copy"
    live = live_agent(spec, project_id, app_id, draft=draft)
    if live is None:
        print(f"NO_CODE_SYNC={name}: no {copy} in the app; nothing to compare.")
        return []
    changed = differences(spec, live)
    if not changed:
        print(f"NO_CODE_SYNC={name}: the {copy} matches the repository.")
        return []
    print(f"NO_CODE_DRIFT={name}: the {copy} differs in {', '.join(changed)}.")
    if export:
        written = export_definition(spec, live)
        print(
            f"NO_CODE_EXPORTED={name}: {', '.join(written) or 'no file changes'}; "
            "review and commit."
        )
        if "connectors" in changed:
            print(
                f"NOTE={name}: connectors differ (live: {', '.join(live.data_sources) or 'none'}); "
                "update the connectors in agent.yaml by hand."
            )
    return changed


if __name__ == "__main__":
    main()
