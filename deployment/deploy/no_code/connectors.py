"""Find the Gemini Enterprise connectors a no-code agent refers to.

Connectors are created once per app in the console, because each one holds an
OAuth client or an admin consent that no API sets up. A no-code agent refers
to them by type, so the same agent.yaml works in any app: this module lists
the project's connector collections and resolves each reference to the
collection and data stores the agent definition needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.environment import configured_value

from deploy.no_code.spec import ConnectorRef
from deploy.register.api_http import discovery_url, iter_resources, request


@dataclass(frozen=True, slots=True)
class ResolvedConnector:
    collection: str  # collections/<id>, relative to the project location
    data_source: str
    data_stores: tuple[str, ...]


def _collections_url(project_id: str) -> str:
    return discovery_url(f"projects/{project_id}/locations/global/collections?pageSize=100")


def list_connectors(project_id: str) -> list[dict]:
    """Every collection in the project that carries a data connector."""
    connectors = []
    for collection in iter_resources(_collections_url(project_id), project_id, "collections"):
        name = str(collection.get("name", ""))
        if not name or name.endswith("/default_collection"):
            continue
        connector = request("GET", discovery_url(f"{name}/dataConnector"), project_id)
        if connector.get("dataSource"):
            connectors.append(connector)
    return connectors


def _instance_uri(connector: dict) -> str:
    params = connector.get("params") or {}
    action = (connector.get("actionConfig") or {}).get("actionParams") or {}
    return str(params.get("instance_uri") or action.get("instance_uri") or "").rstrip("/")


def _collection_id(connector: dict) -> str:
    # .../collections/<id>/dataConnector
    return str(connector["name"]).split("/collections/", 1)[1].split("/", 1)[0]


def _matches(ref: ConnectorRef, connector: dict) -> bool:
    if connector.get("dataSource") != ref.data_source:
        return False
    if ref.mcp_server_url:
        return _instance_uri(connector) == ref.mcp_server_url.rstrip("/")
    return True


def resolve(ref: ConnectorRef, connectors: list[dict], agent: str) -> ResolvedConnector:
    """Pick exactly one connector for a reference, or explain how to choose one."""
    candidates = [c for c in connectors if _matches(ref, c)]
    wanted = configured_value(ref.collection_env) if ref.collection_env else ""
    if wanted:
        candidates = [c for c in candidates if _collection_id(c) == wanted]
    label = ref.data_source + (f" ({ref.mcp_server_url})" if ref.mcp_server_url else "")
    if not candidates:
        raise SystemExit(
            f"{agent} needs a {label} connector, and none was found in the project"
            + (f" with collection ID '{wanted}'" if wanted else "")
            + ". Create it in the Gemini Enterprise console (Data stores > Create data store), "
            "then deploy again. See agents/no_code/README.md."
        )
    if len(candidates) > 1:
        ids = ", ".join(sorted(_collection_id(c) for c in candidates))
        hint = (
            f"Set {ref.collection_env} (gemini_enterprise.*_connector_id in deployment/config.yaml)"
            if ref.collection_env
            else "Add collection_env to this connector in agent.yaml and set it"
        )
        raise SystemExit(
            f"{agent}: more than one {label} connector exists ({ids}). {hint} to choose one."
        )
    connector = candidates[0]
    state = connector.get("state")
    if state not in {"ACTIVE", "WARNING"}:
        print(f"WARNING={agent}: connector {_collection_id(connector)} is in state {state}.")
    stores = tuple(
        str(entity["dataStore"])
        for entity in connector.get("entities") or ()
        if entity.get("dataStore")
    )
    return ResolvedConnector(
        collection=f"collections/{_collection_id(connector)}",
        data_source=ref.data_source,
        data_stores=stores,
    )
