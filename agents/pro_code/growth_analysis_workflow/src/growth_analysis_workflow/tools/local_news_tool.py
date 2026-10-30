"""Production Batch Local News & Metro Market Tool using NYT Article Search API and Eater RSS with L6W Date Filtering."""

import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import feedparser
import requests
from gemini_shared.secrets import optional_secret

from growth_analysis_workflow.config_loader import load_agent_config
from growth_analysis_workflow.models.local_news_models import (
    LocalNewsArticle,
    LocalNewsSummary,
    StoreInput,
)
from growth_analysis_workflow.tools import sample_external
from growth_analysis_workflow.utils.date_helpers import get_l6w_date_bounds

logger = logging.getLogger(__name__)

# Dynamic configuration loading from dedicated local_news_agent.yaml
local_cfg = load_agent_config("local_news_agent")
nyt_cfg = local_cfg.get("nyt", {})
EATER_RSS_MAP: Dict[str, str] = local_cfg.get("eater_rss_map", {})


def _search_nyt_articles_for_cities(
    cities: List[str],
    l6w_start_date: datetime.date,
    ref_date: datetime.date,
) -> List[LocalNewsArticle]:
    """Queries NYT Article Search API for restaurant news using native begin_date and end_date filtering.

    Args:
        cities: List of city names to include in search query.
        l6w_start_date: Start date of evaluation window.
        ref_date: End date of evaluation window.

    Returns:
        List[LocalNewsArticle]: List of matching NYT news articles.
    """
    api_key = optional_secret("NYT_API_KEY_SECRET")
    if not api_key:
        logger.warning("[Local News Tool Warning] NYT_API_KEY is not configured in environment.")
        return []

    base_query = nyt_cfg.get("base_query", "restaurant")
    city_query = " OR ".join(cities) if cities else "dining"
    full_query = f"{base_query} AND ({city_query})"

    # NYT API expects YYYYMMDD format
    begin_date_str = l6w_start_date.strftime("%Y%m%d")
    end_date_str = ref_date.strftime("%Y%m%d")

    url = nyt_cfg.get("url", "https://api.nytimes.com/svc/search/v2/articlesearch.json")
    timeout_sec = nyt_cfg.get("timeout_seconds", 6)
    sort_order = nyt_cfg.get("sort", "newest")

    params = {
        "q": full_query,
        "begin_date": begin_date_str,
        "end_date": end_date_str,
        "api-key": api_key.strip(),
        "sort": sort_order,
    }

    articles: List[LocalNewsArticle] = []

    try:
        response = requests.get(url, params=params, timeout=timeout_sec)
        response.raise_for_status()
        payload = response.json()
        response_data = payload.get("response") or {}
        docs = response_data.get("docs") or []

        for doc in docs:
            headline_obj = doc.get("headline", {})
            main_headline = (
                headline_obj.get("main", "")
                if isinstance(headline_obj, dict)
                else str(headline_obj)
            )
            snippet = doc.get("snippet", "")
            pub_date = doc.get("pub_date", "")[:10]  # Extract YYYY-MM-DD
            web_url = doc.get("web_url", "")

            if main_headline:
                articles.append(
                    LocalNewsArticle(
                        headline=main_headline,
                        snippet=snippet,
                        source="New York Times",
                        pub_date=pub_date,
                        url=web_url,
                    )
                )

    except requests.RequestException as req_err:
        logger.error(f"[Local News Tool ERROR] NYT API HTTP request failed: {req_err}")
    except Exception as gen_err:
        logger.error(f"[Local News Tool ERROR] Failed parsing NYT API payload: {gen_err}")

    return articles


def _parse_eater_local_rss(
    states: List[str],
    l6w_start_date: datetime.date,
    ref_date: datetime.date,
    fallback_limit: int = 5,
) -> List[LocalNewsArticle]:
    """Parses local Eater RSS feeds corresponding to target store state regions, filtered by L6W date window.

    Args:
        states: List of two-letter state postal abbreviations.
        l6w_start_date: Start date of evaluation window.
        ref_date: End date of evaluation window.
        fallback_limit: Maximum articles to include if none match date window.

    Returns:
        List[LocalNewsArticle]: List of matching local Eater articles.
    """
    articles: List[LocalNewsArticle] = []
    fallback_articles: List[LocalNewsArticle] = []
    processed_urls = set()

    for st in states:
        rss_url = EATER_RSS_MAP.get(st.upper().strip())
        if not rss_url or rss_url in processed_urls:
            continue

        processed_urls.add(rss_url)
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries:
                title = getattr(entry, "title", "Untitled")
                link = getattr(entry, "link", "")
                pub_date_raw = getattr(entry, "published", "2026")[:16]

                article = LocalNewsArticle(
                    headline=title,
                    snippet=f"Local dining updates from regional Eater coverage ({st}).",
                    source=f"Eater ({st})",
                    pub_date=pub_date_raw,
                    url=link,
                )
                fallback_articles.append(article)

                pub_parsed = getattr(entry, "published_parsed", None)
                is_l6w = True

                if pub_parsed:
                    try:
                        pub_dt = datetime.date(
                            pub_parsed.tm_year, pub_parsed.tm_mon, pub_parsed.tm_mday
                        )
                        if pub_dt < l6w_start_date or pub_dt > ref_date:
                            is_l6w = False
                    except Exception:
                        pass

                if is_l6w:
                    articles.append(article)

        except Exception as parse_err:
            logger.warning(
                f"[Local News Tool Warning] Failed parsing Eater RSS feed '{rss_url}': {parse_err}"
            )

    return articles if articles else fallback_articles[:fallback_limit]


def fetch_local_news_batch(
    stores: List[StoreInput],
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure batch tool: Searches NYT API and Eater RSS feeds for local market news within L6W timeframe.

    Args:
        stores: List of StoreInput objects.
        target_date: Optional reference date string (YYYY-MM-DD).

    Returns:
        Dict[str, Any]: Aggregated local news summary and article listings.
    """
    if sample_external.enabled():
        return sample_external.local_news(stores)
    window_days = local_cfg.get("window_days", 42)
    fallback_limit = local_cfg.get("fallback_article_limit", 5)
    max_workers = local_cfg.get("max_workers", 2)
    l6w_start_date, ref_date = get_l6w_date_bounds(target_date, days_back=window_days)

    logger.info(
        f"[Local News Tool Batch] Fetching local market coverage for {len(stores)} store cities (L6W target: {ref_date})..."
    )

    unique_cities = sorted(list(set(s.city for s in stores if s.city)))
    unique_states = sorted(list(set(s.state.upper().strip() for s in stores if s.state)))

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            nyt_future = executor.submit(
                _search_nyt_articles_for_cities, unique_cities, l6w_start_date, ref_date
            )
            eater_future = executor.submit(
                _parse_eater_local_rss, unique_states, l6w_start_date, ref_date, fallback_limit
            )

            all_articles = nyt_future.result() + eater_future.result()

        summary = LocalNewsSummary(
            cities_searched=unique_cities,
            total_articles_found=len(all_articles),
            articles=all_articles,
        )

        logger.info(
            f"[Local News Tool Batch Success] Successfully retrieved {len(all_articles)} local news records."
        )
        return summary.model_dump()
    except Exception as batch_err:
        logger.error(
            f"[Local News Tool Batch ERROR] Local news batch execution failed: {batch_err}"
        )
        return {"error": str(batch_err), "cities_searched": unique_cities}
