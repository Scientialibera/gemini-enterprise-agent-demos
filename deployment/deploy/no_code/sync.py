"""Keep a no-code agent in the repository and in the agent designer the same.

The repository is the source: deploy writes agent.yaml and prompt.md into the
app. People also edit agents in the designer, so this module reads the live
definition back, reports where it differs from the repository (drift), and
exports it into agent.yaml and prompt.md so the edit can be reviewed and
committed. Environment values in the live instruction (project, datasets) are
turned back into their ${NAME} placeholders, so the exported files still deploy
to any environment.

The designer keeps a draft and a published copy. Users chat with the published
one, so that is what is compared and exported by default.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import yaml

from deploy.no_code.spec import LOW_CODE_KEY, NoCodeSpec


@dataclass(frozen=True, slots=True)
class LiveAgent:
    description: str
    model: str
    google_search: bool
    starter_prompts: tuple[str, ...]
    instruction: str
    data_sources: tuple[str, ...]


def live_definition(agent: dict, *, draft: bool = False) -> LiveAgent | None:
    """The published (or draft) copy of an agent resource; None if it has none."""
    definition = agent.get(LOW_CODE_KEY) or {}
    nodes = definition.get("nodes" if draft else "deployedNodes") or []
    if not nodes:
        return None
    node = nodes[0].get("llmAgentNode", {})
    prompts = definition.get("draftStarterPrompts") if draft else agent.get("starterPrompts")
    return LiveAgent(
        description=str(agent.get("description") or node.get("description") or "").strip(),
        model=str(node.get("model", "")).strip(),
        google_search=not node.get("googleSearchDisabled", False),
        starter_prompts=tuple(str(p.get("text", "")) for p in prompts or ()),
        instruction=str(node.get("instruction", "")).strip(),
        data_sources=tuple(
            sorted(str(c.get("dataSource", "")) for c in node.get("dataConnectors") or ())
        ),
    )


def _normalized(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def differences(spec: NoCodeSpec, live: LiveAgent) -> list[str]:
    """Fields where the live agent differs from the repository."""
    found = []
    if live.description != spec.description:
        found.append("description")
    if live.model != spec.model:
        found.append("model")
    if live.google_search != spec.google_search:
        found.append("google_search")
    if live.starter_prompts != spec.starter_prompts:
        found.append("starter_prompts")
    if _normalized(live.instruction) != _normalized(spec.render_prompt()):
        found.append("instruction")
    # An optional connector the app lacks is skipped on deploy, so only a live
    # connector the repository does not declare, or a required one missing, counts.
    declared = {c.data_source for c in spec.connectors}
    required = {c.data_source for c in spec.connectors if not c.optional}
    live_sources = set(live.data_sources)
    if live_sources - declared or required - live_sources:
        found.append("connectors")
    return found


def unrender(spec: NoCodeSpec, instruction: str) -> str:
    """Put ${NAME} back where an environment value was filled in.

    Longest values first, so a dataset name that contains the project ID is
    restored as the dataset placeholder rather than half-replaced. Only whole
    names are matched ("." separates the parts of a table path), so a longer
    name that merely starts with a value is left alone. Either way the result
    renders back to the same instruction, which differences() confirms.
    """
    values = {
        name: os.environ[name].strip()
        for name in spec.prompt_variables
        if os.getenv(name, "").strip()
    }
    text = instruction
    for name, value in sorted(values.items(), key=lambda item: -len(item[1])):
        text = re.sub(rf"(?<![\w-]){re.escape(value)}(?![\w-])", f"${{{name}}}", text)
    return text


def _set_scalar(settings: str, key: str, value: object) -> str:
    line = yaml.safe_dump({key: value}, default_flow_style=False, width=1000, sort_keys=False)
    pattern = re.compile(rf"^{key}:.*$", re.MULTILINE)
    if not pattern.search(settings):
        raise SystemExit(f"agent.yaml has no single-line '{key}:' to update; edit it by hand.")
    return pattern.sub(lambda _: line.rstrip("\n"), settings, count=1)


def _set_list(settings: str, key: str, values: tuple[str, ...]) -> str:
    # Items indented two spaces, as the agent.yaml files are written.
    items = "".join(f"  {yaml.safe_dump([value], width=1000)}" for value in values)
    block = f"{key}:\n{items}"
    pattern = re.compile(rf"^{key}:\n(?:[ \t]+-.*\n)*", re.MULTILINE)
    if pattern.search(settings):
        return pattern.sub(lambda _: block, settings, count=1)
    return settings.rstrip("\n") + "\n" + block


def export_definition(spec: NoCodeSpec, live: LiveAgent) -> list[str]:
    """Write the live definition into the agent's files; return what changed."""
    changed = []
    prompt = unrender(spec, live.instruction).strip() + "\n"
    if _normalized(prompt) != _normalized(spec.prompt_path.read_text(encoding="utf-8")):
        spec.prompt_path.write_text(prompt, encoding="utf-8")
        changed.append("prompt.md")

    settings_path = spec.folder / "agent.yaml"
    settings = settings_path.read_text(encoding="utf-8")
    updated = settings
    if live.description != spec.description:
        updated = _set_scalar(updated, "description", live.description)
    if live.model != spec.model:
        updated = _set_scalar(updated, "model", live.model)
    if live.google_search != spec.google_search:
        updated = _set_scalar(updated, "google_search", live.google_search)
    if live.starter_prompts != spec.starter_prompts:
        updated = _set_list(updated, "starter_prompts", live.starter_prompts)
    if updated != settings:
        settings_path.write_text(updated, encoding="utf-8")
        changed.append("agent.yaml")
    return changed
