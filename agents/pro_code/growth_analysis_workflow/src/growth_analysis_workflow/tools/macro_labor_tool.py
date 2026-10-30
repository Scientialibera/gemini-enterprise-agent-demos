"""Production Batch Macro & Labor Tool with Dynamic BLS Series ID Generation and L6W Date Windowing."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from gemini_shared.secrets import optional_secret

from growth_analysis_workflow.config_loader import load_agent_config
from growth_analysis_workflow.models.macro_models import (
    BlsMacroDetails,
    FredRetailSalesDetails,
    MacroLaborSummary,
    StateUnemploymentDetail,
    StoreInput,
)
from growth_analysis_workflow.tools import sample_external
from growth_analysis_workflow.utils.date_helpers import get_l6w_date_bounds

logger = logging.getLogger(__name__)

# Dynamic configuration loading from dedicated macro_labor_agent.yaml
macro_cfg = load_agent_config("macro_labor_agent")
fred_cfg = macro_cfg.get("fred", {})
bls_cfg = macro_cfg.get("bls", {})
bls_series_cfg = bls_cfg.get("series_ids", {})
STATE_FIPS_MAP: Dict[str, str] = macro_cfg.get("state_fips_map", {})


def generate_bls_unemployment_series_id(
    state: str,
    fips_map: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Dynamically generates the official BLS LAUS 18-character Series ID for ANY U.S. state.

    Args:
        state: Two-letter state postal abbreviation.
        fips_map: Optional state-to-FIPS mapping dictionary; defaults to config map.

    Returns:
        Optional[str]: Formatted 18-character series ID (e.g. 'LAUST060000000000003' for CA), or None.
    """
    mapping = fips_map if fips_map is not None else STATE_FIPS_MAP
    clean_state = state.upper().strip()
    fips = mapping.get(clean_state)
    if not fips:
        return None
    return f"LAUST{fips}0000000000003"


