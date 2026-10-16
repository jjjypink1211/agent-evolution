from __future__ import annotations

import json
from pathlib import Path

from agent_evolution import target_harness
from agent_evolution.snapshot import Snapshot

TASK_TEXT_FRAGMENTS = (
    "Read both records",
    "Retrieve the payload",
    "Complete this multi-step delivery",
    "It may have been renamed",
    "Install package",
    "Complete every component of this incident workflow",
)


def test_default_snapshot_matches_golden_fixture(
    default_snapshot_path: Path, harness_fixture: dict
) -> None:
    snapshot = Snapshot.load(default_snapshot_path)
    assert snapshot.system_prompt == harness_fixture["system_prompt"]
    assert dict(snapshot.tool_descriptions) == harness_fixture["tool_descriptions"]
    assert dict(snapshot.status_sections) == harness_fixture["status_sections"]


def test_default_snapshot_excludes_task_text(default_snapshot_path: Path) -> None:
    snapshot = Snapshot.load(default_snapshot_path)
    blob = "\n".join(
        [snapshot.system_prompt, *snapshot.status_sections.values(), *snapshot.tool_descriptions.values()]
    )
    for fragment in TASK_TEXT_FRAGMENTS:
        assert fragment not in blob


def test_default_snapshot_covers_every_status_feature(default_snapshot_path: Path) -> None:
    snapshot = Snapshot.load(default_snapshot_path)
    expected = {case.feature for case in target_harness.STATUS_CASES}
    assert set(snapshot.status_sections) == expected


def test_live_target_reproduces_the_golden_fixture(
    target_module_path: Path, harness_fixture: dict
) -> None:
    assert target_harness.extract(target_module_path) == harness_fixture


def test_snapshot_renders_byte_identical_to_live_target(
    target_module_path: Path, default_snapshot_path: Path
) -> None:
    snapshot = Snapshot.load(default_snapshot_path)
    module = target_harness.load_module(target_module_path)
    for case in target_harness.STATUS_CASES:
        live_section = target_harness.status_section(module, case)
        assert snapshot.render_status_section(case.feature, case.rendered) == live_section
    for suite in target_harness.SUITES:
        for tool in module.tools_for(suite, set(target_harness.FEATURES)):
            name = tool["function"]["name"]
            assert snapshot.tool_descriptions[name] == tool["function"]["description"]


def test_default_features_match_protocol_conditions(
    target_module_path: Path, default_snapshot_path: Path
) -> None:
    protocol_path = target_module_path.parent / "experiment_protocol.json"
    if not protocol_path.is_file():
        import pytest

        pytest.skip(f"protocol not found at {protocol_path}")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    union = sorted({feature for condition in protocol["conditions"].values() for feature in condition})
    assert list(Snapshot.load(default_snapshot_path).features) == union
