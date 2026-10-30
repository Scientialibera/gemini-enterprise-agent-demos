"""Build the Kitchen Sequencer's curated BigQuery tables once, from the shared SQL.

Kitchen Sequencer reads four pre-aggregated tables rather than Looker dashboards,
defined in
infrastructure/sql/kitchen_compliance/. Terraform schedules the same statements
to refresh daily; this builds them immediately with the caller's ADC, so a new
environment can be tested before the first scheduled run. No IAM is changed.

The caller needs BigQuery read access to the source dataset and permission to
create tables in the target project.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from config.environment import configured_value, env_bool
from google.api_core.exceptions import NotFound
from paths import ROOT

SEED_ENV = "DEV_SEED_KITCHEN_COMPLIANCE"
SOURCE_PROJECT_ENV = "KITCHEN_COMPLIANCE_SOURCE_PROJECT"
DATASET_ENV = "KITCHEN_COMPLIANCE_DATASET"
LOCATION_ENV = "KITCHEN_COMPLIANCE_LOCATION"
BIGQUERY_API_SERVICE = "bigquery.googleapis.com"

DEFAULT_DATASET = "kitchen_compliance"
# The source tables are in the US multi-region; a query cannot join across locations.
DEFAULT_LOCATION = "US"
SQL_DIR = ROOT / "infrastructure" / "sql" / "kitchen_compliance"
PLACEHOLDER = re.compile(r"\$\{([A-Z_]+)\}")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


@dataclass(frozen=True, slots=True)
class KitchenComplianceResult:
    dataset: str
    tables: tuple[str, ...]


def seeding_enabled() -> bool:
    return env_bool(SEED_ENV, False)


def render(sql: str, values: dict[str, str]) -> str:
    """Fill ${NAME} placeholders, refusing to run a statement with one left over."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise SystemExit(f"Kitchen compliance SQL uses ${{{name}}}, which has no value.")
        return values[name]

    return PLACEHOLDER.sub(substitute, sql)


def statements() -> tuple[tuple[str, str], ...]:
    """The SQL files in run order: 01 builds the kitchen dimension the others join."""
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"No SQL files found in {SQL_DIR}.")
    return tuple((path.stem, path.read_text(encoding="utf-8")) for path in files)


def prepare_kitchen_compliance(project_id: str) -> KitchenComplianceResult | None:
    """Create the dataset if missing and run each statement once, in order."""
    if not seeding_enabled():
        return None
    source = configured_value(SOURCE_PROJECT_ENV)
    if not source and env_bool("DEV_SEED_SAMPLE_DATA", False):
        # The sample ops_analytics tables are loaded into this project.
        source = project_id
    if not source:
        raise SystemExit(
            f"{SEED_ENV}=true needs {SOURCE_PROJECT_ENV}, the project holding ops_analytics."
        )
    dataset = os.getenv(DATASET_ENV, "").strip() or DEFAULT_DATASET
    if not IDENTIFIER.fullmatch(dataset):
        raise SystemExit(f"{DATASET_ENV} must be a valid BigQuery dataset ID.")
    location = os.getenv(LOCATION_ENV, "").strip() or DEFAULT_LOCATION

    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    reference = f"{project_id}.{dataset}"
    try:
        client.get_dataset(reference)
    except NotFound:
        created = bigquery.Dataset(reference)
        created.location = location
        created.description = "Curated kitchen compliance tables read by Kitchen Sequencer."
        created.labels = {"managed_by": "gemini-agent-repo", "agent": "kitchen-sequencer"}
        client.create_dataset(created)
        print(f"KITCHEN_COMPLIANCE_DATASET_CREATED={reference}")

    values = {"SOURCE_PROJECT": source, "TARGET_PROJECT": project_id, "TARGET_DATASET": dataset}
    built = []
    for name, sql in statements():
        client.query(render(sql, values), location=location).result()
        built.append(name)
        print(f"KITCHEN_COMPLIANCE_TABLE_BUILT={name}")
    return KitchenComplianceResult(dataset=reference, tables=tuple(built))
