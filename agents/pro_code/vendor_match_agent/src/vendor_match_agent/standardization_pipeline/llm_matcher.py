import concurrent.futures
import json
import logging
import os
import random
import re
import time
from typing import Dict, List, Tuple

from gemini_shared import get_runtime_config
from gemini_shared.runtime import create_genai_client
from google import genai
from google.genai import types

from vendor_match_agent.config import BOOTSTRAP
from vendor_match_agent.pipeline_config import load_config_set, load_prompt, load_yaml_config
from vendor_match_agent.standardization_pipeline.resolver_agent import VendorResolution

CONFIG = load_yaml_config("config/pipeline_config.yaml")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)


def parse_resolution_response(response_text: str) -> VendorResolution:
    """Cleans markdown JSON containers and enforces native Pydantic validation for a single record."""
    if not response_text or not response_text.strip():
        raise ValueError("Received completely empty text response from LLM model.")

    cleaned = re.sub(r"^```(?:json)?\s*", "", response_text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    raw_dict = json.loads(cleaned)
    return VendorResolution(**raw_dict)


def process_vendor_task(record: dict, client: genai.Client, model_name: str) -> tuple:
    """Worker function executing direct, thread-safe LLM queries with zero session overhead."""
    vendor_target_name = record["Vendor Name"]
    input_payload = json.dumps(record)

    system_instruction = load_prompt("resolution_agent_instruction")
    user_prompt_template = load_prompt("resolution_user_prompt")
    prompt = user_prompt_template.format(input_payload=input_payload)

    model_cfg = CONFIG.get("resolver_agent", {}).get("model", {})
    max_retries = model_cfg.get("max_retries", CONFIG.get("model", {}).get("max_retries", 5))
    backoff_rate = model_cfg.get("rate_limit_backoff_factor", 2.5)
    jitter_min = model_cfg.get("jitter_min", 0.3)
    jitter_max = model_cfg.get("jitter_max", 1.5)

    for attempt in range(1, max_retries + 1):
        try:
            # Direct API call: 0.5s response time, 0 session locks, 0 ADK overhead
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=VendorResolution,
                ),
            )

            response_text = response.text or ""
            result_record = parse_resolution_response(response_text)
            logger.debug(
                f"✅ Resolved '{vendor_target_name}' -> '{result_record.standardized_vendor_name}'"
            )
            return True, vendor_target_name, result_record

        except Exception as e:
            error_str = str(e)
            is_429 = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "Quota" in error_str

            if attempt < max_retries:
                base_sleep = (backoff_rate * attempt) if is_429 else (1.2**attempt)
                jitter = random.uniform(jitter_min, jitter_max)
                sleep_time = base_sleep + jitter
                logger.warning(
                    f"⚡ [RETRY {attempt}/{max_retries}] Vendor '{vendor_target_name}' ({type(e).__name__}). Sleeping {sleep_time:.2f}s..."
                )
                time.sleep(sleep_time)
            else:
                logger.error(
                    f"❌ [PERMANENT FAILURE] Vendor '{vendor_target_name}' | Error: {type(e).__name__} - {e}"
                )
                return False, vendor_target_name, None


def clean_master_key(key_str: str, corp_exts: set) -> str:
    """Strips corporate legal extensions and trailing punctuation dynamically."""
    s = key_str.lower()
    tokens = re.findall(r"\b\w+\b", s)
    filtered = [t for t in tokens if t not in corp_exts]
    clean = " ".join(filtered).strip()
    return re.sub(r"[\s,._-]+$", "", clean)


