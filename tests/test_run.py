"""The runner isolates agents from one another, keeps going, and runs the chosen modes."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

DEPLOYMENT = Path(__file__).resolve().parents[1] / "deployment"


@pytest.fixture
def run(monkeypatch):
    monkeypatch.syspath_prepend(str(DEPLOYMENT))
    module = importlib.import_module("run")
    monkeypatch.setattr(module, "read_main_config", lambda: None)
    monkeypatch.setattr(module, "load_environment", lambda *a: None)
    monkeypatch.setattr(
        module, "require_deploy_environment", lambda **kw: ("test-project", "us-central1", "gs://b")
    )
    monkeypatch.setenv("GEMINI_ENTERPRISE_APP_ID", "test-app")
    monkeypatch.setattr(module, "bootstrap", Mock())
    monkeypatch.setattr(module, "release_agent", Mock())
    monkeypatch.setattr(module, "deploy_no_code_agent", Mock())
    return module


def test_each_release_starts_from_the_same_environment(run, monkeypatch):
    """A default one release fills in must not leak into the next."""
    seen = []

    def release(name, skip_register=False):
        seen.append(os.environ.get("CONFIG_PARAMETER"))
        os.environ["CONFIG_PARAMETER"] = f"{name}-config"

    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.setattr(run, "release_agent", release)
    monkeypatch.setattr(sys, "argv", ["run.py", "deploy", "--skip-no-code"])
    run.main()
    assert seen == [None] * len(run.AGENTS)
    assert "CONFIG_PARAMETER" not in os.environ


def test_one_failure_does_not_stop_the_others(run, monkeypatch, capsys):
    calls = []

    def release(name, skip_register=False):
        calls.append(name)
        if name == "growth_analysis_workflow":
            raise SystemExit("create an OAuth client")

    monkeypatch.setattr(run, "release_agent", release)
    monkeypatch.setattr(sys, "argv", ["run.py", "deploy"])
    with pytest.raises(SystemExit) as raised:
        run.main()
    assert raised.value.code == 1
    assert calls == list(run.AGENTS)
    assert run.deploy_no_code_agent.call_count == len(run.no_code_agent_names())
    output = capsys.readouterr().out
    assert "deploy:growth_analysis_workflow: needs attention" in output
    assert "create an OAuth client" in output


def test_only_limits_the_run(run, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["run.py", "deploy", "--skip-platform", "--only", "kitchen_sequencer"]
    )
    run.main()
    run.release_agent.assert_not_called()
    run.bootstrap.assert_not_called()
    assert run.deploy_no_code_agent.call_args.args[0] == "kitchen_sequencer"


def test_unknown_names_are_rejected(run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "deploy", "--only", "recipe_card_agent"])
    with pytest.raises(SystemExit, match="Unknown agent"):
        run.main()


def test_seed_runs_its_steps_after_the_platform(run, monkeypatch):
    order = []
    run.bootstrap.side_effect = lambda: order.append("platform")
    seed = importlib.import_module("seed")
    monkeypatch.setattr(
        seed,
        "seed_steps",
        lambda project, secrets: {"secrets": lambda: order.append("secrets")},
    )
    monkeypatch.setattr(sys, "argv", ["run.py", "seed"])
    run.main()
    assert order == ["platform", "secrets"]
    run.release_agent.assert_not_called()


def test_test_mode_runs_one_check_per_selected_agent(run, monkeypatch, capsys):
    checks = importlib.import_module("verify.checks")
    ran = []
    fake = {name: (lambda name=name: ran.append(name) or f"{name} ok") for name in checks.CHECKS}
    monkeypatch.setattr(checks, "CHECKS", fake)
    monkeypatch.setattr(sys, "argv", ["run.py", "test", "--only", "vendor_match_agent"])
    run.main()
    assert ran == ["vendor_match_agent"]
    run.bootstrap.assert_not_called()
    assert "All steps passed." in capsys.readouterr().out


def test_a_skipped_check_is_not_a_failure(run, monkeypatch, capsys):
    checks = importlib.import_module("verify.checks")

    def skipped():
        raise checks.CheckSkipped("tests.growth_full_run is false")

    monkeypatch.setattr(checks, "CHECKS", {**checks.CHECKS, "growth_analysis_workflow": skipped})
    monkeypatch.setattr(sys, "argv", ["run.py", "test", "--only", "growth_analysis_workflow"])
    run.main()
    assert "skipped (tests.growth_full_run is false)" in capsys.readouterr().out


@pytest.mark.parametrize("environment", ["qa", "prod"])
def test_no_ticket_is_created_in_a_shared_environment(run, monkeypatch, environment):
    """Even with the setting left at its default, qa and prod never get a test ticket."""
    checks = importlib.import_module("verify.checks")
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.delenv("TEST_TICKET_GUIDANCE_CREATES_TICKETS", raising=False)
    conversation = Mock()
    monkeypatch.setattr(checks, "_conversation", conversation)
    with pytest.raises(checks.CheckSkipped, match="not run in qa or prod"):
        checks.ticket_guidance()
    conversation.assert_not_called()


class _DroppedStream:
    """A Growth run whose stream breaks while the runtime finishes the report."""

    def __init__(self, states):
        self._states = iter(states)

    def send(self, message):
        raise ConnectionError("stream aborted by the host")

    def state(self):
        return next(self._states)


def test_growth_check_survives_a_dropped_stream(run, monkeypatch):
    checks = importlib.import_module("verify.checks")
    monkeypatch.setenv("TEST_GROWTH_FULL_RUN", "true")
    monkeypatch.setattr(checks, "REPORT_POLL_SECONDS", 0)
    doc = "https://docs.google.com/document/d/abc123"
    states = [{}, {"insights_agent": "..."}, {"report_generation_agent": f"Report: {doc}/edit"}]
    monkeypatch.setattr(checks, "_conversation", lambda agent: _DroppedStream(states))
    assert checks.growth_analysis() == f"report written: {doc}"


def test_growth_check_fails_when_the_run_wrote_no_report(run, monkeypatch):
    checks = importlib.import_module("verify.checks")
    monkeypatch.setenv("TEST_GROWTH_FULL_RUN", "true")
    monkeypatch.setattr(checks, "REPORT_POLL_SECONDS", 0)
    monkeypatch.setattr(checks, "REPORT_WAIT_SECONDS", 0)
    monkeypatch.setattr(checks, "_conversation", lambda agent: _DroppedStream([{}] * 3))
    with pytest.raises(checks.CheckFailed, match="no report Doc was produced"):
        checks.growth_analysis()


def test_every_agent_has_an_end_to_end_check(run):
    checks = importlib.import_module("verify.checks")
    assert set(checks.CHECKS) == set(run.AGENTS) | set(run.no_code_agent_names())
