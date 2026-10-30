"""Seed the Atlassian site Ticket Guidance uses, as its service account.

* Confluence: the knowledge base space and the sample articles in
  sample_data/confluence/, created when missing (matched by title).
* Jira: checked, not created. Creating a project needs a site admin and a
  template choice, so the step reports what is missing instead.

The API token is read from Secret Manager (ticket-guidance-jira-api-token) and
never printed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests
from paths import ROOT
from registry import JIRA_API_TOKEN_SECRET

TIMEOUT_SECONDS = 30
SAMPLE_PAGES_DIR = ROOT / "sample_data" / "confluence"
SPACE_NAME = "Enterprise Technology Service Desk Knowledge Base"
REQUIRED_STATUSES = ("Done", "In Progress")
SERVICE_DESK_TYPES = ("Service Request", "Incident Request")


@dataclass(frozen=True, slots=True)
class Atlassian:
    site: str
    email: str
    token: str

    def call(self, method: str, path: str, **kwargs) -> requests.Response:
        return requests.request(
            method,
            f"{self.site}{path}",
            auth=(self.email, self.token),
            headers={"Accept": "application/json", "X-Atlassian-Token": "no-check"},
            timeout=TIMEOUT_SECONDS,
            **kwargs,
        )


def atlassian_client(project_id: str) -> Atlassian:
    from google.cloud import secretmanager

    site = os.getenv("JIRA_SITE_URL", "").rstrip("/")
    email = os.getenv("JIRA_SERVICE_ACCOUNT_EMAIL", "")
    if not site or not email:
        raise SystemExit(
            "Set atlassian.site_url and atlassian.service_account_email in config.yaml."
        )
    name = f"projects/{project_id}/secrets/{JIRA_API_TOKEN_SECRET}/versions/latest"
    try:
        token = (
            secretmanager.SecretManagerServiceClient()
            .access_secret_version(name=name)
            .payload.data.decode("utf-8")
        )
    except Exception as exc:
        raise SystemExit(
            f"Cannot read the Atlassian API token from {JIRA_API_TOKEN_SECRET}: "
            f"{type(exc).__name__}. Run the seed step's secrets first."
        ) from None
    return Atlassian(site, email, token)


def _markdown_page(path) -> tuple[str, str]:
    import markdown

    lines = path.read_text(encoding="utf-8").splitlines()
    title = lines[0].lstrip("# ").strip()
    return title, markdown.markdown("\n".join(lines[1:])).replace("\n", " ")


def seed_confluence(client: Atlassian, space: str) -> list[str]:
    """Create the space and any missing sample page; return the page titles."""
    response = client.call("GET", f"/wiki/rest/api/space/{space}")
    if response.status_code == 404:
        created = client.call(
            "POST", "/wiki/rest/api/space", json={"key": space, "name": SPACE_NAME}
        )
        if not created.ok:
            raise SystemExit(
                f"Creating Confluence space {space} failed: HTTP {created.status_code}"
            )
        print(f"CONFLUENCE_SPACE_CREATED={space}")
    elif not response.ok:
        raise SystemExit(f"Reading Confluence space {space} failed: HTTP {response.status_code}")

    titles = []
    for path in sorted(SAMPLE_PAGES_DIR.glob("*.md")):
        title, body = _markdown_page(path)
        titles.append(title)
        found = client.call(
            "GET", "/wiki/rest/api/content", params={"spaceKey": space, "title": title}
        )
        if found.ok and found.json().get("results"):
            print(f"CONFLUENCE_PAGE_EXISTS={title}")
            continue
        page = {
            "type": "page",
            "title": title,
            "space": {"key": space},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        created = client.call("POST", "/wiki/rest/api/content", json=page)
        if not created.ok:
            raise SystemExit(f"Creating page '{title}' failed: HTTP {created.status_code}")
        print(f"CONFLUENCE_PAGE_CREATED={title}")
    return titles


def check_jira(client: Atlassian, project_key: str) -> list[str]:
    """What the Jira project lacks for Ticket Guidance; empty when it is ready."""
    problems = []
    myself = client.call("GET", "/rest/api/2/myself")
    if not myself.ok:
        return [f"the API token is rejected (HTTP {myself.status_code})"]
    project = client.call("GET", f"/rest/api/2/project/{project_key}")
    if not project.ok:
        return [f"project {project_key} does not exist or the service account cannot see it"]
    types = client.call("GET", f"/rest/api/2/issue/createmeta/{project_key}/issuetypes").json()
    names = {item["name"] for item in types.get("issueTypes", types.get("values", []))}
    if not names & set(SERVICE_DESK_TYPES):
        problems.append(
            f"no {' or '.join(SERVICE_DESK_TYPES)} issue type (tickets will be created as Task)"
        )
    statuses = client.call("GET", f"/rest/api/2/project/{project_key}/statuses").json()
    available = {s["name"].lower() for kind in statuses for s in kind.get("statuses", [])}
    problems += [f"no '{s}' status" for s in REQUIRED_STATUSES if s.lower() not in available]
    return problems


def seed_atlassian(project_id: str) -> None:
    client = atlassian_client(project_id)
    space = os.getenv("TICKET_CONFLUENCE_SPACE", "") or "ETSDKB"
    seed_confluence(client, space)
    project_key = os.getenv("JIRA_PROJECT_KEY", "")
    problems = check_jira(client, project_key) if project_key else ["no jira_project_key set"]
    for problem in problems:
        print(f"ACTION_REQUIRED=Jira project {project_key}: {problem}.")
    if not problems:
        print(f"JIRA_PROJECT_READY={project_key}")