def consolidate_master_dictionary(raw_master_dict: dict, corp_exts: set) -> dict:
    """High-performance consolidation pass pre-cleaning variants to eliminate freeze on large datasets."""
    sorted_keys = sorted(
        raw_master_dict.keys(), key=lambda k: (len(clean_master_key(k, corp_exts)), k.lower())
    )
    consolidated = {}

    for key in sorted_keys:
        variants = set(raw_master_dict[key])
        clean_k = clean_master_key(key, corp_exts)
        merged = False

        for master, existing_variants in consolidated.items():
            clean_m = clean_master_key(master, corp_exts)
            clean_existing = {clean_master_key(v, corp_exts) for v in existing_variants}

            if clean_k == clean_m or clean_k in clean_existing:
                existing_variants.update(variants)
                existing_variants.add(key)
                merged = True
                break

        if not merged:
            consolidated[key] = variants

    final_output = {}
    seen_variants = set()

    for master, variants_set in consolidated.items():
        clean_master = re.sub(r"[\s,._-]+$", "", master.strip()).strip()
        unique_variants = []

        for v in sorted(list(variants_set)):
            v_clean = v.strip()
            if not v_clean:
                continue
            if v_clean.lower() not in seen_variants:
                seen_variants.add(v_clean.lower())
                unique_variants.append(v_clean)

        if unique_variants:
            final_output[clean_master] = unique_variants

    return final_output


def _segregate_contender_pools(contender_pools: List[dict]) -> Tuple[List[str], List[dict]]:
    """Segregates vendor candidate records into standalones (0 contenders) and LLM-required pools.

    Args:
        contender_pools: List of candidate records containing 'Vendor Name' and 'Contender Pool'.

    Returns:
        Tuple of (standalone_vendor_names, llm_required_records).
    """
    standalone_items = []
    llm_required_items = []

    for record in contender_pools:
        try:
            if len(record.get("Contender Pool", [])) == 0:
                standalone_items.append(record["Vendor Name"])
            else:
                llm_required_items.append(record)
        except Exception as err:
            logger.warning(
                f"⚠️ [WARNING] Malformed contender record skipped: {record}. Error: {err}"
            )

    return standalone_items, llm_required_items


def _map_standalone_entities(standalone_items: List[str], corp_exts: set) -> Dict[str, set]:
    """Instantly maps standalone vendors without contender ambiguity directly to master keys.

    Args:
        standalone_items: List of raw vendor names with 0 candidate contenders.
        corp_exts: Set of corporate suffixes to strip for canonical master naming.

    Returns:
        Dictionary mapping standardized master names to sets of raw vendor strings.
    """
    master_dict = {}
    logger.info(f"🧠 Pass 1: Instantly mapping {len(standalone_items)} standalone entities...")

    for vendor in standalone_items:
        try:
            clean_v = vendor.strip()
            clean_master = clean_master_key(clean_v, corp_exts).title()
            master_key = clean_master if clean_master else clean_v.title()
            master_key = re.sub(r"[\s,._-]+$", "", master_key).strip()

            if master_key not in master_dict:
                master_dict[master_key] = set()
            master_dict[master_key].add(clean_v)
        except Exception as err:
            logger.warning(f"⚠️ [WARNING] Failed to map standalone vendor '{vendor}': {err}")

    return master_dict


