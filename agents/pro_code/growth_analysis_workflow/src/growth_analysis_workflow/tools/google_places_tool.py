"""Production Google Places (New) Batch Tool for Customer Reviews with L6W Date Filtering."""

import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import requests
from gemini_shared.secrets import optional_secret

from growth_analysis_workflow.config_loader import load_agent_config
from growth_analysis_workflow.models.greview_models import (
    ReviewItem,
    StoreInput,
    StoreReviewSummary,
)
from growth_analysis_workflow.tools import sample_external
from growth_analysis_workflow.utils.date_helpers import get_l6w_date_bounds

logger = logging.getLogger(__name__)

# Load configuration parameters for Google Reviews
review_cfg = load_agent_config("google_reviews_agent")
api_cfg = review_cfg.get("api", {})
search_cfg = review_cfg.get("search", {})


def _build_candidate_queries(
    store: StoreInput,
    brand_prefix: str = "",
    brand_to_strip: str = "",
) -> List[str]:
    """Constructs multi-tiered search query candidates for Google Places API matching.

    Args:
        store: Store details including name, address, city, and state.
        brand_prefix: Brand prefix to prepend to store queries.
        brand_to_strip: Substring to remove from raw store name.

    Returns:
        List[str]: Ranked list of search query strings.
    """
    raw_name = store.store_name or ""
    clean_name = (
        raw_name.replace(brand_to_strip, "").strip() if brand_to_strip else raw_name.strip()
    )

    candidate_queries: List[str] = []

    # Primary: Brand + Store Name + Address + City + State
    if store.address and store.city:
        candidate_queries.append(
            f"{brand_prefix} {clean_name} {store.address} {store.city} {store.state}".strip()
        )

    # Fallback 1: Brand + Store Name / City
    if store.city:
        candidate_queries.append(f"{brand_prefix} {clean_name} {store.city} {store.state}".strip())

    # Fallback 2: Address + City + State without brand
    if store.address and store.city:
        candidate_queries.append(f"{store.address} {store.city} {store.state}".strip())

    # Fallback 3: Raw store query
    candidate_queries.append(f"{raw_name} {store.city} {store.state}".strip())

    return candidate_queries


