"""Vendor Match tools, each run with the signed-in user's Drive access."""

from gemini_shared import with_user_credentials

from ..config import GEMINI_ENTERPRISE_AUTHORIZATION_ID
from .orchestration_tools import (
    confirm_and_commit_master_updates,
    initialize_vendor_batch,
    lookup_master_dictionary_vendor,
    process_vendor_batch_chunk,
)

_as_user = with_user_credentials(GEMINI_ENTERPRISE_AUTHORIZATION_ID)

VENDOR_MATCH_TOOLS = [
    _as_user(initialize_vendor_batch),
    _as_user(process_vendor_batch_chunk),
    _as_user(confirm_and_commit_master_updates),
    _as_user(lookup_master_dictionary_vendor),
]

__all__ = ["VENDOR_MATCH_TOOLS"]
