"""Bootstrap values this agent resolves once at import.

Two credentials, for two different jobs:

* The signed-in user's Google token, from this agent's Gemini Enterprise
  authorization, searches the Confluence knowledge base through the Gemini
  Enterprise Confluence connector. Confluence permissions therefore apply to
  the person asking.
* A dedicated Atlassian service account's API token, read from Secret Manager
  under the agent's own identity, creates and updates Jira tickets. The
  signed-in user is set as the ticket's reporter, found by email.
"""

from __future__ import annotations

import os

from gemini_shared import get_bootstrap_settings

# require_auth raises at import if the authorization ID is missing.
BOOTSTRAP = get_bootstrap_settings(require_auth=True)
PROJECT_ID = BOOTSTRAP.project_id
GEMINI_ENTERPRISE_AUTHORIZATION_ID = str(BOOTSTRAP.gemini_enterprise_authorization_id)


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# Confluence knowledge base, searched through the Gemini Enterprise connector.
CONFLUENCE_SPACE = _setting("CONFLUENCE_SPACE", "ETSDKB")
CONFLUENCE_SPACE_NAME = _setting(
    "CONFLUENCE_SPACE_NAME", "Enterprise Technology Service Desk Knowledge Base"
)
# The connector's collection ID, e.g. confluence_1234567890. Its pages, blogs
# and comments are separate data stores named <collection>_page and so on.
CONFLUENCE_CONNECTOR_ID = _setting("CONFLUENCE_CONNECTOR_ID")
CONFLUENCE_DATASTORE_SUFFIXES = ("_page", "_blog", "_comment")
# "connector" searches the connector's data stores as the signed-in user, so each
# user's Confluence permissions apply. "api" calls Confluence's search API as the
# Atlassian service account below: for an environment that cannot run an ingestion
# connector (it needs a Workspace or Cloud Identity organization), and only for a
# space every user may read.
CONFLUENCE_SEARCH_BACKEND = _setting("CONFLUENCE_SEARCH_BACKEND", "connector").lower()
DISCOVERY_ENGINE_LOCATION = _setting("DISCOVERY_ENGINE_LOCATION", "global")
SEARCH_PAGE_SIZE = int(_setting("CONFLUENCE_SEARCH_PAGE_SIZE", "10"))
MAX_ARTICLES_RETURNED = int(_setting("CONFLUENCE_MAX_ARTICLES", "5"))

# Jira (and Confluence with the "api" backend), called as a dedicated Atlassian
# service account. One Atlassian API token covers both on the same site.
# A scoped service-account token must use the API gateway form,
# https://api.atlassian.com/ex/jira/<cloud-id>; a classic token can use the site URL.
JIRA_API_BASE_URL = _setting("JIRA_API_BASE_URL").rstrip("/")
# Human-facing site for browse links, e.g. https://example.atlassian.net.
JIRA_SITE_URL = _setting("JIRA_SITE_URL").rstrip("/")
JIRA_SERVICE_ACCOUNT_EMAIL = _setting("JIRA_SERVICE_ACCOUNT_EMAIL")
# Names the Secret Manager secret holding the service account's API token.
JIRA_API_TOKEN_SECRET_ENV = "JIRA_API_TOKEN_SECRET"
JIRA_PROJECT_KEY = _setting("JIRA_PROJECT_KEY", "AGENT")
JIRA_PARENT_ISSUE_KEY = _setting("JIRA_PARENT_ISSUE_KEY")
JIRA_ALLOWED_ISSUE_TYPES = ("Service Request", "Incident Request")
JIRA_LABELS = ("AI-Generated",)
