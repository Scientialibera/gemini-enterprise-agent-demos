"""No-code agent definitions: agents/no_code/<name>/agent.yaml and prompt.md.

A no-code agent has no runtime of its own. Gemini Enterprise runs it from an
instruction, a model and the connectors it may use, so that is all the
repository holds. Each folder is discovered automatically; adding one needs no
registry change.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from paths import ROOT

NO_CODE_DIR = ROOT / "agents" / "no_code"
SETTINGS_FILE = "agent.yaml"
# Key of the no-code definition in the Gemini Enterprise agent resource.
LOW_CODE_KEY = "lowCodeAgentDefinition"
PROMPT_FILE = "prompt.md"
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
SUPPORTED_SOURCES = frozenset({"custom_mcp", "google_mail", "confluence", "google_drive", "jira"})


@dataclass(frozen=True, slots=True)
class ConnectorRef:
    """A connector the agent uses, matched in the target app by type.

    ``mcp_server_url`` narrows a custom MCP connector to one server. When an
    app has several connectors of one type, ``collection_env`` names the
    variable holding the collection ID to use. An ``optional`` connector that
    the app lacks is left out with a warning, for capabilities the agent can
    do without, such as emailing a report it can also show in chat.
    """

    data_source: str
    mcp_server_url: str | None = None
    collection_env: str | None = None
    optional: bool = False


@dataclass(frozen=True, slots=True)
class NoCodeSpec:
    name: str
    display_name: str
    description: str
    model: str
    google_search: bool
    starter_prompts: tuple[str, ...]
    connectors: tuple[ConnectorRef, ...]
    prompt_variables: tuple[str, ...]
    folder: Path

    @property
    def prompt_path(self) -> Path:
        return self.folder / PROMPT_FILE

    def render_prompt(self) -> str:
        """The instruction with ${NAME} placeholders filled from the environment.

        Only names listed in prompt_variables are substituted, so a literal
        ``${...}`` elsewhere in a prompt is never touched by accident. A listed
        name that is unset fails deployment rather than publishing a prompt
        that tells the agent to use an empty project.
        """
        text = self.prompt_path.read_text(encoding="utf-8").strip()
        missing = [name for name in self.prompt_variables if not os.getenv(name, "").strip()]
        if missing:
            raise SystemExit(
                f"{self.name} prompt needs {', '.join(missing)}. "
                "Set them in deployment/config.yaml."
            )
        allowed = set(self.prompt_variables)

        def substitute(match: re.Match[str]) -> str:
            name = match.group(1)
            return os.environ[name].strip() if name in allowed else match.group(0)

        return PLACEHOLDER.sub(substitute, text)


def _connector(raw: object, agent: str) -> ConnectorRef:
    if not isinstance(raw, dict) or "data_source" not in raw:
        raise SystemExit(f"{agent}: each connector needs a data_source.")
    source = str(raw["data_source"])
    if source not in SUPPORTED_SOURCES:
        raise SystemExit(
            f"{agent}: connector type '{source}' is not supported. "
            f"Use one of: {', '.join(sorted(SUPPORTED_SOURCES))}."
        )
    return ConnectorRef(
        data_source=source,
        mcp_server_url=raw.get("mcp_server_url"),
        collection_env=raw.get("collection_env"),
        optional=bool(raw.get("optional", False)),
    )


def load_spec(name: str) -> NoCodeSpec:
    if not NAME_PATTERN.fullmatch(name):
        raise SystemExit(f"No-code agent names are lowercase folder names, not '{name}'.")
    folder = NO_CODE_DIR / name
    settings_path = folder / SETTINGS_FILE
    if not settings_path.is_file() or not (folder / PROMPT_FILE).is_file():
        allowed = ", ".join(no_code_agent_names()) or "none"
        raise SystemExit(f"Unknown no-code agent '{name}'. Choose one of: {allowed}")
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    for key in ("display_name", "description", "model"):
        if not str(raw.get(key, "")).strip():
            raise SystemExit(f"{settings_path} must set {key}.")
    return NoCodeSpec(
        name=name,
        display_name=str(raw["display_name"]).strip(),
        description=str(raw["description"]).strip(),
        model=str(raw["model"]).strip(),
        google_search=bool(raw.get("google_search", False)),
        starter_prompts=tuple(str(p) for p in raw.get("starter_prompts") or ()),
        connectors=tuple(_connector(c, name) for c in raw.get("connectors") or ()),
        prompt_variables=tuple(str(v) for v in raw.get("prompt_variables") or ()),
        folder=folder,
    )


def no_code_agent_names() -> tuple[str, ...]:
    if not NO_CODE_DIR.is_dir():
        return ()
    return tuple(
        sorted(
            path.name
            for path in NO_CODE_DIR.iterdir()
            if (path / SETTINGS_FILE).is_file() and NAME_PATTERN.fullmatch(path.name)
        )
    )
