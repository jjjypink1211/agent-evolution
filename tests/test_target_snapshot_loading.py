"""Loading contract and override behaviour for the refactored system-hint loop.

After ticket #3 the target reads its harness from a bundled snapshot directory.
These tests prove the bundled default is the reviewed canonical snapshot, that
the loop loads it by default, and that an explicit path or environment variable
can override it. The byte-for-byte golden equivalence against the frozen fixture
is asserted separately in ``test_system_hint_harness.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_evolution import target_harness
from agent_evolution.snapshot import Snapshot


def bundled_harness_dir(target_module_path: Path) -> Path:
    return target_module_path.parent / "harness_snapshot"


def with_system_prompt(snapshot: Snapshot, system_prompt: str) -> Snapshot:
    return Snapshot(
        features=snapshot.features,
        system_prompt=system_prompt,
        status_sections=snapshot.status_sections,
        tool_descriptions=snapshot.tool_descriptions,
    )


def test_bundled_default_equals_canonical_snapshot(
    target_module_path: Path, default_snapshot_path: Path
) -> None:
    bundled = bundled_harness_dir(target_module_path)
    if not bundled.is_dir():
        pytest.skip(f"target does not bundle a harness snapshot at {bundled}")
    assert Snapshot.load(bundled) == Snapshot.load(default_snapshot_path)


def test_target_loads_bundled_snapshot_by_default(
    target_module_path: Path, default_snapshot_path: Path
) -> None:
    module = target_harness.load_module(target_module_path)
    active = module.harness()
    canonical = Snapshot.load(default_snapshot_path)
    assert active.system_prompt == canonical.system_prompt
    assert dict(active.status_sections) == dict(canonical.status_sections)
    assert dict(active.tool_descriptions) == dict(canonical.tool_descriptions)


def test_explicit_snapshot_path_overrides_the_harness(
    target_module_path: Path, default_snapshot_path: Path, tmp_path: Path
) -> None:
    override = tmp_path / "explicit"
    with_system_prompt(Snapshot.load(default_snapshot_path), "EXPLICIT SYSTEM PROMPT").save(override)

    module = target_harness.load_module(target_module_path)
    module.set_harness(override)
    assert module.harness().system_prompt == "EXPLICIT SYSTEM PROMPT"


def test_environment_variable_selects_the_harness(
    target_module_path: Path, default_snapshot_path: Path, tmp_path: Path, monkeypatch
) -> None:
    override = tmp_path / "from-env"
    with_system_prompt(Snapshot.load(default_snapshot_path), "ENV SYSTEM PROMPT").save(override)

    module = target_harness.load_module(target_module_path)
    monkeypatch.setenv(module.HARNESS_ENV_VAR, str(override))
    assert module.harness().system_prompt == "ENV SYSTEM PROMPT"
