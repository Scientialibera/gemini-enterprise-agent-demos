"""Bootstrap values this agent resolves once at import.

Everything runs as the agent's own Agent Identity: BigQuery reads with
``bigquery.dataViewer`` and ``jobUser``, and the Gmail app password from its own
Secret Manager secret. No user authorization is needed.
"""

from __future__ import annotations

import os

from gemini_shared import get_bootstrap_settings

BOOTSTRAP = get_bootstrap_settings()
PROJECT_ID = BOOTSTRAP.project_id

# project.dataset of the product and legacy recipe tables.
PRODUCT_DATASET = os.getenv("RECIPE_PRODUCT_DATASET", f"{PROJECT_ID}.recipe_products").strip()
LEGACY_DATASET = os.getenv("RECIPE_LEGACY_DATASET", f"{PROJECT_ID}.recipe_legacy").strip()
ALLOWED_DATASETS = (PRODUCT_DATASET, LEGACY_DATASET)


def today_iso() -> str:
    """Today in US Eastern time, which the menu cycles are scheduled in."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
