import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from google.adk.tools import ToolContext

from vendor_match_agent.pipeline_config import load_yaml_config
from vendor_match_agent.standardization_pipeline.llm_matcher import (
    consolidate_master_dictionary,
    load_config_set,
    resolve_final_vendor_matrix,
)
from vendor_match_agent.standardization_pipeline.phase_execution import execute_cleaning_pipeline
from vendor_match_agent.standardization_pipeline.search_contenders import gather_possible_contenders
from vendor_match_agent.tools.drive_tools import delete_file_from_drive
from vendor_match_agent.utils.master_dict_helpers import (
    commit_new_mappings_to_master,
    execute_fast_master_lookup,
    load_master_dictionary_cache,
    normalize_key,
)
from vendor_match_agent.utils.pipeline_helpers import (
    archive_processed_inputs,
    create_batch_job_manifest,
    create_review_staging_workbook,
    delete_staged_payload_from_drive,
    extract_attached_files_from_context,
    extract_clean_username,
    ingest_chat_uploads,
    ingest_drive_source_folder,
    load_staged_payload_from_drive,
    sanitize_str,
    save_staged_payload_to_drive,
)

CONFIG = load_yaml_config("config/pipeline_config.yaml")

logger = logging.getLogger(__name__)

# One runtime process serves every user, so entries are keyed per session and
# user, and a key is only ever honoured for the user it belongs to.
_STAGED_RESOLUTION_CACHE = {}


def _session_cache_key(tool_context: ToolContext) -> str:
    """Key of this session's staged batch: the session's short ID and the user's name."""
    length = CONFIG.get("orchestrator_agent", {}).get("batching", {}).get("session_id_length", 8)
    session_id = getattr(tool_context, "session_id", None) or getattr(
        getattr(tool_context, "session", None), "id", "session"
    )
    return f"{sanitize_str(session_id)[:length]}_{extract_clean_username(tool_context)}"


def _owned_cache_key(tool_context: ToolContext, session_key: Optional[str]) -> str:
    """The model may name a session key to resume; accept it only for the same user."""
    if session_key and session_key.endswith(f"_{extract_clean_username(tool_context)}"):
        return session_key
    return _session_cache_key(tool_context)


def _ingest_vendor_sources(
    uploaded_files: List[Tuple[str, bytes]],
    final_source_id: Optional[str],
    temp_dir: str,
) -> Tuple[Dict[str, str], List[Dict[str, str]], List[str], int]:
    """Ingests raw vendor names either from chat attachments or from Google Drive source folder."""
    files_to_archive = []
    grouped_uploads = {}

    if uploaded_files:
        logger.info(f"📎 [CHAT UPLOADS] Processing {len(uploaded_files)} attached file(s)...")
        grouped_uploads, raw_extracted_names = ingest_chat_uploads(uploaded_files, temp_dir)
        total_files = len(grouped_uploads)
    else:
        logger.info(f"🚀 [DRIVE BATCH] Scanning source folder: {final_source_id}")
        (
            files_to_archive,
            raw_extracted_names,
            total_files,
        ) = ingest_drive_source_folder(final_source_id, temp_dir)

    return grouped_uploads, files_to_archive, raw_extracted_names, total_files


