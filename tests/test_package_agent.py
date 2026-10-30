from __future__ import annotations

import importlib.util
import re
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "deployment"
PACKAGE_MODULE_PATH = DEV_DIR / "deploy" / "package_agent.py"
# Check that nested shared modules reach the archive.
EXPECTED_ARCHIVE_MEMBERS = {
    "requirements.txt",
    "vendor_match_agent",
    "vendor_match_agent/__init__.py",
    "vendor_match_agent/agent.py",
    "gemini_shared",
    "gemini_shared/__init__.py",
    "gemini_shared/auth/__init__.py",
    "gemini_shared/auth/delegated.py",
    "gemini_shared/auth/workspace.py",
    "gemini_shared/config/__init__.py",
    "gemini_shared/config/bootstrap.py",
    "gemini_shared/config/runtime_config.py",
    "gemini_shared/config/tools.py",
    "gemini_shared/mcp/__init__.py",
    "gemini_shared/mcp/mcp_auth/__init__.py",
    "gemini_shared/mcp/mcp_auth/toolset.py",
    "gemini_shared/mcp/mcp_google_cloud/__init__.py",
    "gemini_shared/mcp/mcp_google_cloud/servers.py",
    "gemini_shared/secrets/__init__.py",
}


def _load_package_module():
    sys.path.insert(0, str(DEV_DIR))
    try:
        spec = importlib.util.spec_from_file_location("package_agent_for_test", PACKAGE_MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(DEV_DIR))


@pytest.mark.parametrize("agent", ["vendor_match_agent", "ticket_guidance_agent"])
def test_package_is_deterministic_and_has_expected_layout(tmp_path: Path, agent: str) -> None:
    module = _load_package_module()
    first = module.package_agent(agent, tmp_path / "first.tar.gz")
    second = module.package_agent(agent, tmp_path / "second.tar.gz")

    assert first.read_bytes() == second.read_bytes()

    with tarfile.open(first, mode="r:gz") as archive:
        members = {member.name for member in archive.getmembers()}

    expected = {name.replace("vendor_match_agent", agent) for name in EXPECTED_ARCHIVE_MEMBERS}
    assert expected.issubset(members)
    assert {name.split("/")[0] for name in members} == {"requirements.txt", agent, "gemini_shared"}


def test_packages_carry_their_resource_files(tmp_path):
    """YAML prompts and reference data ship inside the package, not beside it."""
    module = _load_package_module()
    expected = {
        "vendor_match_agent": {
            "vendor_match_agent/resources/config/pipeline_config.yaml",
            "vendor_match_agent/resources/config/prompts.yaml",
            "vendor_match_agent/resources/data/reference/stop_words.json",
        },
        "growth_analysis_workflow": {
            "growth_analysis_workflow/resources/prompts.yaml",
            "growth_analysis_workflow/resources/agents/sheet_reader_agent.yaml",
            "growth_analysis_workflow/resources/agents/weather_agent.yaml",
            "growth_analysis_workflow/stages.py",
        },
    }
    for agent, files in expected.items():
        path = module.package_agent(agent, tmp_path / f"{agent}.tar.gz")
        with tarfile.open(path, "r:gz") as archive:
            members = {member.name for member in archive.getmembers()}
        assert files <= members, files - members


def test_archives_carry_no_credentials(tmp_path):
    """Token and credential files must never ship inside a runtime archive."""
    module = _load_package_module()
    forbidden = re.compile(r"(token|credential|client_secret|oauth).*\.json$|\.env$", re.I)
    for agent in ("vendor_match_agent", "ticket_guidance_agent", "growth_analysis_workflow"):
        path = module.package_agent(agent, tmp_path / f"{agent}.tar.gz")
        with tarfile.open(path, "r:gz") as archive:
            leaked = [m.name for m in archive.getmembers() if forbidden.search(m.name)]
        assert not leaked, leaked
