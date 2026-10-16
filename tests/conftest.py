from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPO_ROOT / "snapshots" / "system-hint"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "system_hint_harness.json"

DEFAULT_TARGET = Path(r"C:\agent\ai-agent-book\chapter2\system-hint")
TARGET_MODULE_NAME = "run_experiment_2_8.py"

TARGET_ENV_VAR = "AI_AGENT_BOOK_TARGET"


@pytest.fixture(scope="session")
def default_snapshot_path() -> Path:
    return SNAPSHOT_ROOT


@pytest.fixture(scope="session")
def harness_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def target_module_path() -> Path:
    target = Path(os.environ.get(TARGET_ENV_VAR, DEFAULT_TARGET))
    module_path = target / TARGET_MODULE_NAME
    if not module_path.is_file():
        pytest.skip(f"system-hint target not found at {module_path}")
    return module_path
