"""Extract harness texts from the system-hint target loop, for golden checks.

The target loop now loads its harness (system prompt, ``<agent_status>``
section templates and tool descriptions) from a declarative snapshot
directory. This module drives the live target to read those texts back out, so
the default snapshot and the frozen golden fixture can be proven equal to the
behaviour the refactored loop actually produces.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_evolution.snapshot import RENDERED_PLACEHOLDER

SUITES = ("timestamps", "tool_counter", "todo_list", "detailed_errors", "system_state", "combined")

FEATURES = (
    "detailed_errors",
    "system_state",
    "timestamp_guidance",
    "timestamps",
    "todo_list",
    "tool_counter",
)

ENVELOPE_PREFIX = "<agent_status>\n"
ENVELOPE_SUFFIX = "\n</agent_status>"

TARGET_ENV_VAR = "AI_AGENT_BOOK_TARGET"
DEFAULT_TARGET_DIR = Path(r"C:\agent\ai-agent-book\chapter2\system-hint")
TARGET_MODULE_NAME = "run_experiment_2_8.py"


def resolve_target_dir() -> Path:
    """Locate the system-hint target, honouring the ``AI_AGENT_BOOK_TARGET`` override."""
    return Path(os.environ.get(TARGET_ENV_VAR, DEFAULT_TARGET_DIR))


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
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def system_prompt(module: types.ModuleType) -> str:
    """Return the target loop's effective (snapshot-loaded) system prompt."""
    return module.harness().system_prompt


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
        "system_prompt": system_prompt(module),
        "tool_descriptions": tool_descriptions(module),
        "status_sections": dict(sorted(status_sections.items())),
    }


__all__ = [
    "DEFAULT_TARGET_DIR",
    "FEATURES",
    "STATUS_CASES",
    "SUITES",
    "TARGET_ENV_VAR",
    "TARGET_MODULE_NAME",
    "StatusCase",
    "extract",
    "load_module",
    "resolve_target_dir",
    "status_section",
    "status_template",
    "system_prompt",
    "tool_descriptions",
]