async def initialize_vendor_batch(
    tool_context: ToolContext,
    chunk_size: Optional[int] = None,
    source_folder_id: Optional[str] = None,
    master_folder_id: Optional[str] = None,
) -> str:
    """Step 1: Ingests vendor input data, creates numbered batch chunks, and returns an execution manifest."""
    try:
        batch_cfg = CONFIG.get("orchestrator_agent", {}).get("batching", {})
        default_chunk_size = batch_cfg.get(
            "chunk_size", CONFIG.get("pipeline", {}).get("chunk_size", 1000)
        )
        effective_chunk_size = chunk_size or default_chunk_size
        final_source_id = source_folder_id or os.environ.get("DRIVE_SOURCE_FOLDER_ID")
        final_master_id = master_folder_id or os.environ.get("DRIVE_MASTER_DICT_FOLDER_ID")
        final_processed_id = os.environ.get("DRIVE_PROCESSED_FOLDER_ID")

        cache_key = _session_cache_key(tool_context)
        clean_user = extract_clean_username(tool_context)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_prefix = f"{clean_user}_{timestamp_str}"

        logger.info(f"📌 [SESSION INIT] Session key: {cache_key} | Prefix: {session_prefix}")

        # Check if an active, incomplete batch session already exists for this session key
        _, staged_data = _resolve_session_state(
            tool_context=tool_context,
            processed_folder_id=final_processed_id,
        )

        if staged_data and "manifest" in staged_data:
            manifest = staged_data["manifest"]
            chunks = manifest.get("chunks", {})
            pending_chunks = [int(k) for k, v in chunks.items() if v.get("status") != "completed"]
            if pending_chunks:
                next_chunk = min(pending_chunks)
                logger.info(
                    f"🔄 [RESUME GUARD] Active session '{cache_key}' found. Resuming at chunk {next_chunk}/{manifest['total_chunks']}."
                )
                return json.dumps(
                    {
                        "status": "batch_resumed",
                        "job_id": manifest.get("job_id"),
                        "session_key": staged_data.get("session_key", cache_key),
                        "total_records": manifest["total_records"],
                        "chunk_size": manifest["chunk_size"],
                        "total_chunks": manifest["total_chunks"],
                        "current_chunk": next_chunk,
                        "next_step_directive": f"IMMEDIATELY_CALL_TOOL: process_vendor_batch_chunk(chunk_number={next_chunk})",
                        "message": f"Active batch in progress. Resuming processing at chunk {next_chunk} of {manifest['total_chunks']}.",
                    },
                    indent=2,
                )

        uploaded_files = await extract_attached_files_from_context(tool_context)

        with tempfile.TemporaryDirectory() as temp_dir:
            (
                grouped_uploads,
                files_to_archive,
                raw_extracted_names,
                total_files,
            ) = _ingest_vendor_sources(uploaded_files, final_source_id, temp_dir)

            if not raw_extracted_names:
                logger.error("❌ No valid vendor name columns found across input sheets.")
                return json.dumps(
                    {
                        "status": "error",
                        "message": "No valid vendor name columns found across input sheets.",
                    },
                    indent=2,
                )

            logger.info(
                f"📊 Ingested {len(raw_extracted_names)} records across {total_files} file(s)."
            )

            job_id, manifest = create_batch_job_manifest(
                raw_extracted_names, chunk_size=effective_chunk_size
            )

            staged_payload = {
                "session_key": cache_key,
                "manifest": manifest,
                "files_to_archive": files_to_archive,
                "grouped_uploads": grouped_uploads,
                "final_source_id": final_source_id,
                "final_master_id": final_master_id,
                "session_prefix": session_prefix,
            }

            _STAGED_RESOLUTION_CACHE[cache_key] = staged_payload
            if final_processed_id:
                save_staged_payload_to_drive(cache_key, staged_payload, final_processed_id)

            return json.dumps(
                {
                    "status": "batch_initialized",
                    "job_id": job_id,
                    "session_key": cache_key,
                    "total_records": manifest["total_records"],
                    "chunk_size": manifest["chunk_size"],
                    "total_chunks": manifest["total_chunks"],
                    "current_chunk": 1,
                    "next_step_directive": "IMMEDIATELY_CALL_TOOL: process_vendor_batch_chunk(chunk_number=1)",
                    "message": f"Successfully initialized {manifest['total_records']} vendor records into {manifest['total_chunks']} chunk(s). Please process chunk 1 next.",
                },
                indent=2,
            )

    except Exception as err:
        logger.error(f"❌ Initialization failed: {err}")
        return json.dumps(
            {"status": "error", "message": f"Initialization failed: {str(err)}"}, indent=2
        )


def _resolve_session_state(
    tool_context: ToolContext,
    session_key: Optional[str] = None,
    processed_folder_id: Optional[str] = None,
) -> Tuple[str, Optional[dict]]:
    """Resolves session identity and retrieves the latest staged batch state from Drive."""
    try:
        cache_key = _owned_cache_key(tool_context, session_key)

        # 1. ALWAYS load the latest state from Google Drive first to sync across cloud workers
        staged_data = None
        if processed_folder_id:
            logger.info(f"🔍 [CLOUD SYNC] Loading latest manifest for '{cache_key}' from Drive...")
            staged_data = load_staged_payload_from_drive(cache_key, processed_folder_id)

        # 2. Fall back to local memory cache if Drive read returns None
        if not staged_data:
            staged_data = _STAGED_RESOLUTION_CACHE.get(cache_key)

        return cache_key, staged_data
    except Exception as err:
        logger.error(f"❌ [ERROR] Failed to resolve session state: {err}")
        return "", None


