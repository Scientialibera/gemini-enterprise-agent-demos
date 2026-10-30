"""Seed an environment with what the agents need before and after they deploy.

Each step is idempotent and controlled by config.yaml:

    secrets     every secret the agents read exists; first values from env vars
    bigquery    synthetic source tables (seed.bigquery.sample_data) and the
                Kitchen Sequencer tables (seed.bigquery.kitchen_compliance)
    drive       sample performance sheet and vendor workbooks (seed.drive.enabled)
    atlassian   knowledge base space and pages; Jira project check
                (seed.atlassian.enabled)

Sample data is synthetic and for testing; with real data, leave those steps off.
"""

from __future__ import annotations

from collections.abc import Callable

from config.environment import env_bool

SEED_STEPS = ("secrets", "bigquery", "drive", "atlassian")


def _bigquery(project_id: str) -> None:
    from .kitchen_compliance import prepare_kitchen_compliance
    from .sample_data import load_sample_data, sample_data_enabled

    # Synthetic source tables first, so the Kitchen tables can be built from them.
    if sample_data_enabled():
        loaded = load_sample_data(project_id)
        print(f"SAMPLE_TABLES_LOADED={len(loaded)}")
    seeded = prepare_kitchen_compliance(project_id)
    if seeded is not None:
        print(f"KITCHEN_COMPLIANCE_TABLES={seeded.dataset}: {','.join(seeded.tables)}")


def seed_steps(
    project_id: str, secrets: dict[str, dict[str, str]]
) -> dict[str, Callable[[], object]]:
    """The enabled steps, in order, ready to run."""
    from .atlassian import seed_atlassian
    from .drive import seed_drive
    from .secrets import seed_secrets
    from .storage import seed_performance_workbook

    steps: dict[str, Callable[[], object]] = {
        "secrets": lambda: seed_secrets(project_id, secrets),
        "bigquery": lambda: _bigquery(project_id),
        "storage": lambda: seed_performance_workbook(project_id),
    }
    if env_bool("SEED_DRIVE", False):
        steps["drive"] = seed_drive
    if env_bool("SEED_ATLASSIAN", False):
        steps["atlassian"] = lambda: seed_atlassian(project_id)
    return steps
