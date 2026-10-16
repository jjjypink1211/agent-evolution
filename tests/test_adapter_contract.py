"""Both adapters satisfy the same seam, and the upper layer needs only it."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_evolution.adapter import Adapter, CaseRef, EpisodeResult
from agent_evolution.snapshot import Snapshot
from agent_evolution.system_hint_adapter import SystemHintAdapter
from agent_evolution.target_harness import TARGET_MODULE_NAME, resolve_target_dir

from fake_adapter import FakeAdapter


def test_fake_adapter_satisfies_the_adapter_protocol() -> None:
    assert isinstance(FakeAdapter(), Adapter)


def test_system_hint_adapter_satisfies_the_adapter_protocol(tmp_path: Path) -> None:
    module_path = resolve_target_dir() / TARGET_MODULE_NAME
    if not module_path.is_file():
        pytest.skip(f"system-hint target not found at {module_path}")
    assert isinstance(SystemHintAdapter(client=object(), run_root=tmp_path), Adapter)


def test_fake_adapter_lists_distinct_suites() -> None:
    adapter = FakeAdapter(
        cases=(CaseRef("combined", "all-01"), CaseRef("todo_list", "todo-01"), CaseRef("combined", "all-02"))
    )
    assert adapter.suites() == ("combined", "todo_list")


def test_system_hint_adapter_lists_every_protocol_suite(tmp_path: Path) -> None:
    module_path = resolve_target_dir() / TARGET_MODULE_NAME
    if not module_path.is_file():
        pytest.skip(f"system-hint target not found at {module_path}")
    adapter = SystemHintAdapter(client=object(), run_root=tmp_path)
    assert "combined" in adapter.suites()
    assert len(adapter.suites()) == len(set(adapter.suites()))


def test_upper_layer_uses_only_episode_result() -> None:
    """A consumer written against the seam alone works with either adapter."""

    def objective_passes(adapter: Adapter, snapshot: Snapshot, cases: list[CaseRef]) -> int:
        return sum(adapter.run(snapshot, case).objective_pass for case in cases)

    def scripted(snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        passing = case.case_id == "all-01"
        return EpisodeResult(
            objective_pass=passing,
            component_scores={"gate": passing},
            llm_turns=2,
            tokens=10,
            evidence_path=Path("episode.json"),
        )

    adapter = FakeAdapter(responder=scripted)
    snapshot = Snapshot(system_prompt="p")
    cases = [CaseRef("combined", "all-01"), CaseRef("combined", "all-02")]

    assert objective_passes(adapter, snapshot, cases) == 1
    assert [case.case_id for _, case in adapter.calls] == ["all-01", "all-02"]
