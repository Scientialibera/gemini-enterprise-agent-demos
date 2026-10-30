"""Production Batch QSR & Industry News Tool using Feedparser RSS Feeds with L6W Date Filtering."""

import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import feedparser

from growth_analysis_workflow.config_loader import load_agent_config
from growth_analysis_workflow.models.qsr_news_models import NewsArticle, QsrNewsSummary, StoreInput
from growth_analysis_workflow.tools import sample_external
from growth_analysis_workflow.utils.date_helpers import get_l6w_date_bounds

logger = logging.getLogger(__name__)

# Dynamic configuration loading from dedicated qsr_news_agent.yaml
qsr_cfg = load_agent_config("qsr_news_agent")
RSS_FEED_CONFIG: Dict[str, str] = qsr_cfg.get("rss_feeds", {})


def _fetch_single_rss_feed(
    source_name: str,
    feed_url: str,
    l6w_start_date: datetime.date,
    ref_date: datetime.date,
    fallback_limit: int = 5,
) -> List[NewsArticle]:
    """Parses entries available in an RSS feed falling strictly within the L6W window.

    Args:
        source_name: Human-readable publication name (e.g. 'QSR Magazine').
        feed_url: Target RSS feed endpoint URL.
        l6w_start_date: Start date of the evaluation window.
        ref_date: End date of the evaluation window.
        fallback_limit: Max number of recent articles to return if none fall inside the window.

    Returns:
        List[NewsArticle]: Filtered news articles.
    """
    articles: List[NewsArticle] = []
    fallback_articles: List[NewsArticle] = []

    try:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            pub_date_raw = getattr(entry, "published", "2026")
            title = getattr(entry, "title", "Untitled Article")
            link = getattr(entry, "link", "")

            article = NewsArticle(
                title=title,
                link=link,
                published=pub_date_raw,
                source=source_name,
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
            f"[QSR News Tool Warning] Failed to parse RSS feed '{source_name}' ({feed_url}): {parse_err}"
        )

    return articles if articles else fallback_articles[:fallback_limit]


def fetch_qsr_industry_news_batch(
    stores: List[StoreInput],
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure batch tool: Ingests live QSR industry publication RSS feeds within L6W timeframe.

    Args:
        stores: List of StoreInput objects.
        target_date: Optional reference date string (YYYY-MM-DD).

    Returns:
        Dict[str, Any]: Aggregated industry news articles and metadata.
    """
    if sample_external.enabled():
        return sample_external.industry_news()
    window_days = qsr_cfg.get("window_days", 42)
    fallback_limit = qsr_cfg.get("fallback_article_limit", 5)
    max_workers = qsr_cfg.get("max_workers", 3)
    l6w_start_date, ref_date = get_l6w_date_bounds(target_date, days_back=window_days)

    logger.info(
        f"[QSR News Tool Batch] Ingesting industry RSS feeds across {len(RSS_FEED_CONFIG)} publications (L6W target: {ref_date})..."
    )

    all_articles: List[NewsArticle] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _fetch_single_rss_feed, source, url, l6w_start_date, ref_date, fallback_limit
            )
            for source, url in RSS_FEED_CONFIG.items()
        ]
        for future in futures:
            try:
                all_articles.extend(future.result())
            except Exception as e:
                logger.error(f"[QSR News Tool ERROR] Thread execution failed: {e}")

    summary = QsrNewsSummary(
        total_articles_ingested=len(all_articles),
        articles=all_articles,
        parsed_sources=list(RSS_FEED_CONFIG.keys()),
    )

    logger.info(
        f"[QSR News Tool Batch Success] Successfully parsed {len(all_articles)} industry news articles."
    )
    return summary.model_dump()