def _execute_multithreaded_llm_resolution(
    llm_required_items: List[dict],
    n_threads: int,
    model_name: str,
) -> Dict[str, set]:
    """Executes multi-threaded parallel LLM queries to deduplicate complex vendor records.

    Args:
        llm_required_items: List of candidate records with contender pools.
        n_threads: Number of worker threads for parallel execution.
        model_name: Gemini model name for resolution.

    Returns:
        Dictionary mapping standardized master names to sets of validated vendor variants.
    """
    master_dict = {}
    sorted_items = sorted(llm_required_items, key=lambda x: str(x.get("Vendor Name", "")).lower())
    total_vendors = len(sorted_items)

    logger.info(
        f"🚀 Pass 2: Processing {total_vendors} complex vendors across {n_threads} parallel threads (Model: {model_name})..."
    )

    # One Vertex AI client under the runtime's identity, shared by the workers.
    client = create_genai_client(BOOTSTRAP)
    processed_count = 0
    failed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        future_to_record = {
            executor.submit(process_vendor_task, record, client, model_name): record
            for record in sorted_items
        }

        for future in concurrent.futures.as_completed(future_to_record):
            processed_count += 1
            record = future_to_record[future]
            vendor_target_name = record["Vendor Name"]

            try:
                success, _, result_record = future.result()

                if success and result_record:
                    raw_master = result_record.standardized_vendor_name.strip()
                    master_name = re.sub(r"[\s,._-]+$", "", raw_master).strip()

                    allowed_variants = {v.strip().lower() for v in record.get("Contender Pool", [])}
                    allowed_variants.add(vendor_target_name.strip().lower())

                    raw_returned_variants = [
                        v.strip() for v in result_record.unique_variants if v.strip()
                    ]
                    raw_returned_variants.append(result_record.source_vendor.strip())

                    validated_variants = {
                        v for v in raw_returned_variants if v.lower() in allowed_variants
                    }
                    if not validated_variants:
                        validated_variants.add(vendor_target_name.strip())

                    if master_name not in master_dict:
                        master_dict[master_name] = set()
                    master_dict[master_name].update(validated_variants)
                else:
                    failed_count += 1
                    fallback_key = vendor_target_name.strip().title()
                    if fallback_key not in master_dict:
                        master_dict[fallback_key] = set()
                    master_dict[fallback_key].add(vendor_target_name.strip())
                    logger.warning(
                        f"⚠️ Fallback engaged for vendor: '{vendor_target_name}' ({processed_count}/{total_vendors})"
                    )

            except Exception as err:
                failed_count += 1
                fallback_key = vendor_target_name.strip().title()
                if fallback_key not in master_dict:
                    master_dict[fallback_key] = set()
                master_dict[fallback_key].add(vendor_target_name.strip())
                logger.error(
                    f"❌ [ERROR] Worker exception for vendor '{vendor_target_name}': {err}"
                )

            log_interval = (
                CONFIG.get("resolver_agent", {})
                .get("concurrency", {})
                .get("progress_log_interval", 25)
            )
            if processed_count % log_interval == 0 or processed_count == total_vendors:
                logger.info(
                    f"⚡ [LLM RESOLUTION] {processed_count}/{total_vendors} records processed ({failed_count} fallbacks)"
                )

    return master_dict


def resolve_final_vendor_matrix(contender_pools: list, **kwargs) -> Tuple[dict, int, int]:
    """Orchestrates vendor consolidation through multi-threaded parallel execution and returns category counts.

    Args:
        contender_pools: List of candidate records containing 'Vendor Name' and 'Contender Pool'.
        **kwargs: Optional keyword arguments for backward compatibility.

    Returns:
        Tuple of (consolidated_dictionary, standalone_count, llm_count).
    """
    try:
        start_time = time.time()
        corp_exts = load_config_set("corporate_extensions.json")

        # Step 1: Segregate standalones vs complex records
        standalone_items, llm_required_items = _segregate_contender_pools(contender_pools)
        standalone_count = len(standalone_items)
        llm_count = len(llm_required_items)

        master_dictionary = {}

        # Step 2: Map standalones (zero LLM overhead)
        if standalone_items:
            standalone_dict = _map_standalone_entities(standalone_items, corp_exts)
            for k, v in standalone_dict.items():
                master_dictionary.setdefault(k, set()).update(v)

        # Step 3: Multi-threaded LLM resolution for complex records
        if llm_required_items:
            default_threads = (
                CONFIG.get("resolver_agent", {})
                .get("concurrency", {})
                .get("default_max_threads", CONFIG.get("pipeline", {}).get("max_threads", 6))
            )
            n_threads = int(os.environ.get("MAX_THREADS", default_threads))
            # The live model from Parameter Manager, the same one the agent uses.
            model_name = get_runtime_config().model
            llm_resolved_dict = _execute_multithreaded_llm_resolution(
                llm_required_items, n_threads, model_name
            )
            for k, v in llm_resolved_dict.items():
                master_dictionary.setdefault(k, set()).update(v)

        # Step 4: Consolidate overlapping master entities
        consolidated_dict = consolidate_master_dictionary(master_dictionary, corp_exts)
        final_output = {
            key.strip(): sorted(list(variants_set))
            for key, variants_set in consolidated_dict.items()
        }

        end_time = time.time()
        elapsed_time = end_time - start_time
        logger.info(
            f"📊 [CHUNK SUMMARY] Completed in {elapsed_time:.2f}s | "
            f"Master Entities: {len(final_output)} | Standalone: {standalone_count} | LLM Resolved: {llm_count}"
        )

        return final_output, standalone_count, llm_count
    except Exception as err:
        logger.error(f"❌ [ERROR] Failed to resolve final vendor matrix: {err}")
        return {}, 0, 0