def _query_google_places_api(
    candidate_queries: List[str],
    store: StoreInput,
    api_key: str,
    api_url: str,
    field_mask: str,
    timeout_sec: int,
    bias_radius: float,
) -> Tuple[List[Dict[str, Any]], str]:
    """Iterates candidate search queries against Google Places API with location biasing.

    Args:
        candidate_queries: Ranked search strings.
        store: Target store containing coordinate details.
        api_key: Google Places API authentication key.
        api_url: Google Places searchText endpoint URL.
        field_mask: Field mask string specifying returned fields.
        timeout_sec: Request timeout in seconds.
        bias_radius: Coordinate circle radius in meters.

    Returns:
        Tuple of (matching_places_list, matched_query_string).
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }

    places: List[Dict[str, Any]] = []
    matched_query = ""

    for query_text in candidate_queries:
        if not query_text:
            continue

        payload: Dict[str, Any] = {"textQuery": query_text}

        lat = getattr(store, "lat", None)
        long = getattr(store, "long", None)
        if lat is not None and long is not None:
            try:
                payload["locationBias"] = {
                    "circle": {
                        "center": {"latitude": float(lat), "longitude": float(long)},
                        "radius": bias_radius,
                    }
                }
            except (ValueError, TypeError):
                pass

        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=timeout_sec)
            response.raise_for_status()
            res_json = response.json()
            found_places = res_json.get("places", [])
            if found_places:
                places = found_places
                matched_query = query_text
                break
        except requests.RequestException as req_err:
            logger.debug(f"[Google Places] Candidate query '{query_text}' failed: {req_err}")
            continue
        except Exception as err:
            logger.debug(f"[Google Places] Unexpected error during candidate search: {err}")
            continue

    return places, matched_query


def _filter_l6w_reviews(
    raw_reviews: List[Dict[str, Any]],
    l6w_start_date: datetime.date,
    ref_date: datetime.date,
) -> List[ReviewItem]:
    """Parses Google Places reviews and filters those falling within the evaluation window.

    Args:
        raw_reviews: List of raw review dictionaries from Google Places API.
        l6w_start_date: Start date of the evaluation window.
        ref_date: End / reference date of the evaluation window.

    Returns:
        List[ReviewItem]: Filtered list of structured review items.
    """
    parsed_reviews: List[ReviewItem] = []
    for r in raw_reviews:
        text_obj = r.get("text", {})
        review_text = text_obj.get("text", "") if isinstance(text_obj, dict) else str(text_obj)
        publish_time_str = r.get("publishTime", "")

        is_l6w = True
        if publish_time_str:
            try:
                clean_iso = publish_time_str.replace("Z", "+00:00")
                rev_dt = datetime.datetime.fromisoformat(clean_iso).date()
                if rev_dt < l6w_start_date or rev_dt > ref_date:
                    is_l6w = False
            except Exception:
                pass

        if is_l6w:
            parsed_reviews.append(
                ReviewItem(
                    author_name=r.get("authorAttribution", {}).get("displayName", "Anonymous"),
                    rating=float(r.get("rating", 0.0)),
                    relative_time=r.get("relativePublishTimeDescription", ""),
                    text=review_text,
                )
            )

    return parsed_reviews


def fetch_single_store_reviews(
    store: StoreInput,
    target_date: Optional[str] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """Fetches Google Places Details for a single location using multi-tier queries & location biasing.

    Args:
        store: Target store data model.
        target_date: Optional reference date string (YYYY-MM-DD).

    Returns:
        Tuple of (store_id, concise_summary_string, detailed_dict).
    """
    location_label = f"{store.city} ({store.state})" if store.city else f"Store #{store.store_id}"

    # Calculate L6W cutoff date relative to target_date using date_helpers
    window_days = search_cfg.get("date_window_days", 60)
    l6w_start_date, ref_date = get_l6w_date_bounds(target_date, days_back=window_days)

    api_key = optional_secret("GOOGLE_PLACES_API_KEY_SECRET")
    if not api_key:
        err_msg = f"{location_label}: GOOGLE_PLACES_API_KEY missing."
        logger.warning(f"[Google Places Tool] {err_msg}")
        return store.store_id, err_msg, {"error": "Missing key", "store_id": store.store_id}

    # Configuration extraction
    brand_prefix = search_cfg.get("brand_prefix", "")
    brand_to_strip = search_cfg.get("brand_to_strip", "")
    api_url = api_cfg.get("places_search_url", "https://places.googleapis.com/v1/places:searchText")
    field_mask = api_cfg.get(
        "field_mask",
        (
            "places.id,places.displayName,places.rating,places.userRatingCount,"
            "places.reviews.name,places.reviews.rating,places.reviews.text,"
            "places.reviews.publishTime,places.reviews.relativePublishTimeDescription,"
            "places.reviews.authorAttribution"
        ),
    )
    timeout_sec = api_cfg.get("timeout_seconds", 6)
    bias_radius = search_cfg.get("location_bias_radius_meters", 2000.0)

    # 1. Multi-tiered search query candidates
    candidate_queries = _build_candidate_queries(
        store=store,
        brand_prefix=brand_prefix,
        brand_to_strip=brand_to_strip,
    )

    # 2. Iterate queries with Lat/Long location biasing
    places, _ = _query_google_places_api(
        candidate_queries=candidate_queries,
        store=store,
        api_key=api_key,
        api_url=api_url,
        field_mask=field_mask,
        timeout_sec=timeout_sec,
        bias_radius=bias_radius,
    )

    if not places:
        concise = f"{location_label}: No matching Google Place listing found."
        logger.info(f"[Google Places Tool] {concise}")
        return store.store_id, concise, {"store_id": store.store_id, "status": "NOT_FOUND"}

    place = places[0]
    display_name = place.get("displayName", {}).get("text", store.store_name or "Store")
    rating = float(place.get("rating", 0.0))
    rating_count = int(place.get("userRatingCount", 0))

    # 3. Parse and filter reviews falling within the evaluation window
    parsed_reviews = _filter_l6w_reviews(
        raw_reviews=place.get("reviews", []),
        l6w_start_date=l6w_start_date,
        ref_date=ref_date,
    )

    summary = StoreReviewSummary(
        store_id=store.store_id,
        place_id=place.get("id"),
        display_name=display_name,
        rating=rating,
        user_rating_count=rating_count,
        recent_reviews=parsed_reviews,
    )

    concise = (
        f"{location_label} (Store #{store.store_id}): Rated {rating:.1f}/5.0 stars across "
        f"{rating_count} Google reviews ({len(parsed_reviews)} within L6W window)."
    )
    return store.store_id, concise, summary.model_dump()


def fetch_google_reviews_batch(
    stores: List[StoreInput],
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure batch tool: Fetches Google Places reviews for a batch of stores within L6W window.

    Args:
        stores: List of StoreInput objects.
        target_date: Optional reference date string (YYYY-MM-DD).

    Returns:
        Dict[str, Any]: Mapping of store_id to customer review summaries.
    """
    if sample_external.enabled():
        return sample_external.reviews(stores)
    # ADK passes the raw dicts when one of them fails validation, so validate here
    # and keep going with the stores that are usable.
    stores = [
        store if isinstance(store, StoreInput) else StoreInput.model_validate(store)
        for store in stores or []
        if isinstance(store, StoreInput) or (isinstance(store, dict) and store.get("store_id"))
    ]
    # Without a key every store fails the same way; say so once, plainly, so the
    # model writes its summary instead of retrying the call with other inputs.
    if not optional_secret("GOOGLE_PLACES_API_KEY_SECRET"):
        logger.warning("[Google Places Tool Batch] No Places API key; reviews unavailable.")
        return {
            "status": "unavailable",
            "message": "Google reviews are not configured in this environment. Do not call "
            "this tool again. Write the summary from the review and rating metrics in the "
            "store performance data instead.",
        }
    logger.info(
        f"[Google Places Tool Batch] Executing parallel review analysis for {len(stores)} stores..."
    )
    max_workers = min(len(stores), api_cfg.get("max_workers", 5)) if stores else 1

    def _worker(store: StoreInput) -> Tuple[str, Dict[str, Any]]:
        """Worker function for concurrent store review analysis."""
        try:
            store_id, _, detailed_dict = fetch_single_store_reviews(store, target_date=target_date)
            return store_id, detailed_dict
        except Exception as e:
            logger.error(
                f"[Google Places Tool Batch] Worker error for store '{store.store_id}': {e}"
            )
            return store.store_id, {"error": str(e), "store_id": store.store_id}

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = dict(executor.map(_worker, stores))
        logger.info(
            f"[Google Places Tool Batch Success] Completed customer review analysis for all {len(stores)} stores."
        )
        return results
    except Exception as batch_err:
        logger.error(f"[Google Places Tool Batch] Batch execution failed: {batch_err}")
        return {"error": str(batch_err)}
