"""Loads the workflow's prompts and per-stage settings from the packaged resources.

``resources/prompts.yaml`` holds each stage's description and instruction plus the
tool-level prompt templates; ``resources/agents/<stage>.yaml`` holds that stage's
settings (sheet layout, metrics, API endpoints, report styling). Both are the dev
team's files with every client-specific value taken out. Those come from the
environment: GROWTH_SPREADSHEET_ID, GROWTH_REPORT_FOLDER_ID, and
GROWTH_SETTINGS_OVERRIDE, a JSON object keyed by stage that is merged over these
files (a sheet's own column headers, the brand to search Google Places with).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import yaml

logger = logging.getLogger(__name__)

RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "resources")
AGENTS_CONFIG_DIR = os.path.join(RESOURCES_DIR, "agents")
DEFAULT_PROMPTS_PATH = os.path.join(RESOURCES_DIR, "prompts.yaml")

SPREADSHEET_ENV = "GROWTH_SPREADSHEET_ID"
REPORT_FOLDER_ENV = "GROWTH_REPORT_FOLDER_ID"
OVERRIDE_ENV = "GROWTH_SETTINGS_OVERRIDE"


def load_config(yaml_path: str) -> dict[str, Any]:
    """Reads and parses a YAML file."""
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"Configuration file not found at: {yaml_path}")
    with open(yaml_path, encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override into base: mappings merge, anything else replaces."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _override(agent_name: str) -> dict[str, Any]:
    raw = os.getenv(OVERRIDE_ENV, "").strip()
    if not raw:
        return {}
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{OVERRIDE_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{OVERRIDE_ENV} must be a JSON object keyed by stage name.")
    stage = document.get(agent_name) or {}
    if not isinstance(stage, dict):
        raise ValueError(f"{OVERRIDE_ENV}[{agent_name!r}] must be an object.")
    return stage


def _with_environment(agent_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Merge the environment's override, then fill the IDs the packaged files leave blank."""
    _merge(config, _override(agent_name))
    if agent_name == "sheet_reader_agent":
        config["spreadsheet_id"] = os.getenv(SPREADSHEET_ENV) or config.get("spreadsheet_id", "")
    elif agent_name == "report_generation_agent":
        storage = config.setdefault("storage", {})
        storage["target_folder_id"] = os.getenv(REPORT_FOLDER_ENV) or storage.get(
            "target_folder_id", ""
        )
    return config


def load_agent_config(agent_name: str | None = None) -> dict[str, Any]:
    """One stage's settings from resources/agents/, or all of them keyed by stage."""
    if agent_name:
        path = os.path.join(AGENTS_CONFIG_DIR, f"{agent_name}.yaml")
        if not os.path.exists(path):
            logger.warning(f"Agent config file not found: {path}")
            return {}
        return _with_environment(agent_name, load_config(path))
    combined: dict[str, Any] = {}
    for fname in sorted(os.listdir(AGENTS_CONFIG_DIR)):
        if fname.endswith((".yaml", ".yml")):
            stem = os.path.splitext(fname)[0]
            combined[stem] = load_agent_config(stem)
    return combined


get_agent_config = load_agent_config


def load_threshold_config() -> dict[str, Any]:
    """Weather anomaly thresholds, from resources/agents/weather_agent.yaml."""
    return load_agent_config("weather_agent").get("thresholds", {})


def load_prompt_config(yaml_path: str = DEFAULT_PROMPTS_PATH) -> dict[str, Any]:
    """Each stage's description and instruction, keyed by stage name."""
    return load_config(yaml_path).get("agents", {})


def load_tool_prompt(
    prompt_key: str, default: str = "", yaml_path: str = DEFAULT_PROMPTS_PATH
) -> str:
    """A tool-level prompt template from the ``tool_prompts`` section of prompts.yaml."""
    try:
        return load_config(yaml_path).get("tool_prompts", {}).get(prompt_key, default)
    except Exception as e:
        logger.warning(f"Failed loading tool prompt '{prompt_key}' ({e}). Using default.")
        return default


def get_default_model() -> str:
    """The model the tools' own Gemini calls use: the live runtime configuration's.

    The dev build read it from global_settings.yaml; here it follows the same
    runtime parameter as the stages, so one change moves the whole workflow.
    """
    from gemini_shared import get_runtime_config

    return get_runtime_config().model


def get_l6w_window_days() -> int:
    """The Last 6 Weeks (L6W) lookback window in days (default 42)."""
    try:
        return int(load_agent_config("global_settings").get("l6w_window_days", 42))
    except (ValueError, TypeError):
        return 42
