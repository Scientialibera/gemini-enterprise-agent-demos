"""Shared authentication and runtime configuration. Import MCP and secrets separately."""

from .auth import (
    GeminiEnterpriseDelegatedAuthProvider,
    GeminiEnterpriseDelegatedAuthProviderScheme,
    MissingUserAuthorization,
    current_user_credentials,
    delegated_auth_config,
    read_delegated_token,
    read_session_token,
    user_credentials,
    with_user_credentials,
)
from .config import (
    BootstrapSettings,
    RuntimeConfig,
    apply_runtime_model,
    get_bootstrap_settings,
    get_runtime_config,
    get_runtime_config_status,
    runtime_instruction,
    stage_instruction,
)

__all__ = [
    "BootstrapSettings",
    "GeminiEnterpriseDelegatedAuthProvider",
    "GeminiEnterpriseDelegatedAuthProviderScheme",
    "MissingUserAuthorization",
    "RuntimeConfig",
    "apply_runtime_model",
    "current_user_credentials",
    "delegated_auth_config",
    "get_bootstrap_settings",
    "get_runtime_config",
    "get_runtime_config_status",
    "read_delegated_token",
    "read_session_token",
    "runtime_instruction",
    "stage_instruction",
    "user_credentials",
    "with_user_credentials",
]