def _execute_chunk_resolution(
    chunk_vendor_names: List[str],
    lookup_cache: dict,
    manifest: dict,
    chunk_number: int,
) -> Tuple[int, int, int]:
    """Resolves a chunk of raw vendor names via cache lookup, adaptive sub-chunking, and LLM matching.

    Args:
        chunk_vendor_names: List of raw vendor strings for the active chunk.
        lookup_cache: Master dictionary lookup cache mapping normalized keys to master names.
        manifest: Batch execution manifest dictionary storing chunks and accumulated matches.
        chunk_number: Current chunk sequence number (1-indexed).

    Returns:
        Tuple of (master_matches_count, standalone_count, llm_count).
    """
    try:
        # Pass 1: Fast Master Dictionary Lookup
        chunk_known, unmatched_raw = execute_fast_master_lookup(chunk_vendor_names, lookup_cache)
        master_matches_count = len(chunk_vendor_names) - len(unmatched_raw)

        # ADAPTIVE SUB-CHUNKING: Configurable thresholds to prevent stream timeouts on heavy workloads
        batch_cfg = CONFIG.get("orchestrator_agent", {}).get("batching", {})
        subchunk_thresh = batch_cfg.get("adaptive_subchunk_threshold", 400)
        subchunk_slice = batch_cfg.get("adaptive_subchunk_slice_size", 350)

        if len(unmatched_raw) > subchunk_thresh:
            logger.info(
                f"⚡ [ADAPTIVE SUB-CHUNKING] High unmatched load ({len(unmatched_raw)} items > {subchunk_thresh}). "
                f"Dynamically slicing overflow items (slice size: {subchunk_slice}) into next sub-chunk..."
            )
            current_unmatched = unmatched_raw[:subchunk_slice]
            overflow_unmatched = unmatched_raw[subchunk_slice:]

            # --- TRUNCATE CURRENT CHUNK TO PREVENT DUPLICATE COUNTING ---
            overflow_set = set(overflow_unmatched)
            manifest["chunks"][str(chunk_number)]["vendor_names"] = [
                v for v in chunk_vendor_names if v not in overflow_set
            ]

            # Shift all subsequent chunk keys right by +1
            curr_total = manifest["total_chunks"]
            for c_idx in range(curr_total, chunk_number, -1):
                manifest["chunks"][str(c_idx + 1)] = manifest["chunks"][str(c_idx)]

            # Insert overflow sub-chunk at next index
            manifest["chunks"][str(chunk_number + 1)] = {
                "status": "pending",
                "vendor_names": overflow_unmatched,
            }
            manifest["total_chunks"] += 1

            # Resolve current sub-chunk
            df_cleaned = execute_cleaning_pipeline(current_unmatched)
            contender_pools = gather_possible_contenders(df_cleaned.to_dict(orient="records"))
            chunk_proposed, standalone_count, llm_count = resolve_final_vendor_matrix(
                contender_pools
            )
        else:
            # Standard resolution path for normal workloads
            if unmatched_raw:
                df_cleaned = execute_cleaning_pipeline(unmatched_raw)
                contender_pools = gather_possible_contenders(df_cleaned.to_dict(orient="records"))
                chunk_proposed, standalone_count, llm_count = resolve_final_vendor_matrix(
                    contender_pools
                )
            else:
                chunk_proposed, standalone_count, llm_count = {}, 0, 0

        # Accumulate resolved mappings into manifest (handling sets recovered as lists from JSON)
        for master, vars_list in chunk_known.items():
            if master not in manifest["accumulated_known_resolved"]:
                manifest["accumulated_known_resolved"][master] = set()
            elif isinstance(manifest["accumulated_known_resolved"][master], (list, tuple)):
                manifest["accumulated_known_resolved"][master] = set(
                    manifest["accumulated_known_resolved"][master]
                )
            manifest["accumulated_known_resolved"][master].update(vars_list)

        for master, vars_list in chunk_proposed.items():
            if master not in manifest["accumulated_proposed"]:
                manifest["accumulated_proposed"][master] = set()
            elif isinstance(manifest["accumulated_proposed"][master], (list, tuple)):
                manifest["accumulated_proposed"][master] = set(
                    manifest["accumulated_proposed"][master]
                )
            manifest["accumulated_proposed"][master].update(vars_list)

        return master_matches_count, standalone_count, llm_count
    except Exception as err:
        logger.error(f"❌ [ERROR] Chunk resolution failed: {err}")
        raise


