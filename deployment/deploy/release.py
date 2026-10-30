"""Package, deploy or update, then register a development agent."""

from __future__ import annotations

import argparse
import os

from config.bootstrap import ensure_dev_prerequisites
from config.settings import load_environment, require_deploy_environment, unresolved_declared_env
from paths import ROOT
from registry import get_agent_spec

from deploy.package_agent import package_agent
from deploy.register.access_groups import prepare_access_group
from deploy.register.group_config import group_config
from deploy.register.register_agent import APP_ENGINE_ID_ENV, register_agent
from deploy.state import find_resource_name, runtime_override

ARTIFACTS_DIR = ROOT / "artifacts"


def release_agent(agent_name: str, *, skip_register: bool = False) -> str:
    """Release one registry entry and return its runtime resource name."""
    spec = get_agent_spec(agent_name)
    project_id, location, staging_bucket = require_deploy_environment(spec=spec)
    app_id = os.getenv(APP_ENGINE_ID_ENV, "").strip()
    if not skip_register:
        group_config(project_id, app_id, spec.package_name)
    for name in unresolved_declared_env(spec):
        print(f"WARNING={agent_name}: {name} is not set; the runtime will not receive it.")

    existing_resource = runtime_override(project_id, location)

    print("STEP=preflight")
    ensure_dev_prerequisites(project_id, location, staging_bucket, spec)
    if not skip_register:
        prepare_access_group(project_id, app_id, spec.package_name)

    # Preflight may create an explicitly requested new sandbox project. Resolve
    # its numeric state scope only after that project exists.
    existing_resource = existing_resource or find_resource_name(agent_name, project_id, location)

    print("STEP=package")
    archive = package_agent(agent_name, ARTIFACTS_DIR / f"{spec.package_name}.tar.gz")
    print(f"AGENT_ARCHIVE={archive}")

    already_deployed = existing_resource is not None
    print("STEP=update" if already_deployed else "STEP=deploy")
    if already_deployed:
        from deploy.update_dev import update_agent

        resource_name = update_agent(agent_name, project_id, location, staging_bucket, spec)
    else:
        from deploy.deploy_dev import deploy_agent

        resource_name = deploy_agent(agent_name, project_id, location, staging_bucket, spec)
    print(f"REASONING_ENGINE={resource_name}")

    if skip_register:
        print("STEP=register skipped")
        return resource_name

    if not app_id:
        print(
            f"STEP=register skipped: {APP_ENGINE_ID_ENV} is not set. The agent is deployed but "
            "will not appear in a Gemini Enterprise app until it is registered."
        )
        return resource_name

    print("STEP=register")
    register_agent(agent_name, app_id, project_id, spec, resource_name)
    return resource_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package, deploy and register one agent in a dev sandbox.",
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Stop after deployment instead of publishing into a Gemini Enterprise app.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    release_agent(args.agent, skip_register=args.skip_register)


if __name__ == "__main__":
    main()
