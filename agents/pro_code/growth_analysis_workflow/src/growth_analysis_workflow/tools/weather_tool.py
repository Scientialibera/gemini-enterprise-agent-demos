"""Production Weather Analysis Tool using Open-Meteo REST API and Threshold Anomaly Rules."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from growth_analysis_workflow.config_loader import load_agent_config, load_threshold_config
from growth_analysis_workflow.models.weather_models import (
    DailyWeatherRecord,
    LocationQuery,
    StoreInput,
    StoreWeatherSummary,
)
from growth_analysis_workflow.tools import sample_external
from growth_analysis_workflow.utils.date_helpers import parse_target_date

logger = logging.getLogger(__name__)

# Dynamically load WMO codes and API configurations from centralized config
weather_cfg = load_agent_config("weather_agent")
api_cfg = weather_cfg.get("api", {})
WMO_CODE_MAP: Dict[int, str] = weather_cfg.get("wmo_code_map", {})


def _fetch_open_meteo_daily_data(
    query: LocationQuery,
    effective_start_date: date,
    effective_end_date: date,
    url: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Queries the Open-Meteo Archive REST API for raw daily meteorological records.

    Args:
        query: Location query containing coordinates and store details.
        effective_start_date: Validated starting date for historical data retrieval.
        effective_end_date: Validated ending date bounded by archival availability.
        url: Open-Meteo archive endpoint URL.
        timeout_seconds: Request timeout in seconds.

    Returns:
        Dict[str, Any]: Raw daily weather metrics returned by the API.

    Raises:
        requests.RequestException: If the HTTP request fails.
        Exception: If JSON parsing fails.
    """
    params = {
        "latitude": query.lat,
        "longitude": query.long,
        "start_date": effective_start_date.strftime("%Y-%m-%d"),
        "end_date": effective_end_date.strftime("%Y-%m-%d"),
        "daily": [
            "weathercode",
            "temperature_2m_max",
            "temperature_2m_min",
            "temperature_2m_mean",
            "precipitation_sum",
            "precipitation_hours",
            "snowfall_sum",
            "windgusts_10m_max",
        ],
        "temperature_unit": "celsius",
        "precipitation_unit": "inch",
        "windspeed_unit": "mph",
        "timezone": "auto",
    }

    try:
        response = requests.get(url, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        return response.json().get("daily", {})
    except requests.RequestException as req_err:
        logger.error(
            f"[Weather Tool ERROR] Open-Meteo API HTTP request failed for '{query.store_id}': {req_err}"
        )
        raise req_err
    except Exception as json_err:
        logger.error(
            f"[Weather Tool ERROR] Failed to parse JSON response from Open-Meteo for '{query.store_id}': {json_err}"
        )
        raise json_err


def _evaluate_daily_anomalies(
    daily_raw: Dict[str, Any],
    rain_cfg: Dict[str, Any],
    snow_cfg: Dict[str, Any],
    temp_cfg: Dict[str, Any],
    wind_cfg: Dict[str, Any],
    wmo_codes: Dict[int, str],
) -> Tuple[List[DailyWeatherRecord], List[str], int, int, int, float]:
    """Evaluates weather records against configured operational thresholds to detect anomalies.

    Args:
        daily_raw: Meteorological dictionary containing daily metric series.
        rain_cfg: Threshold parameters for rain anomalies.
        snow_cfg: Threshold parameters for snow anomalies.
        temp_cfg: Threshold parameters for temperature deviations.
        wind_cfg: Threshold parameters for wind gusts.
        wmo_codes: WMO code to human-readable weather condition mapping.

    Returns:
        Tuple containing:
            - anomalous_daily_records: List of filtered daily records exhibiting anomalies.
            - key_storm_dates: List of dates where anomalies were recorded.
            - total_rain_days: Count of days exceeding rain thresholds.
            - total_snow_days: Count of days exceeding snow thresholds.
            - anomalous_days_count: Total count of days with any anomaly.
            - baseline_temp: Mean temperature baseline across the evaluation window.
    """
    dates = daily_raw.get("time", [])
    temp_means = daily_raw.get("temperature_2m_mean", [])

    valid_temps = [t for t in temp_means if t is not None]
    baseline_temp = sum(valid_temps) / len(valid_temps) if valid_temps else 0.0

    anomalous_daily_records: List[DailyWeatherRecord] = []
    key_storm_dates: List[str] = []
    total_rain_days = 0
    total_snow_days = 0
    anomalous_days_count = 0

    for idx, date_str in enumerate(dates):
        d_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = d_obj.strftime("%A")
        date_with_day = f"{date_str} ({day_name})"

        t_max = daily_raw.get("temperature_2m_max", [])[idx] or 0.0
        t_min = daily_raw.get("temperature_2m_min", [])[idx] or 0.0
        t_mean = daily_raw.get("temperature_2m_mean", [])[idx] or 0.0
        p_sum = daily_raw.get("precipitation_sum", [])[idx] or 0.0
        p_hrs = daily_raw.get("precipitation_hours", [])[idx] or 0.0
        s_sum = daily_raw.get("snowfall_sum", [])[idx] or 0.0
        w_gust = daily_raw.get("windgusts_10m_max", [])[idx] or 0.0
        code = daily_raw.get("weathercode", [])[idx] or 0

        flags: List[str] = []

        # Rule 1: Rain Anomaly Check
        rain_inch_limit = rain_cfg.get("inches_per_day", 0.50)
        rain_duration_limit = rain_cfg.get("duration_hours", 4.0)
        sustained_min = rain_cfg.get("sustained_min_inches", 0.05)

        if p_sum >= rain_inch_limit:
            flags.append(f"Heavy Rain ({p_sum:.2f} in)")
            total_rain_days += 1
        elif p_hrs >= rain_duration_limit and p_sum >= sustained_min:
            flags.append(f"Sustained Rain ({p_sum:.2f} in over {p_hrs:.1f} hrs)")
            total_rain_days += 1

        # Rule 2: Snow Anomaly Check
        snow_inch_limit = snow_cfg.get("inches_per_day", 0.50)
        if s_sum >= snow_inch_limit:
            flags.append(f"Snowfall ({s_sum:.2f} in)")
            total_snow_days += 1

        # Rule 3: Thermal Anomaly Check
        temp_dev_limit = temp_cfg.get("deviation_deg_c", 5.5)
        if abs(t_mean - baseline_temp) >= temp_dev_limit:
            direction = "Heatwave" if (t_mean - baseline_temp) > 0 else "Cold Snap"
            flags.append(f"{direction} (Mean: {t_mean:.1f}°C vs Baseline: {baseline_temp:.1f}°C)")

        # Rule 4: Wind Anomaly Check
        wind_limit = wind_cfg.get("gust_mph", 35.0)
        if w_gust >= wind_limit:
            flags.append(f"High Wind Gusts ({w_gust:.1f} mph)")

        # Only retain records when operational anomalies occur
        if flags:
            anomalous_days_count += 1
            key_storm_dates.append(date_str)
            record = DailyWeatherRecord(
                date=date_with_day,
                weather_condition=wmo_codes.get(code, f"Unclassified (Code {code})"),
                temp_max_c=round(t_max, 1),
                temp_min_c=round(t_min, 1),
                temp_mean_c=round(t_mean, 1),
                precipitation_in=round(p_sum, 2),
                precipitation_hours=round(p_hrs, 1),
                snowfall_in=round(s_sum, 2),
                wind_gust_max_mph=round(w_gust, 1),
                anomaly_flags=flags,
            )
            anomalous_daily_records.append(record)

    return (
        anomalous_daily_records,
        key_storm_dates,
        total_rain_days,
        total_snow_days,
        anomalous_days_count,
        baseline_temp,
    )


def analyze_store_weather(
    query: LocationQuery,
    config_override: Optional[Dict[str, Any]] = None,
) -> StoreWeatherSummary:
    """Fetches weather metrics from Open-Meteo and flags anomalies using thresholds loaded from config.

    Args:
        query: Target location parameters including store ID, coordinates, and date bounds.
        config_override: Optional custom threshold dictionary overriding configuration file settings.

    Returns:
        StoreWeatherSummary: Formatted summary object with anomaly flags and metric totals.
    """
    logger.info(
        f"[Weather Tool] Analyzing weather for store '{query.store_id}' (Lat: {query.lat}, Long: {query.long})..."
    )

    try:
        thresholds = config_override if config_override else load_threshold_config()
    except Exception as cfg_err:
        logger.warning(
            f"[Weather Tool Warning] Failed to load threshold config ({cfg_err}). Falling back to defaults."
        )
        thresholds = {}

    rain_cfg = thresholds.get("rain", {})
    snow_cfg = thresholds.get("snow", {})
    temp_cfg = thresholds.get("temperature", {})
    wind_cfg = thresholds.get("wind", {})

    url = api_cfg.get("url", "https://archive-api.open-meteo.com/v1/archive")
    timeout_sec = api_cfg.get("timeout_seconds", 10)
    max_lag_days = api_cfg.get("max_archival_lag_days", 2)

    max_archival_date = date.today() - timedelta(days=max_lag_days)
    effective_end_date = min(query.end_date, max_archival_date)
    effective_start_date = min(query.start_date, effective_end_date)

    daily_raw = _fetch_open_meteo_daily_data(
        query=query,
        effective_start_date=effective_start_date,
        effective_end_date=effective_end_date,
        url=url,
        timeout_seconds=timeout_sec,
    )

    try:
        (
            anomalous_daily_records,
            key_storm_dates,
            total_rain_days,
            total_snow_days,
            anomalous_days_count,
            baseline_temp,
        ) = _evaluate_daily_anomalies(
            daily_raw=daily_raw,
            rain_cfg=rain_cfg,
            snow_cfg=snow_cfg,
            temp_cfg=temp_cfg,
            wind_cfg=wind_cfg,
            wmo_codes=WMO_CODE_MAP,
        )

        return StoreWeatherSummary(
            store_id=query.store_id,
            latitude=query.lat,
            longitude=query.long,
            analysis_period=f"{effective_start_date.strftime('%Y-%m-%d')} to {effective_end_date.strftime('%Y-%m-%d')}",
            baseline_mean_temp_c=round(baseline_temp, 1),
            total_anomalous_days=anomalous_days_count,
            total_rain_days=total_rain_days,
            total_snow_days=total_snow_days,
            key_storm_dates=key_storm_dates,
            anomalous_daily_records=anomalous_daily_records,
        )

    except Exception as proc_err:
        logger.error(
            f"[Weather Tool ERROR] Anomaly calculation failed for '{query.store_id}': {proc_err}"
        )
        raise proc_err


def fetch_weather_batch(
    stores: List[StoreInput],
    evaluation_date: Optional[str] = None,
    weeks_back: Optional[int] = None,
) -> Dict[str, Any]:
    """Pure batch tool: Fetches parallel weather records for stores.

    Args:
        stores: List of StoreInput objects with store_id, lat, and long.
        evaluation_date: Target evaluation date string in YYYY-MM-DD format (defaults to yesterday).
        weeks_back: Number of lookback weeks (defaults to configuration or 6).

    Returns:
        Dict[str, Any]: Dictionary mapping store_id to weather summary data or error.
    """
    if sample_external.enabled():
        return sample_external.weather(stores)
    logger.info(
        f"[Weather Tool Batch] Executing parallel weather analysis for {len(stores)} stores..."
    )

    # Resolve lookback window from config if not explicitly provided
    resolved_weeks_back = (
        weeks_back if weeks_back is not None else api_cfg.get("default_weeks_back", 6)
    )

    # Resolve dates using standardized date helper
    try:
        if evaluation_date and isinstance(evaluation_date, str) and evaluation_date.strip():
            end_date = parse_target_date(evaluation_date)
        else:
            end_date = date.today() - timedelta(days=1)
    except Exception as date_err:
        logger.warning(
            f"[Weather Tool Batch] Date parsing error ({date_err}); using yesterday as default."
        )
        end_date = date.today() - timedelta(days=1)
    print("Evaluation Date:", end_date)
    start_date = end_date - timedelta(weeks=resolved_weeks_back)
    max_workers = min(len(stores), api_cfg.get("max_workers", 5)) if stores else 1
    print("Start Date:", start_date, "End Date:", end_date, "Max Workers:", max_workers)

    def _worker(store: StoreInput) -> Tuple[str, Dict[str, Any]]:
        """Worker function for concurrent store weather analysis."""
        query = LocationQuery(
            store_id=store.store_id,
            lat=store.lat,
            long=store.long,
            start_date=start_date,
            end_date=end_date,
        )
        try:
            summary = analyze_store_weather(query)
            return store.store_id, summary.model_dump()
        except Exception as e:
            logger.error(f"[Weather Tool Batch] Worker error for store '{store.store_id}': {e}")
            return store.store_id, {"error": str(e), "store_id": store.store_id}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = dict(executor.map(_worker, stores))

    logger.info(
        f"[Weather Tool Batch Success] Completed parallel weather analysis for all {len(stores)} stores."
    )
    return results