def _stage_chunk_review(
    manifest: dict,
    staged_data: dict,
    processed_folder_id: Optional[str],
    temp_dir: str,
) -> Tuple[List[dict], Optional[str]]:
    """Performs global consolidation on final batch completion and stages the review workbook in Drive.

    Args:
        manifest: Batch execution manifest dictionary.
        staged_data: Session staging dictionary storing mappings and file metadata.
        processed_folder_id: Google Drive folder ID for saving the review workbook.
        temp_dir: Temporary directory path on disk.

    Returns:
        Tuple of (proposed_preview_list, review_file_url_or_None).
    """
    try:
        logger.info(
            "🧹 [GLOBAL CONSOLIDATION] Final chunk complete. Deduplicating proposed entities..."
        )
        corp_exts = load_config_set("corporate_extensions.json")
        final_proposed_mappings = consolidate_master_dictionary(
            manifest["accumulated_proposed"], corp_exts
        )
        staged_data["proposed_new_mappings"] = final_proposed_mappings
        staged_data["known_resolved_map"] = {
            k: sorted(list(v)) for k, v in manifest["accumulated_known_resolved"].items()
        }

        review_file_url = None
        if processed_folder_id:
            review_file_id, review_file_url = create_review_staging_workbook(
                proposed_mappings=final_proposed_mappings,
                known_resolved_map=staged_data["known_resolved_map"],
                processed_folder_id=processed_folder_id,
                temp_dir=temp_dir,
                session_prefix=staged_data["session_prefix"],
            )
            staged_data["review_file_id"] = review_file_id
            staged_data["review_file_url"] = review_file_url

        preview_limit = (
            CONFIG.get("orchestrator_agent", {})
            .get("preview_limits", {})
            .get("proposed_mappings_preview", 10)
        )
        proposed_preview = [
            {"master_entity": k, "resolved_variants": v}
            for k, v in list(final_proposed_mappings.items())[:preview_limit]
        ]
        return proposed_preview, review_file_url
    except Exception as err:
        logger.error(f"❌ [ERROR] Staging review preparation failed: {err}")
        return [], None


