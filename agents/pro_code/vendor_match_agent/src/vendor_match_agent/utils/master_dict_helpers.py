import os
from typing import Dict, List, Tuple

import pandas as pd

from vendor_match_agent.pipeline_config import load_config_set, load_yaml_config
from vendor_match_agent.tools.drive_tools import (
    download_file_from_drive,
    export_gsheet_to_excel,
    list_files_in_folder,
    upload_excel_to_drive,
)

CONFIG = load_yaml_config("config/pipeline_config.yaml")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from vendor_match_agent.utils.text_helpers import (
    normalize_key,
    normalize_key_alpha_numeric,
    normalize_key_fuzzy,
)


def load_master_dictionary_cache(
    master_folder_id: str, temp_dir: str
) -> Tuple[Dict[str, str], pd.DataFrame, str]:
    """Downloads master dictionary from Drive and builds exact, fuzzy, and alphanumeric lookup caches."""
    lookup_cache = {}
    master_filename = (
        CONFIG.get("drive", {})
        .get("files", {})
        .get(
            "master_dict_filename",
            CONFIG.get("pipeline", {}).get("master_dict_filename", "master_vendor_dictionary.xlsx"),
        )
    )
    master_sheet = (
        CONFIG.get("drive", {})
        .get("files", {})
        .get(
            "master_sheet_name",
            CONFIG.get("pipeline", {}).get("master_sheet_name", "Master Dictionary"),
        )
    )
    std_col_name = (
        CONFIG.get("governance", {})
        .get("master_dictionary_columns", {})
        .get("standardized_name", "Standardized Vendor Name")
    )
    var_col_name = (
        CONFIG.get("governance", {})
        .get("master_dictionary_columns", {})
        .get("raw_variant", "Raw Vendor Variant")
    )
    base_name_clean = master_filename.replace(".xlsx", "").lower().strip()

    corp_exts = load_config_set("corporate_extensions.json")
    manual_excl = load_config_set("manual_exclusions.json")

    files_found = list_files_in_folder(master_folder_id)

    target_file = next(
        (
            f
            for f in files_found
            if f["name"].lower().strip() in [master_filename.lower(), base_name_clean]
        ),
        None,
    )

    if target_file:
        file_id = target_file["id"]
        mime_type = target_file.get("mimeType", "")
        local_master_path = os.path.join(temp_dir, master_filename)

        if mime_type == "application/vnd.google-apps.spreadsheet":
            export_gsheet_to_excel(file_id, local_master_path)
        else:
            try:
                download_file_from_drive(file_id, local_master_path)
            except Exception:
                export_gsheet_to_excel(file_id, local_master_path)

        try:
            df_existing_master = pd.read_excel(local_master_path, sheet_name=master_sheet)

            col_std = (
                std_col_name
                if std_col_name in df_existing_master.columns
                else df_existing_master.columns[0]
            )
            col_var = (
                var_col_name
                if var_col_name in df_existing_master.columns
                else df_existing_master.columns[1]
            )

            for _, row in df_existing_master.iterrows():
                std_name = str(row.get(col_std, "")).strip()
                raw_variant = str(row.get(col_var, "")).strip()

                norm_variant = normalize_key(raw_variant)
                fuzzy_variant = normalize_key_fuzzy(raw_variant, corp_exts, manual_excl)
                alpha_variant = normalize_key_alpha_numeric(raw_variant)

                if std_name and norm_variant:
                    lookup_cache[norm_variant] = std_name
                if std_name and fuzzy_variant and fuzzy_variant not in lookup_cache:
                    lookup_cache[fuzzy_variant] = std_name
                if std_name and alpha_variant and alpha_variant not in lookup_cache:
                    lookup_cache[alpha_variant] = std_name

            return lookup_cache, df_existing_master, file_id
        except Exception as e:
            print(f"⚠️ [WARNING] Could not parse existing Master Dictionary sheet: {e}")

    df_empty_master = pd.DataFrame(columns=["Standardized Vendor Name", "Raw Vendor Variant"])
    return lookup_cache, df_empty_master, None


