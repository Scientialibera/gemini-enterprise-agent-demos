"""Fixed sample data for the five research tools, keyed by store city.

The demo's store workbook never changes, so the same stores are always the bottom
performers. Serving their weather, reviews, labor data and news from a file keeps
every run fast and identical, with no outside API, key or rate limit involved.
Set GROWTH_LIVE_EXTERNAL_DATA=true to call the real APIs instead.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from functools import cache
from pathlib import Path
from typing import Any, Dict, Iterable

logger = logging.getLogger(__name__)

SAMPLE_FILE = Path(__file__).resolve().parent.parent / "resources" / "sample_external_data.json"


def enabled() -> bool:
    return os.getenv("GROWTH_LIVE_EXTERNAL_DATA", "").strip().lower() != "true"


@cache
def _data() -> Dict[str, Any]:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def _field(store: Any, name: str) -> Any:
    return store.get(name) if isinstance(store, dict) else getattr(store, name, None)


def _by_city(stores: Iterable[Any], section: str) -> Dict[str, Any]:
    """Map each requested store's id to its city's sample record, keyed as the caller sent it."""
    records = _data()[section]
    found = {}
    for store in stores or []:
        city = str(_field(store, "city") or "").strip()
        store_id = str(_field(store, "store_id") or _field(store, "store_name") or city)
        if city in records:
            found[store_id] = {**copy.deepcopy(records[city]), "store_id": store_id}
    return found


def weather(stores: Iterable[Any]) -> Dict[str, Any]:
    logger.info("[Sample Data] Serving weather for the requested stores.")
    return _by_city(stores, "weather")


def reviews(stores: Iterable[Any]) -> Dict[str, Any]:
    logger.info("[Sample Data] Serving Google reviews for the requested stores.")
    return _by_city(stores, "reviews")


def macro_labor() -> Dict[str, Any]:
    logger.info("[Sample Data] Serving macro and labor data.")
    return copy.deepcopy(_data()["macro_labor"])


def industry_news() -> Dict[str, Any]:
    logger.info("[Sample Data] Serving industry news.")
    return copy.deepcopy(_data()["industry_news"])


def local_news(stores: Iterable[Any]) -> Dict[str, Any]:
    logger.info("[Sample Data] Serving local news for the requested stores.")
    cities = sorted({str(_field(store, "city") or "").strip() for store in stores or []} - {""})
    articles = [article for city in cities for article in _data()["local_news"].get(city, [])]
    return {
        "cities_searched": cities,
        "total_articles_found": len(articles),
        "articles": copy.deepcopy(articles),
    }
