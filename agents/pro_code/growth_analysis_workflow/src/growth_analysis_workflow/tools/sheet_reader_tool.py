"""Google Sheets Reader Tool for Kitchen Performance Metrics.

Reads store performance metrics and geographic coordinates from Google Sheets,
merges datasets on normalized keys using Pandas DataFrames, ranks stores by SSS
performance, and evaluates Core Metrics and Operational Deficits against benchmarks.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from growth_analysis_workflow.config_loader import load_agent_config
from growth_analysis_workflow.utils.data_helpers import clean_key, get_first_col, parse_num
from growth_analysis_workflow.utils.sheets.google_sheets_client import (
    get_all_sheet_names,
    read_google_sheet,
)

logger = logging.getLogger(__name__)

__all__ = [
    "fetch_top_and_bottom_performing_stores",
    "read_google_sheet",
    "get_all_sheet_names",
]


def _apply_column_aliases(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Renames a sheet's own headers to the canonical names the rest of the code uses.

    ``column_aliases`` maps canonical name -> the header as the sheet spells it, so a
    sheet with different headers needs only settings, not code. Matching ignores
    case, spaces and punctuation, as get_first_col does.
    """
    aliases = config.get("column_aliases") or {}
    if not aliases or df.empty:
        return df
    wanted = {clean_key(header): canonical for canonical, header in aliases.items()}
    return df.rename(
        columns={col: wanted[clean_key(col)] for col in df.columns if clean_key(col) in wanted}
    )


def _process_performance_tab(
    spreadsheet_id: str,
    tab_name: str,
    config: Dict[str, Any],
    is_15mo: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, str], Dict[str, Dict[str, float]], Optional[str]]:
    """Reads store performance tab, extracting DataFrames, owner tags, and row-level benchmarks."""
    tab_cfg = config.get("sheet1_15mo" if is_15mo else "sheet1_18mo", {})
    header_row = tab_cfg.get("header_row", 11)
    owner_row = tab_cfg.get("owner_tag_row", 10)
    bench_start = tab_cfg.get("benchmark_start_row", 3)
    bench_end = tab_cfg.get("benchmark_end_row", 6)

    df_raw, raw_matrix = read_google_sheet(spreadsheet_id, f"'{tab_name}'", header_row)
    df_raw = _apply_column_aliases(df_raw, config)
    if df_raw.empty:
        return pd.DataFrame(), {}, {}, None

    raw_headers = df_raw.columns.tolist()

    # 0. Parse Target L6W Date from Cell E1 (Row 1, Column E / Index 4)
    target_date_str = None
    if len(raw_matrix) >= 1 and len(raw_matrix[0]) >= 5:
        cell_e1 = raw_matrix[0][4]
        if cell_e1 and str(cell_e1).strip():
            target_date_str = str(cell_e1).strip()

    # 1. Parse Owner Tags from Row 10
    owner_tags_by_idx: Dict[int, str] = {}
    if len(raw_matrix) >= owner_row:
        row_10 = raw_matrix[owner_row - 1]
        for col_idx, cell_val in enumerate(row_10):
            if cell_val and str(cell_val).strip():
                tag = str(cell_val).strip()
                if not tag.startswith("@"):
                    tag = f"@{tag}"
                owner_tags_by_idx[col_idx] = tag

    # 2. Parse Benchmark Averages from Rows 3 to 6
    benchmarks_by_idx: Dict[int, Dict[str, float]] = {}
    bench_rows = raw_matrix[bench_start - 1 : bench_end]
    for b_row in bench_rows:
        bench_label = None
        for cell in b_row:
            cell_str = str(cell).strip()
            if "simple average" in cell_str.lower():
                bench_label = cell_str
                break

        if not bench_label:
            continue

        for col_idx, cell_val in enumerate(b_row):
            val_num = parse_num(cell_val)
            if val_num is not None:
                if col_idx not in benchmarks_by_idx:
                    benchmarks_by_idx[col_idx] = {}
                benchmarks_by_idx[col_idx][bench_label] = val_num

    # 3. Build DataFrame using get_first_col helper
    target_columns = config.get("table_columns", [])
    metrics_cfg = config.get("metrics_config", {})
    all_needed = (
        target_columns
        + [m["name"] for m in metrics_cfg.get("must_have", [])]
        + [m["name"] for m in metrics_cfg.get("nice_to_have", [])]
    )
    all_needed = list(dict.fromkeys(all_needed))

    df_clean = pd.DataFrame()
    mapped_tags: Dict[str, str] = {}
    mapped_benchmarks: Dict[str, Dict[str, float]] = {}

    for col_name in all_needed:
        col_data = get_first_col(df_raw, col_name)
        if col_data is not None:
            df_clean[col_name] = col_data
            matched_header_name = col_data.name
            if matched_header_name in raw_headers:
                c_idx = raw_headers.index(matched_header_name)
                mapped_tags[col_name] = owner_tags_by_idx.get(c_idx, "")
                mapped_benchmarks[col_name] = benchmarks_by_idx.get(c_idx, {})

    store_col = get_first_col(df_clean, "Kitchen Name")
    if store_col is not None:
        df_clean = df_clean[
            store_col.notna() & (store_col.astype(str).str.strip() != "")
        ].reset_index(drop=True)

    return df_clean, mapped_tags, mapped_benchmarks, target_date_str


