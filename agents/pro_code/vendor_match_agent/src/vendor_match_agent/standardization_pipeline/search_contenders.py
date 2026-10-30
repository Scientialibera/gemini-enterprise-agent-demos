import logging
import os
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)


from vendor_match_agent.pipeline_config import load_config_set, load_yaml_config

CONFIG = load_yaml_config("config/pipeline_config.yaml")

_SIMILARITY_CFG = CONFIG.get("resolver_agent", {}).get("similarity_search", {})
MIN_TOKEN_LENGTH: int = _SIMILARITY_CFG.get("min_token_length", 2)
MAX_CONTENDERS: int = _SIMILARITY_CFG.get("max_contenders_per_vendor", 15)


def build_inverted_token_index(
    df_cleaned: list, generics: set, min_token_length: int = MIN_TOKEN_LENGTH
) -> dict:
    """Builds an inverted token index excluding generic business terms from config files."""
    token_index = defaultdict(set)

    for record in df_cleaned:
        vendor_name = record["Vendor Name"]
        search_space = record.get("Cleaned Search Space", "")

        if not search_space:
            continue

        if isinstance(search_space, list):
            tokens = [str(t).strip().lower() for t in search_space if str(t).strip() != ""]
        else:
            tokens = [t.strip().lower() for t in str(search_space).split(",") if t.strip() != ""]

        for token in tokens:
            if token not in generics and len(token) >= min_token_length:
                token_index[token].add(vendor_name)

    return token_index


def gather_possible_contenders(df_cleaned: list, max_contenders: int = MAX_CONTENDERS) -> list:
    """
    Cross-references vendor clean search space against inverted index.
    Ranks contenders by token overlap count before capping to top contenders.
    """
    generics = load_config_set("generic_business_names.json")
    inverted_index = build_inverted_token_index(
        df_cleaned, generics, min_token_length=MIN_TOKEN_LENGTH
    )

    contender_records = []

    for record in df_cleaned:
        vendor_name = record["Vendor Name"]
        search_space = record.get("Cleaned Search Space", "")

        if not search_space:
            contender_records.append(
                {"Vendor Name": vendor_name, "Cleaned Search Space": "", "Contender Pool": []}
            )
            continue

        if isinstance(search_space, list):
            tokens = [str(t).strip().lower() for t in search_space if str(t).strip() != ""]
            search_space_str = ", ".join(tokens)
        else:
            tokens = [t.strip().lower() for t in str(search_space).split(",") if t.strip() != ""]
            search_space_str = str(search_space)

        # Count token overlap frequency for every candidate
        candidate_overlap_counts = defaultdict(int)
        for token in tokens:
            if token in inverted_index:
                for candidate in inverted_index[token]:
                    if candidate != vendor_name:
                        candidate_overlap_counts[candidate] += 1

        # Rank candidates by highest token overlap count first, then alphabetically as tie-breaker
        ranked_candidates = sorted(
            candidate_overlap_counts.keys(), key=lambda c: (-candidate_overlap_counts[c], c.lower())
        )[:max_contenders]

        contender_records.append(
            {
                "Vendor Name": vendor_name,
                "Cleaned Search Space": search_space_str,
                "Contender Pool": ranked_candidates,
            }
        )

    return contender_records