def fetch_fred_food_services_sales(
    observation_start: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetches Advance Retail Sales in Food Services from FRED filtered by start date.

    Args:
        observation_start: Optional earliest observation date string (YYYY-MM-DD).

    Returns:
        Tuple of (value_millions_usd, observation_date, error_message).
    """
    api_key = optional_secret("FRED_API_KEY_SECRET")
    if not api_key:
        return None, None, "FRED_API_KEY missing"

    url = fred_cfg.get("url", "https://api.stlouisfed.org/fred/series/observations")
    series_id = fred_cfg.get("series_id", "RSFSDPN")
    timeout_sec = fred_cfg.get("timeout_seconds", 10)

    params = {
        "series_id": series_id,
        "api_key": api_key.strip(),
        "file_type": "json",
    }
    if observation_start:
        params["observation_start"] = observation_start

    headers = {
        "User-Agent": "GrowthAnalyticsAgent/1.0 (dev-team@company.com)",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=timeout_sec)
        response.raise_for_status()
        data = response.json()
        observations = data.get("observations", [])

        if observations:
            latest = observations[-1]
            val = latest.get("value", "N/A")
            obs_date = latest.get("date", "N/A")
            return val, obs_date, None

    except requests.RequestException as req_err:
        logger.error(f"[Macro Tool ERROR] FRED API HTTP request failed: {req_err}")
        return None, None, str(req_err)
    except Exception as err:
        logger.error(f"[Macro Tool ERROR] FRED API parsing error: {err}")
        return None, None, str(err)

    return None, None, "No observations found"


def _parse_bls_series_payload(
    series_list: List[Dict[str, Any]],
    state_to_series_map: Dict[str, Tuple[str, str]],
    cpi_series_id: str,
    national_unemp_series_id: str,
) -> BlsMacroDetails:
    """Helper: Parses raw BLS series results into structured BlsMacroDetails model.

    Args:
        series_list: List of series item dictionaries from BLS API.
        state_to_series_map: Map of BLS series ID to tuple of (state_code, series_id).
        cpi_series_id: Series identifier for CPI Food Away From Home.
        national_unemp_series_id: Series identifier for National Unemployment.

    Returns:
        BlsMacroDetails: Populated macro labor details object.
    """
    details = BlsMacroDetails()

    for s_item in series_list:
        sid = s_item.get("seriesID", "")
        data_points = s_item.get("data", [])

        if not data_points:
            continue

        latest_point = data_points[0]
        val = latest_point.get("value", "N/A")
        period_str = f"{latest_point.get('periodName', '')} {latest_point.get('year', '')}"

        if sid == cpi_series_id:
            # Calculate YoY inflation dynamically if at least 13 months of historical data points exist
            yoy_str = ""
            if len(data_points) >= 13:
                try:
                    latest_val = float(data_points[0].get("value", 0))
                    prior_year_val = float(data_points[12].get("value", 0))
                    if prior_year_val > 0:
                        yoy_pct = ((latest_val - prior_year_val) / prior_year_val) * 100
                        yoy_str = f", reflecting +{yoy_pct:.1f}% YoY inflation"
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

            details.cpi_summary = f"CPI Food Away From Home at index {val} ({period_str}){yoy_str}."
        elif sid == national_unemp_series_id:
            details.national_unemployment_rate = f"{val}% ({period_str})"
        elif sid in state_to_series_map:
            st_code, dynamic_sid = state_to_series_map[sid]
            details.state_unemployment_rates[st_code] = StateUnemploymentDetail(
                series_id=dynamic_sid,
                rate=f"{val}% ({period_str})",
            )

    return details


def fetch_bls_cpi_and_labor_batch(
    states: List[str],
    start_year: str,
    end_year: str,
) -> Tuple[BlsMacroDetails, Optional[str]]:
    """Fetches CPI Inflation, National Unemployment, and State Unemployment rates dynamically by year range.

    Args:
        states: List of two-letter state postal abbreviations.
        start_year: Beginning calendar year string (e.g. '2026').
        end_year: Ending calendar year string (e.g. '2026').

    Returns:
        Tuple of (BlsMacroDetails, error_message).
    """
    url = bls_cfg.get("url", "https://api.bls.gov/publicAPI/v2/timeseries/data/")
    timeout_sec = bls_cfg.get("timeout_seconds", 10)
    cpi_sid = bls_series_cfg.get("cpi_food_away", "CUUR0000SEFV")
    nat_unemp_sid = bls_series_cfg.get("national_unemployment", "LNS14000000")

    series_ids = [cpi_sid, nat_unemp_sid]

    state_to_series_map: Dict[str, Tuple[str, str]] = {}
    for st in states:
        sid = generate_bls_unemployment_series_id(st)
        if sid and sid not in series_ids:
            series_ids.append(sid)
            state_to_series_map[sid] = (st.upper().strip(), sid)

    payload: Dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": start_year,
        "endyear": end_year,
    }

    api_key = optional_secret("BLS_API_KEY_SECRET")
    if api_key:
        payload["registrationkey"] = api_key.strip()

    try:
        response = requests.post(url, json=payload, timeout=timeout_sec)
        response.raise_for_status()
        data = response.json()
        series_list = data.get("Results", {}).get("series", [])

        details = _parse_bls_series_payload(
            series_list=series_list,
            state_to_series_map=state_to_series_map,
            cpi_series_id=cpi_sid,
            national_unemp_series_id=nat_unemp_sid,
        )
        return details, None

    except requests.RequestException as req_err:
        logger.error(f"[Macro Tool ERROR] BLS API HTTP request failed: {req_err}")
        err_details = BlsMacroDetails()
        err_details.error = str(req_err)
        return err_details, str(req_err)
    except Exception as err:
        logger.error(f"[Macro Tool ERROR] BLS API processing failed: {err}")
        err_details = BlsMacroDetails()
        err_details.error = str(err)
        return err_details, str(err)


def fetch_macro_labor_batch(
    stores: List[StoreInput],
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure batch tool: Queries FRED and BLS macro & labor endpoints within dynamic L6W timeframe.

    Args:
        stores: List of StoreInput objects.
        target_date: Optional reference date string (YYYY-MM-DD).

    Returns:
        Dict[str, Any]: Aggregated macroeconomic and state labor metrics.
    """
    if sample_external.enabled():
        return sample_external.macro_labor()
    window_days = macro_cfg.get("window_days", 42)
    l6w_start_date, ref_date = get_l6w_date_bounds(target_date, days_back=window_days)

    start_year = str(l6w_start_date.year)
    end_year = str(ref_date.year)

    # FRED monthly series use 1st-of-month dates and have a publication lag.
    # Set observation_start to lookback days prior, aligned to day 1, so FRED returns the latest released data point.
    fred_lookback_days = fred_cfg.get("lookback_days", 90)
    fred_lookback = (l6w_start_date - timedelta(days=fred_lookback_days)).replace(day=1)
    fred_obs_start = fred_lookback.strftime("%Y-%m-%d")

    logger.info(
        f"[Macro Tool Batch] Executing macro & labor analysis for {len(stores)} store locations (L6W target: {ref_date})..."
    )

    unique_states = sorted(list(set(s.state.upper().strip() for s in stores if s.state)))
    max_workers = macro_cfg.get("max_workers", 2)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            fred_future = executor.submit(fetch_fred_food_services_sales, fred_obs_start)
            bls_future = executor.submit(
                fetch_bls_cpi_and_labor_batch, unique_states, start_year, end_year
            )

            fred_val, fred_date, fred_err = fred_future.result()
            bls_details, bls_err = bls_future.result()

        summary = MacroLaborSummary(
            fred_retail_sales=FredRetailSalesDetails(
                value_millions_usd=fred_val,
                date=fred_date,
                error=fred_err,
            ),
            bls_macro_and_labor=bls_details,
            covered_states=unique_states,
        )

        logger.info(
            "[Macro Tool Batch Success] Macroeconomic & labor data successfully aggregated."
        )
        return summary.model_dump()
    except Exception as batch_err:
        logger.error(f"[Macro Tool Batch ERROR] Macro analysis batch execution failed: {batch_err}")
        return {"error": str(batch_err), "covered_states": unique_states}
