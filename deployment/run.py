"""Check, seed, deploy and test every agent from deployment/config.yaml, end to end.

    check    what only a person or the console can provide (app, org policy,
             connectors, OAuth clients, secrets); reports, changes nothing
    seed     secrets, BigQuery sample and Kitchen tables, Drive sample files,
             the Atlassian knowledge base (each as enabled in config.yaml)
    deploy   platform (APIs, bucket, baseline IAM), each code agent (package,
             deploy or update, IAM, registration), each no-code agent (a draft
             to publish, unless its published copy already matches)
    test     one end-to-end check per agent against what was deployed
    all      check, seed, deploy, test (the default)

Every step is idempotent, so a run that stops is finished by running it again.
One agent failing does not stop the others; the summary lists what needs
attention, which on a first run is usually console work the check step named.
"""

from __future__ import annotations

import argparse
import os
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from config.bootstrap_dev import bootstrap
from config.main_config import config_path, read_main_config
from config.settings import CONFIRM_PROJECT_ENV, load_environment, require_deploy_environment
from deploy.no_code.deploy_no_code import PENDING_PUBLISH, deploy_no_code_agent
from deploy.no_code.spec import no_code_agent_names
from deploy.register.register_agent import APP_ENGINE_ID_ENV
from deploy.release import release_agent
from paths import ROOT
from registry import AGENTS

MODES = ("check", "seed", "deploy", "test", "all")


@contextmanager
def _isolated_environment() -> Iterator[None]:
    """Undo per-agent defaults so one release never inherits another's settings.

    A release fills CONFIG_PARAMETER and the authorization ID with that
    agent's defaults when they are unset. Left in place, the next agent would
    read the first agent's parameter and attach its authorization.
    """
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _run(label: str, step: Callable[[], object], failures: dict[str, str]) -> None:
    print(f"\n=== {label}")
    with _isolated_environment():
        try:
            result = step()
            if isinstance(result, str):
                print(result)
            print(f"RESULT={label}: ok")
        except SystemExit as exc:
            # Setup gaps (a missing OAuth client, connector or setting) exit with
            # instructions; record them and carry on with the other agents.
            failures[label] = str(exc.code if exc.code is not None else exc)
            print(f"RESULT={label}: needs attention")
        except Exception as exc:
            from verify.checks import CheckFailed, CheckSkipped

            if isinstance(exc, CheckSkipped):
                print(f"RESULT={label}: skipped ({exc})")
                return
            failures[label] = f"{type(exc).__name__}: {exc}"
            if not isinstance(exc, CheckFailed):
                traceback.print_exc()
            print(f"RESULT={label}: failed")


def _selected(only: list[str] | None, skip_code: bool, skip_no_code: bool) -> tuple[list, list]:
    code = [] if skip_code else list(AGENTS)
    no_code = [] if skip_no_code else list(no_code_agent_names())
    if only:
        unknown = set(only) - set(AGENTS) - set(no_code_agent_names())
        if unknown:
            raise SystemExit(f"Unknown agent(s): {', '.join(sorted(unknown))}")
        code = [name for name in code if name in only]
        no_code = [name for name in no_code if name in only]
    return code, no_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("mode", nargs="?", default="all", choices=MODES)
    parser.add_argument(
        "--only", nargs="+", metavar="NAME", help="Limit deploy and test to these agents."
    )
    parser.add_argument("--skip-platform", action="store_true", help="Skip APIs, bucket and IAM.")
    parser.add_argument("--skip-code", action="store_true", help="Skip ADK agents and workflows.")
    parser.add_argument("--skip-no-code", action="store_true", help="Skip no-code agents.")
    parser.add_argument(
        "--confirm-project",
        metavar="PROJECT_ID",
        help="Required for qa and prod: the project ID this run may change.",
    )
    parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Deploy code agents without registering them in the app.",
    )
    args = parser.parse_args()
    modes = ("check", "seed", "deploy", "test") if args.mode == "all" else (args.mode,)

    os.chdir(ROOT)
    config = read_main_config()
    if config is None:
        print(f"NOTE=no {config_path()}; reading settings from the environment only.")
    load_environment(".env.dev")
    if args.confirm_project:
        os.environ[CONFIRM_PROJECT_ENV] = args.confirm_project.strip()
    project_id, _, _ = require_deploy_environment(require_parameter=False)
    app_id = os.getenv(APP_ENGINE_ID_ENV, "").strip()
    code_agents, no_code_agents = _selected(args.only, args.skip_code, args.skip_no_code)

    failures: dict[str, str] = {}
    outcomes: list[str] = []

    if "check" in modes:
        from verify.preflight import run_preflight

        print("\n=== check")
        actions = [f for f in run_preflight(project_id) if not f.ok]
        outcomes.append(f"check: {len(actions)} action(s) listed above" if actions else "check: ok")

    if ("seed" in modes or "deploy" in modes) and not args.skip_platform:
        _run("platform", bootstrap, failures)
        if "platform" in failures:
            raise SystemExit(f"Platform setup failed; nothing else ran.\n{failures['platform']}")

    if "seed" in modes:
        from seed import seed_steps

        for step, run in seed_steps(project_id, config.secrets if config else {}).items():
            # Seeding exports values (such as a new sheet ID) for the deploy that
            # follows, so it runs outside the per-agent isolation.
            label = f"seed:{step}"
            print(f"\n=== {label}")
            try:
                run()
                print(f"RESULT={label}: ok")
            except SystemExit as exc:
                failures[label] = str(exc.code)
                print(f"RESULT={label}: needs attention")

    if "deploy" in modes:
        if no_code_agents and not app_id:
            raise SystemExit(f"No-code agents live only in an app: set {APP_ENGINE_ID_ENV}.")
        for name in code_agents:
            _run(
                f"deploy:{name}",
                lambda name=name: release_agent(name, skip_register=args.skip_register),
                failures,
            )
        for name in no_code_agents:
            _run(
                f"deploy:{name}",
                lambda name=name: deploy_no_code_agent(name, project_id, app_id),
                failures,
            )

    if "test" in modes:
        from verify.checks import CHECKS

        for name in [*no_code_agents, *code_agents]:
            _run(f"test:{name}", CHECKS[name], failures)

    print("\n=== summary")
    for line in outcomes:
        print(line)
    for label in sorted(failures):
        print(f"{label}: needs attention")
    if PENDING_PUBLISH:
        print(
            f"\nPublish in the agent designer (Google has no API for it): "
            f"{', '.join(PENDING_PUBLISH)}. Chat serves the previous version until then; "
            "see each ACTION_REQUIRED line above."
        )
    if failures:
        print("\nDetails:")
        for label, detail in failures.items():
            print(f"\n[{label}]\n{detail}")
        raise SystemExit(1)
    print(
        "All steps passed."
        if not any("action(s)" in o for o in outcomes)
        else "All steps that ran passed; see the check's actions above."
    )


if __name__ == "__main__":
    main()