async def process_vendor_batch_chunk(
    tool_context: ToolContext,
    chunk_number: int,
    session_key: Optional[str] = None,
) -> str:
    """Step 2: Processes a single batch chunk with adaptive sub-chunking for heavy LLM workloads."""
    try:
        final_processed_id = os.environ.get("DRIVE_PROCESSED_FOLDER_ID")
        cache_key, staged_data = _resolve_session_state(
            tool_context=tool_context,
            session_key=session_key,
            processed_folder_id=final_processed_id,
        )

        if not staged_data or "manifest" not in staged_data:
            return json.dumps(
                {
                    "status": "error",
                    "message": "No active batch job manifest found. Please run initialize_vendor_batch first.",
                },
                indent=2,
            )

        manifest = staged_data["manifest"]
        chunk_str = str(chunk_number)

        if chunk_str not in manifest["chunks"]:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Invalid chunk_number {chunk_number}. Total chunks: {manifest['total_chunks']}",
                },
                indent=2,
            )

        chunk_info = manifest["chunks"][chunk_str]
        chunk_vendor_names = chunk_info["vendor_names"]

        logger.info(
            f"🔄 [PROCESSING CHUNK {chunk_number}/{manifest['total_chunks']}] ({len(chunk_vendor_names)} records)..."
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            lookup_cache, _, _ = load_master_dictionary_cache(
                staged_data["final_master_id"], temp_dir
            )

            master_matches_count, standalone_count, llm_count = _execute_chunk_resolution(
                chunk_vendor_names=chunk_vendor_names,
                lookup_cache=lookup_cache,
                manifest=manifest,
                chunk_number=chunk_number,
            )

            chunk_info["status"] = "completed"
            has_more = chunk_number < manifest["total_chunks"]
            next_chunk = chunk_number + 1 if has_more else None

            proposed_preview = []
            review_file_url = None

            if not has_more:
                proposed_preview, review_file_url = _stage_chunk_review(
                    manifest=manifest,
                    staged_data=staged_data,
                    processed_folder_id=final_processed_id,
                    temp_dir=temp_dir,
                )

            _STAGED_RESOLUTION_CACHE[cache_key] = staged_data
            if final_processed_id:
                save_staged_payload_to_drive(cache_key, staged_data, final_processed_id)

            pause_interval = (
                CONFIG.get("orchestrator_agent", {})
                .get("batching", {})
                .get("chunks_per_turn_pause", 3)
            )
            is_pause_point = (chunk_number % pause_interval == 0) and has_more
            batch_total = master_matches_count + standalone_count + llm_count

            summary_line = (
                f"* ✅ **Batch {chunk_number}/{manifest['total_chunks']} Complete** | "
                f"Batch Records: {batch_total:,} | "
                f"Master Dict Matches: {master_matches_count:,} | "
                f"Standalone: {standalone_count:,} | "
                f"LLM Resolved: {llm_count:,}\n\n"
            )

            logger.info(summary_line)

            return json.dumps(
                {
                    "status": "turn_paused_for_user"
                    if is_pause_point
                    else ("completed" if not has_more else "chunk_completed"),
                    "chunk_completed": chunk_number,
                    "total_chunks": manifest["total_chunks"],
                    "has_more": has_more,
                    "next_chunk": next_chunk,
                    "pause_required": is_pause_point,
                    "batch_metrics": {
                        "batch_total": batch_total,
                        "batch_master_dict_matches": master_matches_count,
                        "batch_standalone": standalone_count,
                        "batch_llm_resolved": llm_count,
                    },
                    "batch_summary_line": summary_line,
                    "final_proposed_preview": proposed_preview if not has_more else [],
                    "review_file_url": review_file_url if not has_more else None,
                    "next_step_directive": (
                        f"IMMEDIATELY_CALL_TOOL: process_vendor_batch_chunk(chunk_number={next_chunk})"
                        if (has_more and not is_pause_point)
                        else "PAUSE_TURN_FOR_USER_CONTINUE"
                        if is_pause_point
                        else "BATCH_COMPLETE"
                    ),
                    "message": (
                        f"{summary_line}\n\n"
                        f"⏸️ STREAM PAUSE POINT REACHED (Completed Chunks {max(1, chunk_number - 2)}–{chunk_number} of {manifest['total_chunks']}). "
                        f"Type 'Continue' or 'Next' to run the next batch group."
                        if is_pause_point
                        else summary_line
                    ),
                },
                indent=2,
            )

    except Exception as err:
        logger.error(f"❌ Fatal chunk error: {err}")
        return json.dumps(
            {"status": "error", "message": f"Chunk processing failed: {str(err)}"}, indent=2
        )


def _fetch_staged_commit_data(
    tool_context: ToolContext,
    processed_folder_id: Optional[str] = None,
) -> Tuple[str, Optional[dict]]:
    """Fetches staged resolution payload from in-memory cache or Google Drive.

    Args:
        tool_context: ADK ToolContext instance containing user/session metadata.
        processed_folder_id: Google Drive folder ID for recovering staged JSON.

    Returns:
        Tuple of (cache_key, staged_data_dict_or_None).
    """
    try:
        cache_key = _session_cache_key(tool_context)

        staged_data = _STAGED_RESOLUTION_CACHE.get(cache_key)
        if not staged_data and processed_folder_id:
            staged_data = load_staged_payload_from_drive(cache_key, processed_folder_id)

        return cache_key, staged_data
    except Exception as err:
        logger.error(f"❌ [ERROR] Failed to fetch staged commit data: {err}")
        return "", None


def _execute_master_commit_and_cleanup(
    staged_data: dict,
    cache_key: str,
    is_approved: bool,
    processed_folder_id: Optional[str],
    temp_dir: str,
) -> dict:
    """Executes master dictionary commit, input archiving, and staging file cleanup.

    Args:
        staged_data: Staged resolution dictionary payload.
        cache_key: Session cache key.
        is_approved: Boolean indicating whether the user approved the commit.
        processed_folder_id: Google Drive folder ID for processed files.
        temp_dir: Temporary directory path on disk.

    Returns:
        Result dictionary to be serialized as tool response JSON.
    """
    try:
        actual_cache_key = staged_data.get("session_key") or cache_key

        # 1. Clean up temporary review staging sheet if one was generated
        review_file_id = staged_data.get("review_file_id")
        if review_file_id:
            try:
                delete_file_from_drive(review_file_id)
                logger.info(f"🗑️ [CLEANUP] Deleted temporary review workbook: '{review_file_id}'")
            except Exception as clean_err:
                logger.warning(f"Failed to clean up review staging workbook: {clean_err}")

        # 2. Branch: Commit on approval, or reject
        if is_approved:
            combined_mappings = {}

            # Include Tab 2 entries (Auto-matched variants)
            for master, vars_list in staged_data.get("known_resolved_map", {}).items():
                if master not in combined_mappings:
                    combined_mappings[master] = set()
                combined_mappings[master].update(vars_list)

            # Include Tab 1 entries (Newly proposed LLM / Standalone additions)
            for master, vars_list in staged_data.get("proposed_new_mappings", {}).items():
                if master not in combined_mappings:
                    combined_mappings[master] = set()
                combined_mappings[master].update(vars_list)

            final_commit_payload = {k: sorted(list(v)) for k, v in combined_mappings.items()}

            published_master_id = commit_new_mappings_to_master(
                final_commit_payload,
                staged_data["final_master_id"],
                temp_dir,
            )

            archive_processed_inputs(
                processed_folder_id,
                staged_data.get("grouped_uploads", {}),
                staged_data.get("files_to_archive", []),
                staged_data["final_source_id"],
                temp_dir,
                staged_data["session_prefix"],
            )

            _STAGED_RESOLUTION_CACHE.pop(cache_key, None)
            _STAGED_RESOLUTION_CACHE.pop(actual_cache_key, None)
            if processed_folder_id:
                delete_staged_payload_from_drive(actual_cache_key, processed_folder_id)

            workbook_url = f"https://drive.google.com/open?id={published_master_id}"
            return {
                "status": "success",
                "user_decision": "approved",
                "message": "Successfully committed approved vendor mappings to Master Dictionary.",
                "workbook_url": workbook_url,
            }
        else:
            archive_processed_inputs(
                processed_folder_id,
                staged_data.get("grouped_uploads", {}),
                staged_data.get("files_to_archive", []),
                staged_data["final_source_id"],
                temp_dir,
                staged_data["session_prefix"],
            )

            _STAGED_RESOLUTION_CACHE.pop(cache_key, None)
            _STAGED_RESOLUTION_CACHE.pop(actual_cache_key, None)
            if processed_folder_id:
                delete_staged_payload_from_drive(actual_cache_key, processed_folder_id)

            return {
                "status": "rejected",
                "user_decision": "rejected",
                "message": "User rejected proposed mappings. Master Dictionary was NOT updated. Input file moved to Processed archive.",
            }
    except Exception as err:
        logger.error(f"❌ [ERROR] Failed to execute master commit and cleanup: {err}")
        return {"status": "error", "message": f"Processing failed: {str(err)}"}


async def confirm_and_commit_master_updates(
    tool_context: ToolContext,
    user_decision: str = "approved",
    output_folder_id: Optional[str] = None,
    processed_folder_id: Optional[str] = None,
) -> str:
    """Stage 3 & 4: Commits approved vendor mappings and cleans up temporary review/staging files."""
    try:
        final_processed_id = processed_folder_id or os.environ.get("DRIVE_PROCESSED_FOLDER_ID")
        cache_key, staged_data = _fetch_staged_commit_data(
            tool_context=tool_context,
            processed_folder_id=final_processed_id,
        )

        if not staged_data:
            return json.dumps(
                {
                    "status": "error",
                    "message": "No staged resolution payload found. Please run the vendor analysis step first.",
                },
                indent=2,
            )

        approval_keywords = CONFIG.get("orchestrator_agent", {}).get(
            "approval_keywords", ["approved", "approve", "yes", "confirm", "commit"]
        )
        is_approved = any(kw in user_decision.strip().lower() for kw in approval_keywords)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = _execute_master_commit_and_cleanup(
                staged_data=staged_data,
                cache_key=cache_key,
                is_approved=is_approved,
                processed_folder_id=final_processed_id,
                temp_dir=temp_dir,
            )
            return json.dumps(result, indent=2)

    except Exception as err:
        logger.error(f"❌ Failed to confirm and commit updates: {err}")
        return json.dumps(
            {"status": "error", "message": f"Processing failed: {str(err)}"},
            indent=2,
        )


async def lookup_master_dictionary_vendor(
    query: str, master_folder_id: Optional[str] = None
) -> str:
    """Searches the Master Dictionary for vendor variants or master entities."""
    try:
        final_master_id = master_folder_id or os.environ.get("DRIVE_MASTER_DICT_FOLDER_ID")
        query_norm = normalize_key(query)

        if not query_norm:
            return json.dumps(
                {"status": "error", "message": "Please provide a non-empty vendor name to search."}
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            _, df_existing, _ = load_master_dictionary_cache(final_master_id, temp_dir)

            if df_existing.empty:
                return json.dumps(
                    {"status": "not_found", "message": "Master Dictionary is currently empty."}
                )

            col_std = (
                "Standardized Vendor Name"
                if "Standardized Vendor Name" in df_existing.columns
                else df_existing.columns[0]
            )
            col_var = (
                "Raw Vendor Variant"
                if "Raw Vendor Variant" in df_existing.columns
                else df_existing.columns[1]
            )

            df_existing["std_norm"] = df_existing[col_std].apply(normalize_key)
            df_existing["var_norm"] = df_existing[col_var].apply(normalize_key)

            master_matches = df_existing[df_existing["std_norm"] == query_norm]
            if not master_matches.empty:
                master_name = str(master_matches.iloc[0][col_std]).strip()
                all_variants = master_matches[col_var].tolist()
                return json.dumps(
                    {
                        "status": "found",
                        "search_type": "master_to_variants",
                        "queried_term": query,
                        "standardized_vendor_name": master_name,
                        "all_associated_variants": sorted(list(set(all_variants))),
                    },
                    indent=2,
                )

            var_matches = df_existing[df_existing["var_norm"] == query_norm]
            if not var_matches.empty:
                master_name = str(var_matches.iloc[0][col_std]).strip()
                all_variants = df_existing[df_existing["std_norm"] == normalize_key(master_name)][
                    col_var
                ].tolist()
                return json.dumps(
                    {
                        "status": "found",
                        "search_type": "variant_to_master",
                        "queried_term": query,
                        "standardized_vendor_name": master_name,
                        "all_associated_variants": sorted(list(set(all_variants))),
                    },
                    indent=2,
                )

            partial_matches = df_existing[
                df_existing["var_norm"].str.contains(query_norm, regex=False, na=False)
                | df_existing["std_norm"].str.contains(query_norm, regex=False, na=False)
            ]

            if not partial_matches.empty:
                results = []
                grouped = partial_matches.groupby(col_std)[col_var].apply(list).to_dict()

                total_found = len(grouped)
                lookup_limit = (
                    CONFIG.get("orchestrator_agent", {})
                    .get("preview_limits", {})
                    .get("master_lookup_preview", 25)
                )
                for m_name, vars_list in list(grouped.items())[:lookup_limit]:
                    results.append(
                        {
                            "standardized_vendor_name": m_name,
                            "matching_variants": sorted(list(set(vars_list))),
                        }
                    )

                return json.dumps(
                    {
                        "status": "partial_matches_found",
                        "queried_term": query,
                        "total_matches_found": total_found,
                        "returned_count": len(results),
                        "results": results,
                    },
                    indent=2,
                )

            return json.dumps(
                {
                    "status": "not_found",
                    "message": f"No vendor variant or master entity matching '{query}' was found in the Master Dictionary.",
                },
                indent=2,
            )

    except Exception as e:
        return json.dumps({"status": "error", "message": f"Lookup failed: {str(e)}"})
