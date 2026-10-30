"""Read Secret Manager payloads with the runtime's own identity.

Secrets are never baked into a runtime's environment: an environment variable
on an Agent Engine is readable by anyone who can view the resource. An agent
names the secret it needs in an environment variable and reads the value here,
under its own Agent Identity, which holds ``secretAccessor`` on that secret
alone. Locally the same call uses Application Default Credentials, or the
value itself when ``<NAME>_VALUE`` is set for an offline run.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from ..config.bootstrap import get_bootstrap_settings

LOGGER = logging.getLogger(__name__)
LOCAL_VALUE_SUFFIX = "_VALUE"
DEFAULT_CACHE_SECONDS = 300
LATEST = "latest"

_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _version_name(secret: str, project_id: str) -> str:
    if secret.startswith("projects/"):
        return secret if "/versions/" in secret else f"{secret}/versions/{LATEST}"
    return f"projects/{project_id}/secrets/{secret}/versions/{LATEST}"


def read_secret(env_name: str, *, cache_seconds: int = DEFAULT_CACHE_SECONDS) -> str:
    """Return the payload of the secret named by ``env_name``.

    ``env_name`` holds a secret ID in the runtime's project or a full resource
    name. ``<env_name>_VALUE`` short-circuits the lookup for local runs only;
    it is never forwarded to a deployed runtime.
    """
    local = os.getenv(f"{env_name}{LOCAL_VALUE_SUFFIX}", "").strip()
    if local:
        return local
    secret = os.getenv(env_name, "").strip()
    if not secret:
        raise RuntimeError(f"{env_name} must name a Secret Manager secret.")
    name = _version_name(secret, get_bootstrap_settings().project_id)

    now = time.monotonic()
    with _lock:
        cached = _cache.get(name)
        if cached and cached[0] > now:
            return cached[1]

    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    value = client.access_secret_version(name=name).payload.data.decode("utf-8").strip()
    with _lock:
        _cache[name] = (now + cache_seconds, value)
    return value


def optional_secret(env_name: str) -> str | None:
    """Like ``read_secret``, but None when the secret is unset or unreadable.

    For tools that degrade without a key, such as a news feed that is skipped
    rather than failing the whole report. The failure is logged, never the value.
    """
    if not os.getenv(env_name, "").strip() and not os.getenv(f"{env_name}{LOCAL_VALUE_SUFFIX}"):
        return None
    try:
        return read_secret(env_name)
    except Exception as exc:
        LOGGER.warning("Secret named by %s could not be read: %s", env_name, type(exc).__name__)
        return None


def clear_secret_cache() -> None:
    """Forget cached payloads, so a rotated secret is read on the next call."""
    with _lock:
        _cache.clear()
