"""Create a custom MCP connector (e.g. BigQuery MCP) from a downloaded OAuth client JSON.

The console's connector form does the same thing; this exists so the step can be
scripted. The client secret goes from the JSON file straight into the request and
is never printed. Afterwards, two console steps remain, because no API covers them:
connect the new data store to the app (Gemini Enterprise > Connected data stores >
Add existing data stores) and enable the connector's actions.

Prerequisites:
  * The org policy constraints/discoveryengine.managed.disableCustomMcpServerConnector
    must not be enforced on the project (it is on by default in new organizations).
  * A Web OAuth client with both Gemini Enterprise redirect URIs; download its JSON
    from the client's page (Add secret, then the download icon).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import json
import os
import time

from config.settings import load_environment, require_deploy_environment
from gemini_shared.mcp.mcp_google_cloud import BIGQUERY, BIGQUERY_READONLY_TOOLS, BIGQUERY_SCOPE
from paths import ROOT

from deploy.register.api_http import access_token, discovery_url, request
from deploy.register.register_agent import OAUTH_AUTHORIZATION_ENDPOINT, OAUTH_TOKEN_ENDPOINT

OPERATION_POLL_SECONDS = 5
OPERATION_POLL_ATTEMPTS = 60


def create_connector(
    project_id: str,
    client_json: Path,
    collection_id: str,
    display_name: str,
    server_url: str,
    scopes: str,
    description: str,
) -> list[str]:
    """Create the connector and return its data store names."""
    web = json.loads(client_json.read_text(encoding="utf-8"))["web"]
    location = f"projects/{project_id}/locations/global"
    body = {
        "collectionId": collection_id,
        "collectionDisplayName": display_name,
        "dataConnector": {
            "dataSource": "custom_mcp",
            # The API requires an admin access token here; the console gets one from
            # its sign-in pop-up. The caller's own token serves the same purpose.
            "params": {"oauth_access_token": access_token()},
            "connectorModes": ["FEDERATED"],
            # Without an entity the connector has no data store, and the agent
            # designer never offers it.
            "entities": [{"entityName": "mcp_data"}],
            "refreshInterval": "86400s",
            "actionConfig": {
                "createBapConnection": True,
                "actionParams": {
                    "instance_uri": server_url,
                    "mcp_server_source": "BYO_MCP",
                    "auth_type": "OAUTH",
                    "client_id": web["client_id"],
                    "client_secret": web["client_secret"],
                    "auth_uri": OAUTH_AUTHORIZATION_ENDPOINT,
                    "auth_uri_params": "&access_type=offline&prompt=consent",
                    "token_uri": OAUTH_TOKEN_ENDPOINT,
                    "scopes": scopes,
                    "mcp_server_description": description,
                },
            },
        },
    }
    del web
    operation = request("POST", discovery_url(f"{location}:setUpDataConnector"), project_id, body)
    del body
    for _ in range(OPERATION_POLL_ATTEMPTS):
        status = request("GET", discovery_url(str(operation["name"])), project_id)
        if status.get("done"):
            if status.get("error"):
                raise SystemExit(f"Connector setup failed: {status['error']}")
            break
        time.sleep(OPERATION_POLL_SECONDS)
    connector = request(
        "GET", discovery_url(f"{location}/collections/{collection_id}/dataConnector"), project_id
    )
    print(f"CONNECTOR_STATE={connector.get('state')}")
    return [e["dataStore"] for e in connector.get("entities", []) if e.get("dataStore")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--client-json", type=Path, required=True)
    parser.add_argument("--collection-id", default="bigquery-mcp-connector")
    parser.add_argument("--display-name", default="BigQuery MCP")
    parser.add_argument("--server-url", default=BIGQUERY)
    parser.add_argument("--scopes", default=BIGQUERY_SCOPE)
    parser.add_argument(
        "--description",
        default=("BigQuery MCP server: list datasets, read table schemas and run read-only SQL."),
    )
    parser.add_argument(
        "--delete-json", action="store_true", help="Delete the client JSON after success."
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, _, _ = require_deploy_environment(require_parameter=False)
    stores = create_connector(
        project_id,
        args.client_json,
        args.collection_id,
        args.display_name,
        args.server_url,
        args.scopes,
        args.description,
    )
    if args.delete_json:
        args.client_json.unlink()
        print("CLIENT_JSON_DELETED")
    for store in stores:
        print(f"DATA_STORE={store}")
    print(
        "NEXT_STEP=Connect the data store to the app (Gemini Enterprise > Connected data "
        "stores > Add existing data stores), then run deploy_no_code.py."
    )
    if args.server_url == BIGQUERY:
        print(
            "NEXT_STEP=Enable the connector's actions (Data stores > the connector > Actions): "
            + ", ".join(BIGQUERY_READONLY_TOOLS)
        )


if __name__ == "__main__":
    main()