def _read_arcgis_sheet(spreadsheet_id: str, config: Dict[str, Any]) -> pd.DataFrame:
    """Reads Sheet 2 (ArcGIS store geography) into a Pandas DataFrame."""
    sheet2_cfg = config.get("sheet2", {})
    tab_name = sheet2_cfg.get("tab_name", "'ArcGIS (HH, At Scale GOV)'")
    header_row = sheet2_cfg.get("header_row", 3)
    target_cols = sheet2_cfg.get("columns", [])

    df_raw, _ = read_google_sheet(spreadsheet_id, tab_name, header_row)
    df_raw = _apply_column_aliases(df_raw, config)
    df_filtered = pd.DataFrame()

    for col_name in target_cols:
        col_data = get_first_col(df_raw, col_name)
        if col_data is not None:
            df_filtered[col_name] = col_data

    strat_col = get_first_col(df_filtered, "strategy_name")
    if strat_col is not None:
        df_filtered = df_filtered[
            strat_col.notna() & (strat_col.astype(str).str.strip() != "")
        ].reset_index(drop=True)

    return df_filtered


def _rank_and_merge_cohorts(
    df_18mo: pd.DataFrame,
    df_15mo: pd.DataFrame,
    df_arcgis: pd.DataFrame,
    config: Dict[str, Any],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Merges DataFrames on normalized join keys and ranks store cohorts."""
    biz_cfg = config.get("business_logic", {})
    sss_col_name = biz_cfg.get("sort_column", "L6W SSS or YoY (Kitchen + MP)")
    key1_name = biz_cfg.get("join_keys", {}).get("sheet1", "Kitchen Name")
    key2_name = biz_cfg.get("join_keys", {}).get("sheet2", "strategy_name")

    strat_col = get_first_col(df_arcgis, key2_name) if not df_arcgis.empty else None
    if strat_col is not None:
        df_arcgis["join_key"] = strat_col.apply(clean_key)
    else:
        df_arcgis["join_key"] = ""

    def _prepare_cohort(df: pd.DataFrame) -> pd.DataFrame:
        """Joins cohort data with ArcGIS location details and adds numerical SSS sort key."""
        if df.empty:
            return pd.DataFrame()
        store_c = get_first_col(df, key1_name)
        if store_c is None:
            return pd.DataFrame()
        df["join_key"] = store_c.apply(clean_key)
        merged = pd.merge(df, df_arcgis, on="join_key", how="left").drop(columns=["join_key"])

        sss_c = get_first_col(merged, sss_col_name)
        if sss_c is not None:
            merged["_sss_sort_value"] = sss_c.apply(parse_num)
        else:
            merged["_sss_sort_value"] = 0.0
        return merged

    merged_18mo = _prepare_cohort(df_18mo)
    merged_15mo = _prepare_cohort(df_15mo)

    # 1. 18mo Cohort Top & Bottom
    b18_count = biz_cfg.get("bottom_18mo_count", 5)
    top_count = biz_cfg.get("top_stores_count", 5)

    bottom_18mo = (
        (
            merged_18mo[merged_18mo["_sss_sort_value"] < 0]
            .sort_values(by="_sss_sort_value", ascending=True)
            .head(b18_count)
            .drop(columns=["_sss_sort_value"])
            .reset_index(drop=True)
        )
        if not merged_18mo.empty
        else pd.DataFrame()
    )

    top_18mo = (
        (
            merged_18mo[merged_18mo["_sss_sort_value"] >= 0]
            .sort_values(by="_sss_sort_value", ascending=False)
            .head(top_count)
            .drop(columns=["_sss_sort_value"])
            .reset_index(drop=True)
        )
        if not merged_18mo.empty
        else pd.DataFrame()
    )

    # 2. 15mo Cohort Bottom - EXCLUDE STORES ALREADY IN bottom_18mo
    b15_count = biz_cfg.get("bottom_15mo_count", 3)

    if not merged_15mo.empty:
        merged_15mo_filtered = merged_15mo[merged_15mo["_sss_sort_value"] < 0].sort_values(
            by="_sss_sort_value", ascending=True
        )

        if not bottom_18mo.empty:
            b18_store_names = set(bottom_18mo["Kitchen Name"].astype(str).str.strip().str.lower())
            store_col_15 = get_first_col(merged_15mo_filtered, "Kitchen Name")
            if store_col_15 is not None:
                is_not_in_18mo = ~store_col_15.astype(str).str.strip().str.lower().isin(
                    b18_store_names
                )
                merged_15mo_filtered = merged_15mo_filtered[is_not_in_18mo]

        bottom_15mo = (
            merged_15mo_filtered.head(b15_count)
            .drop(columns=["_sss_sort_value"])
            .reset_index(drop=True)
        )
    else:
        bottom_15mo = pd.DataFrame()

    return bottom_18mo, bottom_15mo, top_18mo


def _evaluate_store_tldr_metrics(
    store_row: pd.Series,
    owner_tags: Dict[str, str],
    benchmarks: Dict[str, Dict[str, float]],
    metrics_cfg: Dict[str, Any],
    cohort_label: str,
) -> Dict[str, Any]:
    """Evaluates Core Metrics and Operational Benchmark Deficits for a single store."""
    store_name = str(store_row.get("Kitchen Name", store_row.get("Store Name", "Unknown Store")))
    pop_type = str(store_row.get("Population Type", store_row.get("Pop Type", ""))).strip()

    must_haves = metrics_cfg.get("must_have", [])
    nice_to_haves = metrics_cfg.get("nice_to_have", [])

    pop_type_clean = pop_type.lower()
    is_suburban = "suburb" in pop_type_clean
    is_urban = "urban" in pop_type_clean and not is_suburban

    def _get_bench_val(col_name: str) -> Optional[float]:
        """Resolves cohort benchmark value matching store population type (Suburban, Urban, or Total)."""
        col_benchmarks = benchmarks.get(col_name, {})
        for b_key, b_num in col_benchmarks.items():
            b_key_clean = b_key.lower()
            if is_suburban and "suburb" in b_key_clean:
                return b_num
            elif is_urban and ("urban" in b_key_clean and "suburb" not in b_key_clean):
                return b_num
        for b_key, b_num in col_benchmarks.items():
            if "total" in b_key.lower():
                return b_num
        return None

    evaluated_must_haves = []
    for cfg in must_haves:
        col_name = cfg["name"]
        val = store_row.get(col_name) if col_name in store_row else None
        val_num = parse_num(val)
        tag = owner_tags.get(col_name, "")
        bench_val = _get_bench_val(col_name)

        higher_is_better = cfg.get("higher_is_better", True)
        is_deficit = False
        if val_num is not None and bench_val is not None:
            is_deficit = (val_num < bench_val) if higher_is_better else (val_num > bench_val)

        evaluated_must_haves.append(
            {
                "metric": col_name,
                "value": val,
                "benchmark_value": bench_val,
                "is_deficit": is_deficit,
                "owner_tag": tag,
            }
        )

    failing_nice_to_haves = []
    for cfg in nice_to_haves:
        col_name = cfg["name"]
        if col_name not in store_row:
            continue

        raw_val = store_row.get(col_name)
        if pd.isna(raw_val) or raw_val is None:
            continue

        val_num = parse_num(raw_val)
        if val_num is None:
            continue

        tag = owner_tags.get(col_name, "")
        bench_val = _get_bench_val(col_name)

        if bench_val is not None:
            higher_is_better = cfg.get("higher_is_better", True)
            is_underperforming = (
                (val_num < bench_val) if higher_is_better else (val_num > bench_val)
            )

            if bool(is_underperforming):
                failing_nice_to_haves.append(
                    {
                        "metric": col_name,
                        "store_value": raw_val,
                        "benchmark_value": bench_val,
                        "owner_tag": tag,
                    }
                )

    return {
        "store_name": store_name,
        "cohort": cohort_label,
        "population_type": pop_type,
        "core_performance_metrics": evaluated_must_haves,
        "operational_benchmark_deficits": failing_nice_to_haves,
    }


def fetch_top_and_bottom_performing_stores(
    spreadsheet_id: Optional[str] = None,
    tool_context: Any = None,
) -> str:
    """ADK Tool: Reads metrics and location data from Google Sheets across 18mo/15mo cohorts."""
    try:
        config = load_agent_config("sheet_reader_agent")
        target_id = spreadsheet_id or config.get("spreadsheet_id")

        cfg_18mo = config.get("sheet1_18mo", {})
        tab_18mo = cfg_18mo.get("tab_name", "L6W SSS Summary (18 Mo.)")
        df_18mo, tags_18mo, bench_18mo, date_18mo = _process_performance_tab(
            target_id, tab_18mo, config, is_15mo=False
        )

        cfg_15mo = config.get("sheet1_15mo", {})
        tab_15mo = cfg_15mo.get("tab_name", "L6W SSS Summary (15 Mo.)")
        df_15mo, tags_15mo, bench_15mo, date_15mo = _process_performance_tab(
            target_id, tab_15mo, config, is_15mo=True
        )

        target_date = date_18mo or date_15mo
        df_arcgis = _read_arcgis_sheet(target_id, config)
        bottom_18mo, bottom_15mo, top_18mo = _rank_and_merge_cohorts(
            df_18mo, df_15mo, df_arcgis, config
        )

        metrics_cfg = config.get("metrics_config", {})
        tldr_evaluations = []

        if not bottom_18mo.empty:
            for _, row in bottom_18mo.iterrows():
                tldr_evaluations.append(
                    _evaluate_store_tldr_metrics(row, tags_18mo, bench_18mo, metrics_cfg, "18 Mo.")
                )

        if not bottom_15mo.empty:
            for _, row in bottom_15mo.iterrows():
                tldr_evaluations.append(
                    _evaluate_store_tldr_metrics(row, tags_15mo, bench_15mo, metrics_cfg, "15 Mo.")
                )

        underperforming_agent_input = []
        for df_cohort in [bottom_18mo, bottom_15mo]:
            if not df_cohort.empty:
                for _, row in df_cohort.iterrows():
                    underperforming_agent_input.append(
                        {
                            "store_name": str(row.get("Kitchen Name", "Store")),
                            "lat": row.get("lat"),
                            "long": row.get("long"),
                            "city": row.get("city"),
                            "state": row.get("state"),
                            "dma": row.get("dma"),
                            "target_date": target_date,
                        }
                    )

        payload = {
            "status": "success",
            "tldr_store_evaluations": tldr_evaluations,
            "bottom_5_18mo_stores": bottom_18mo.to_dict(orient="records")
            if not bottom_18mo.empty
            else [],
            "bottom_3_15mo_stores": bottom_15mo.to_dict(orient="records")
            if not bottom_15mo.empty
            else [],
            "top_5_18mo_stores": top_18mo.to_dict(orient="records") if not top_18mo.empty else [],
            "bottom_5_weather_agent_input": underperforming_agent_input,
            "bottom_5_qsr_market_research_agent_input": underperforming_agent_input,
            "bottom_5_local_news_agent_input": underperforming_agent_input,
            "bottom_5_macro_labor_agent_input": underperforming_agent_input,
            "bottom_5_google_reviews_agent_input": underperforming_agent_input,
        }

        # Write result to ToolContext session state if available
        if tool_context and hasattr(tool_context, "state"):
            try:
                tool_context.state["kitchen_sheet_data"] = payload
                logger.info(
                    "[ADK State] Saved kitchen sheet metrics to tool_context.state['kitchen_sheet_data']"
                )
            except Exception as st_err:
                logger.warning(f"[ADK State] Could not save to state: {st_err}")

        return json.dumps(payload, indent=2)

    except Exception as e:
        logger.error(f"Error encountered in fetch_top_and_bottom_performing_stores: {e}")
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
