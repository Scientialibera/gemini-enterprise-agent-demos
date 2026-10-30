"""Search the Confluence knowledge base.

Two backends, chosen by CONFLUENCE_SEARCH_BACKEND:

* ``connector`` (default) calls the Discovery Engine data stores behind the
  Gemini Enterprise Confluence connector with the user's own Google token, so
  Confluence page permissions are enforced for the person asking.
* ``api`` calls Confluence's search API as the Atlassian service account. It
  needs no connector, for an environment that cannot run one, but returns what
  the service account can read, so use it only for a space every user may read.
"""

from __future__ import annotations

import html
import logging
import re

import requests
from gemini_shared import current_user_credentials
from gemini_shared.secrets import read_secret

from ..config import (
    CONFLUENCE_CONNECTOR_ID,
    CONFLUENCE_DATASTORE_SUFFIXES,
    CONFLUENCE_SEARCH_BACKEND,
    CONFLUENCE_SPACE,
    DISCOVERY_ENGINE_LOCATION,
    JIRA_API_TOKEN_SECRET_ENV,
    JIRA_SERVICE_ACCOUNT_EMAIL,
    JIRA_SITE_URL,
    MAX_ARTICLES_RETURNED,
    PROJECT_ID,
    SEARCH_PAGE_SIZE,
)

LOGGER = logging.getLogger(__name__)
DISCOVERY_ENGINE_HOST = "https://discoveryengine.googleapis.com/v1"
REQUEST_TIMEOUT_SECONDS = 30
# Words too common to narrow a knowledge-base search.
_STOP_WORDS_TEXT = (
    "a an and are but can cant could does doesnt dont for from have how into its just "
    "keep keeps my not now of on or our the this that to was when why will with "
    "working work isnt wont your you"
)
_STOP_WORDS = frozenset(_STOP_WORDS_TEXT.split())


class SearchError(RuntimeError):
    """A search backend failed or is not configured; the message is safe to show."""


def _clean_html(text: str) -> str:
    if not text:
        return ""
    unescaped = html.unescape(text)
    return " ".join(re.sub(r"<[^>]+>", "", unescaped).split())


def _in_space(url: str) -> bool:
    return bool(re.search(re.escape(CONFLUENCE_SPACE), url, re.IGNORECASE))


def _document_fields(item: dict) -> tuple[str, str, str]:
    document = item.get("document", {})
    struct = document.get("structData", {})
    derived = document.get("derivedStructData", {})
    url = struct.get("uri") or struct.get("url") or derived.get("url") or derived.get("link", "")
    title = struct.get("title") or derived.get("title", "Untitled")
    snippets = derived.get("snippets", [])
    snippet = snippets[0].get("snippet", "") if snippets else ""
    return str(title), str(url), str(snippet)


def _search_url(suffix: str) -> str:
    data_store = f"{CONFLUENCE_CONNECTOR_ID}{suffix}"
    return (
        f"{DISCOVERY_ENGINE_HOST}/projects/{PROJECT_ID}/locations/{DISCOVERY_ENGINE_LOCATION}"
        f"/collections/default_collection/dataStores/{data_store}"
        "/servingConfigs/default_config:search"
    )


def _connector_articles(query: str) -> list[tuple[str, str, str]]:
    if not CONFLUENCE_CONNECTOR_ID:
        raise SearchError("CONFLUENCE_CONNECTOR_ID is not configured.")
    token = current_user_credentials().token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    formatted_query = (
        query if CONFLUENCE_SPACE.lower() in query.lower() else (f"{query} {CONFLUENCE_SPACE}")
    )
    payload = {
        "query": formatted_query,
        "pageSize": SEARCH_PAGE_SIZE,
        "contentSearchSpec": {"snippetSpec": {"returnSnippet": True}},
    }
    found = []
    for suffix in CONFLUENCE_DATASTORE_SUFFIXES:
        response = requests.post(
            _search_url(suffix), headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS
        )
        if not response.ok:
            LOGGER.warning(
                "Confluence search on %s%s returned HTTP %s",
                CONFLUENCE_CONNECTOR_ID,
                suffix,
                response.status_code,
            )
            continue
        for item in response.json().get("results", []):
            title, url, snippet = _document_fields(item)
            if url and _in_space(url):
                found.append((title, url, snippet))
    return found


def _cql(query: str) -> str:
    """Match any meaningful word of the user's description, ranked by Confluence."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP_WORDS]
    terms = " OR ".join(f'text ~ "{w}"' for w in dict.fromkeys(words) if len(w) > 2)
    space = CONFLUENCE_SPACE.replace('"', "")
    return f'space = "{space}" AND type in (page, blogpost)' + (f" AND ({terms})" if terms else "")


def _api_articles(query: str) -> list[tuple[str, str, str]]:
    if not JIRA_SITE_URL or not JIRA_SERVICE_ACCOUNT_EMAIL:
        raise SearchError("JIRA_SITE_URL and JIRA_SERVICE_ACCOUNT_EMAIL must be configured.")
    response = requests.get(
        f"{JIRA_SITE_URL}/wiki/rest/api/search",
        params={"cql": _cql(query), "limit": SEARCH_PAGE_SIZE, "excerpt": "highlight"},
        auth=(JIRA_SERVICE_ACCOUNT_EMAIL, read_secret(JIRA_API_TOKEN_SECRET_ENV)),
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise SearchError(f"Confluence search failed with HTTP {response.status_code}.")
    return [
        (
            str(item.get("content", {}).get("title") or item.get("title", "Untitled")),
            f"{JIRA_SITE_URL}/wiki{item.get('url', '')}",
            str(item.get("excerpt", "")),
        )
        for item in response.json().get("results", [])
    ]


def search_confluence_kb_tool(query: str) -> dict:
    """Search the IT knowledge base space in Confluence for articles about the user's issue.

    Always call this first, before responding to any IT issue. Only articles
    from the configured knowledge base space are returned.

    Args:
        query: The user's issue description or keywords to search for.
    """
    search = _api_articles if CONFLUENCE_SEARCH_BACKEND == "api" else _connector_articles
    try:
        found = search(query)
    except SearchError as exc:
        return {"status": "Error", "message": str(exc)}

    articles = [
        {"title": title, "url": url, "content_snippet": _clean_html(snippet)}
        for title, url, snippet in found[:MAX_ARTICLES_RETURNED]
    ]
    return {
        "status": "Success",
        "space": CONFLUENCE_SPACE,
        "total_results": len(articles),
        "articles": articles,
    }