def execute_fast_master_lookup(
    raw_names: List[str], lookup_cache: Dict[str, str]
) -> Tuple[Dict[str, List[str]], List[str]]:
    """Stage 1: Filters raw vendor inputs against exact, fuzzy, and alphanumeric normalized master lookup keys."""
    known_resolved_map = {}
    unmatched_raw_names = []

    corp_exts = load_config_set("corporate_extensions.json")
    manual_excl = load_config_set("manual_exclusions.json")

    unique_raw_inputs = sorted(list(set(str(n).strip() for n in raw_names if str(n).strip())))

    for vendor in unique_raw_inputs:
        norm_vendor = normalize_key(vendor)
        fuzzy_vendor = normalize_key_fuzzy(vendor, corp_exts, manual_excl)
        alpha_vendor = normalize_key_alpha_numeric(vendor)

        master_name = (
            lookup_cache.get(norm_vendor)
            or lookup_cache.get(fuzzy_vendor)
            or lookup_cache.get(alpha_vendor)
        )

        if master_name:
            if master_name not in known_resolved_map:
                known_resolved_map[master_name] = []
            known_resolved_map[master_name].append(vendor)
        else:
            unmatched_raw_names.append(vendor)

    return known_resolved_map, unmatched_raw_names


def commit_new_mappings_to_master(
    approved_new_mappings: Dict[str, List[str]], master_folder_id: str, temp_dir: str
) -> str:
    """Stage 4A: Appends new approved vendor mappings to master_vendor_dictionary.xlsx in Drive."""
    master_filename = (
        CONFIG.get("drive", {})
        .get("files", {})
        .get(
            "master_dict_filename",
            CONFIG.get("pipeline", {}).get("master_dict_filename", "master_vendor_dictionary.xlsx"),
        )
    )
    master_sheet = (
        CONFIG.get("drive", {})
        .get("files", {})
        .get(
            "master_sheet_name",
            CONFIG.get("pipeline", {}).get("master_sheet_name", "Master Dictionary"),
        )
    )
    std_col_name = (
        CONFIG.get("governance", {})
        .get("master_dictionary_columns", {})
        .get("standardized_name", "Standardized Vendor Name")
    )
    var_col_name = (
        CONFIG.get("governance", {})
        .get("master_dictionary_columns", {})
        .get("raw_variant", "Raw Vendor Variant")
    )

    lookup_cache, df_existing, _ = load_master_dictionary_cache(master_folder_id, temp_dir)
    initial_count = len(df_existing)

    # Dynamic column identification
    col_std = std_col_name if std_col_name in df_existing.columns else df_existing.columns[0]
    col_var = (
        var_col_name
        if var_col_name in df_existing.columns
        else (df_existing.columns[1] if len(df_existing.columns) > 1 else var_col_name)
    )

    # FIX: Exact case-insensitive raw text deduplication
    # Allows new raw variant strings from Tab 2 to be appended even if normalized keys collide
    existing_raw_variants = set(
        df_existing[col_var].dropna().astype(str).str.strip().str.lower().tolist()
    )

    new_rows = []
    for master_name, variants in approved_new_mappings.items():
        clean_master = str(master_name).strip()
        for variant in variants:
            clean_var = str(variant).strip()
            var_lower = clean_var.lower()

            # Append if this exact raw text variant string does NOT exist in Master Dictionary
            if clean_var and var_lower not in existing_raw_variants:
                new_rows.append({col_std: clean_master, col_var: clean_var})
                existing_raw_variants.add(var_lower)

    if not new_rows:
        print(
            f"ℹ️ [NO CHANGE] All proposed variants already exist in Master Dictionary. Total rows: {initial_count}"
        )
        local_master_path = os.path.join(temp_dir, master_filename)
        with pd.ExcelWriter(local_master_path, engine="openpyxl") as writer:
            df_existing.to_excel(writer, sheet_name=master_sheet, index=False)
        return upload_excel_to_drive(
            local_path=local_master_path, filename=master_filename, folder_id=master_folder_id
        )

    df_new = pd.DataFrame(new_rows)
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    final_count = len(df_combined)

    print(
        f"📊 [STRICT APPEND] Initial rows: {initial_count} | New rows added: {len(new_rows)} | Final rows: {final_count}"
    )

    local_master_path = os.path.join(temp_dir, master_filename)
    with pd.ExcelWriter(local_master_path, engine="openpyxl") as writer:
        df_combined.to_excel(writer, sheet_name=master_sheet, index=False)

    return upload_excel_to_drive(
        local_path=local_master_path, filename=master_filename, folder_id=master_folder_id
    )
