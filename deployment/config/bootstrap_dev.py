from __future__ import annotations

import sys
from pathlib import Path

# Runnable directly as well as imported by run.py, so deployment/ has to be
# on sys.path either way: running this file puts only its own folder there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

from paths import ROOT
from seed.kitchen_compliance import BIGQUERY_API_SERVICE, seeding_enabled
from seed.sample_data import sample_data_enabled

from config.bootstrap import ensure_runtime_parameter, prepare_dev_platform
from config.environment import configured_value
from config.settings import load_environment, require_deploy_environment


def bootstrap() -> None:
    """Prepare the project: APIs, staging bucket and baseline IAM if asked.

    Seeding is a separate step (seed/); this only enables BigQuery when it will run.
    """
    project_id, location, staging_bucket = require_deploy_environment(require_parameter=False)

    wants_bigquery = seeding_enabled() or sample_data_enabled()
    additional_services = (BIGQUERY_API_SERVICE,) if wants_bigquery else ()
    prepare_dev_platform(
        project_id,
        location,
        staging_bucket,
        additional_services=additional_services,
    )

    # Per-agent parameters are resolved during deployment.
    if configured_value("CONFIG_PARAMETER"):
        ensure_runtime_parameter(project_id)
    # A sandbox with no platform stack needs the roles every Agent Identity
    # reads its own configuration with, or its agents deploy and then fail on
    # the first request. Off unless asked for, so a managed project is never
    # granted IAM behind Terraform's back.
    from deploy.iam.apply_agent_identity_iam import ensure_baseline_roles

    granted = ensure_baseline_roles(project_id, staging_bucket)
    if granted:
        print(f"AGENT_IDENTITY_BASELINE_GRANTED={len(granted)}")

    print("DEV_PREREQUISITES=ready")


def main() -> None:
    os.chdir(ROOT)
    load_environment(".env.dev")
    bootstrap()
    print("NEXT_STEP=Run deployment/run.py, or deployment/deploy/release.py --agent <name>.")


if __name__ == "__main__":
    main()
