import os
import re

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from vendor_match_agent.pipeline_config import load_config_set


def run_inclusion_fallback(
    original_tokens: list, stop_words: set, corp_exts: set, generics: set
) -> tuple:
    """
    Algo 3 Standalone Logic:
    Triggers when standard exclusions wipe out all search keywords.
    Re-injects missing identifiers using the priority hierarchy: P3 -> P1 -> P2.
    """
    p3_matches = [t for t in original_tokens if t in generics]
    if p3_matches:
        return p3_matches, "Inclusion Fallback - P3 Generic (Algo 3)"

    p1_matches = [t for t in original_tokens if t in stop_words]
    if p1_matches:
        return p1_matches, "Inclusion Fallback - P1 Stop Words (Algo 3)"

    p2_matches = [t for t in original_tokens if t in corp_exts]
    if p2_matches:
        return p2_matches, "Inclusion Fallback - P2 Corporate Suffix (Algo 3)"

    return original_tokens, "Absolute Safety Fallback"


def execute_cleaning_pipeline(raw_names: list) -> pd.DataFrame:
    """
    M1 & M2 Cleaning Layer: Ingests raw vendor strings, normalizes text to lowercase,
    applies strict token exclusions based on config files, and routes empty results to the
    Inclusion Fallback pipeline.
    """
    corp_exts = load_config_set("corporate_extensions.json")
    generics = load_config_set("generic_business_names.json")
    stop_words = load_config_set("stop_words.json")
    manual_excl = load_config_set("manual_exclusions.json")

    unique_vendors = sorted(list(set(str(n).strip().lower() for n in raw_names if str(n).strip())))
    processed_records = []

    for vendor in unique_vendors:
        original_tokens = re.findall(r"\b\w+\b", vendor)
        if not original_tokens:
            continue

        core_search_words = [
            t
            for t in original_tokens
            if t not in stop_words
            and t not in corp_exts
            and t not in generics
            and t not in manual_excl
        ]
        algo_applied = "Standard Exclusion (Algo 2)"

        if not core_search_words:
            core_search_words, algo_applied = run_inclusion_fallback(
                original_tokens=original_tokens,
                stop_words=stop_words,
                corp_exts=corp_exts,
                generics=generics,
            )

        processed_records.append(
            {
                "Vendor Name": vendor,
                "Cleaned Search Space": ", ".join(core_search_words),
                "Token Count": len(core_search_words),
                "Strategy Applied": algo_applied,
            }
        )

    return pd.DataFrame(processed_records)
