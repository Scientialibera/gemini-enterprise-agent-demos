"""Bootstrap values this agent resolves once at import."""

from __future__ import annotations

import os

from gemini_shared import get_bootstrap_settings

# require_auth raises at import if the authorization ID is missing.
BOOTSTRAP = get_bootstrap_settings(require_auth=True)
GEMINI_ENTERPRISE_AUTHORIZATION_ID = str(BOOTSTRAP.gemini_enterprise_authorization_id)

# Shared Drive folders the pipeline reads from and writes to. Declared per
# environment in the registry's runtime_env; the tools read them at call time.
DRIVE_FOLDER_ENV = (
    "DRIVE_SOURCE_FOLDER_ID",
    "DRIVE_MASTER_DICT_FOLDER_ID",
    "DRIVE_PROCESSED_FOLDER_ID",
)

MISSING_DRIVE_FOLDERS = tuple(name for name in DRIVE_FOLDER_ENV if not os.getenv(name))
