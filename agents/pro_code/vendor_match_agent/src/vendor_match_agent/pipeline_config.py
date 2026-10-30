"""
Configuration and Prompt Loader Utility Module.

Loads the pipeline's YAML configuration, the resolver's prompt strings and the
JSON reference data sets that ship inside this package under ``resources/``.
"""

import json
import logging
import os
from typing import Any, Dict, Set

import yaml

logger = logging.getLogger(__name__)

# Packaged resources: config/*.yaml and data/reference/*.json. Paths in the
# pipeline configuration are relative to this directory.
PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def load_yaml_config(file_path: str = "config/pipeline_config.yaml") -> Dict[str, Any]:
    """Loads a YAML configuration file safely using absolute pathing.

    Args:
        file_path: Relative or absolute path to the YAML configuration file.

    Returns:
        Dict containing parsed configuration values, or empty dict on failure.
    """
    try:
        if not os.path.isabs(file_path):
            file_path = os.path.join(PROJECT_ROOT, file_path)

        if not os.path.exists(file_path):
            logger.warning(f"⚠️ [WARNING] Config file not found at: {file_path}")
            return {}

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except yaml.YAMLError as yaml_err:
        logger.error(f"❌ [ERROR] YAML syntax error in '{file_path}': {yaml_err}")
        return {}
    except Exception as err:
        logger.error(f"❌ [ERROR] Unexpected failure loading config '{file_path}': {err}")
        return {}


def load_prompt(prompt_key: str, file_path: str = "config/prompts.yaml") -> str:
    """Loads a specific prompt string from the centralized prompts YAML file.

    Args:
        prompt_key: Key name corresponding to the prompt template.
        file_path: Relative or absolute path to the prompts YAML file.

    Returns:
        String containing prompt text, or empty string if key is not found.
    """
    try:
        if not os.path.isabs(file_path):
            file_path = os.path.join(PROJECT_ROOT, file_path)

        if not os.path.exists(file_path):
            logger.warning(f"⚠️ [WARNING] Prompts file not found at: {file_path}")
            return ""

        with open(file_path, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f) or {}

        prompt_val = prompts.get(prompt_key, "")
        if not prompt_val:
            logger.warning(f"⚠️ [WARNING] Prompt key '{prompt_key}' not found in '{file_path}'")
        return prompt_val
    except yaml.YAMLError as yaml_err:
        logger.error(f"❌ [ERROR] YAML syntax error reading prompts '{file_path}': {yaml_err}")
        return ""
    except Exception as err:
        logger.error(f"❌ [ERROR] Unexpected failure loading prompt '{prompt_key}': {err}")
        return ""


def load_config_set(file_name: str) -> Set[str]:
    """Loads a JSON configuration list into a normalized lowercase set.

    Checks 'data/reference/' first, falling back to 'config/' for backward compatibility.

    Args:
        file_name: Base filename (e.g. 'corporate_extensions.json').

    Returns:
        Set of normalized, stripped, lowercase strings.
    """
    try:
        ref_path = os.path.join(PROJECT_ROOT, "data", "reference", file_name)
        cfg_path = os.path.join(PROJECT_ROOT, "config", file_name)

        if os.path.exists(ref_path):
            file_path = ref_path
        elif os.path.exists(cfg_path):
            file_path = cfg_path
        else:
            logger.warning(
                f"⚠️ [WARNING] Reference data file not found in data/reference/ or config/: {file_name}"
            )
            return set()

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {str(x).lower().strip() for x in data if str(x).strip()}
            logger.warning(f"⚠️ [WARNING] Config file '{file_name}' did not contain a JSON list.")
            return set()
    except json.JSONDecodeError as json_err:
        logger.error(f"❌ [ERROR] JSON parse error in '{file_name}': {json_err}")
        return set()
    except Exception as err:
        logger.error(f"❌ [ERROR] Unexpected failure loading config set '{file_name}': {err}")
        return set()
