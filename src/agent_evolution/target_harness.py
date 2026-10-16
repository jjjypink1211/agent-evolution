"""Extract harness texts from the system-hint target loop, for golden checks.

The target loop keeps its harness hardcoded until the prefactor lands. This
module reads those texts back out of the live target so the default snapshot
can be proven byte-identical to them.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUITES = ("timestamps", "tool_counter", "todo_list", "detailed_errors", "system_state", "combined")

FEATURES = (
    "detailed_errors",
    "system_state",
    "timestamp_guidance",
    "timestamps",
    "todo_list",
    "tool_counter",
)

SYSTEM_PROMPT_PREFIX = "You are an audited local-sandbox agent"

ENVELOPE_PREFIX = "<agent_status>\n"
ENVELOPE_SUFFIX = "\n</agent_status>"

RENDERED_PLACEHOLDER = "{rendered}"


@dataclass(frozen=True)
class StatusCase:
    feature: str
    features: frozenset[str]
    state: dict[str, Any]
    counters: dict[str, int]
    todos: dict[str, str]
    rendered: str


STATUS_CASES = (
    StatusCase(
        feature="timestamp_guidance",
        features=frozenset({"timestamp_guidance"}),
        state={},
        counters={},
        todos={},
        rendered="",
    ),
    StatusCase(
        feature="tool_counter",
        features=frozenset({"tool_counter"}),
        state={},
        counters={"probe_resource": 2, "read_record": 1},
        todos={},
        rendered="probe_resource=2, read_record=1",
    ),
    StatusCase(
        feature="todo_list",
        features=frozenset({"todo_list"}),
        state={},
        counters={},
        todos={"inventory.txt": "pending", "audit.txt": "completed"},
        rendered="inventory.txt: pending; audit.txt: completed",
    ),
    StatusCase(
        feature="system_state",
        features=frozenset({"system_state"}),
        state={
            "system": {
                "os": "Linux",
                "shell": "bash",
                "python": "3.11.9",
                "cwd": "workspace/alpha",
                "manager": "apt",
            }
        },
        counters={},
        todos={},
        rendered="os=Linux, shell=bash, python=3.11.9, cwd=workspace/alpha, manager=apt",
    ),
)


def load_module(path: Path) -> types.ModuleType:
    """Import the target loop, stubbing its OpenAI dependency."""
    if "openai" not in sys.modules:
        stub = types.ModuleType("openai")
        stub.OpenAI = type("OpenAI", (), {})
        sys.modules["openai"] = stub
    spec = importlib.util.spec_from_file_location(f"target_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load target module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def system_prompt(module_path: Path) -> str:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    candidates = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(SYSTEM_PROMPT_PREFIX)
    ]
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one system prompt literal, found {len(candidates)}")
    return candidates[0]


def tool_descriptions(module: types.ModuleType) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for suite in SUITES:
        for tool in module.tools_for(suite, set(FEATURES)):
            descriptions[tool["function"]["name"]] = tool["function"]["description"]
    return dict(sorted(descriptions.items()))


def status_section(module: types.ModuleType, case: StatusCase) -> str:
    message = module.status_message(
        set(case.features), case.state, dict(case.counters), dict(case.todos)
    )
    if message is None:
        raise ValueError(f"target produced no status message for {case.feature}")
    if not message.startswith(ENVELOPE_PREFIX) or not message.endswith(ENVELOPE_SUFFIX):
        raise ValueError(f"unexpected status envelope: {message!r}")
    return message[len(ENVELOPE_PREFIX) : len(message) - len(ENVELOPE_SUFFIX)]


def status_template(section: str, rendered: str) -> str:
    if not rendered:
        return section
    if section.count(rendered) != 1:
        raise ValueError(f"rendered text {rendered!r} is not present exactly once")
    return section.replace(rendered, RENDERED_PLACEHOLDER)


def extract(module_path: Path) -> dict[str, Any]:
    module = load_module(module_path)
    status_sections = {
        case.feature: status_template(status_section(module, case), case.rendered)
        for case in STATUS_CASES
    }
    return {
        "system_prompt": system_prompt(module_path),
        "tool_descriptions": tool_descriptions(module),
        "status_sections": dict(sorted(status_sections.items())),
    }


__all__ = [
    "FEATURES",
    "STATUS_CASES",
    "SUITES",
    "StatusCase",
    "extract",
    "load_module",
    "system_prompt",
    "tool_descriptions",
    "status_section",
    "status_template",
]
