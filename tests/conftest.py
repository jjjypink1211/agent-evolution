from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_evolution.target_harness import TARGET_MODULE_NAME, resolve_target_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPO_ROOT / "snapshots" / "system-hint"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "system_hint_harness.json"


@pytest.fixture(scope="session")
def default_snapshot_path() -> Path:
    return SNAPSHOT_ROOT


@pytest.fixture(scope="session")
def harness_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def target_module_path() -> Path:
    module_path = resolve_target_dir() / TARGET_MODULE_NAME
    if not module_path.is_file():
        pytest.skip(f"system-hint target not found at {module_path}")
    return module_path
