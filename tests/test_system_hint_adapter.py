"""SystemHintAdapter reproduces the target's own gates, offline, from recordings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_evolution.adapter import CaseRef
from agent_evolution.snapshot import Snapshot
from agent_evolution.system_hint_adapter import SystemHintAdapter
from agent_evolution.target_harness import TARGET_MODULE_NAME, resolve_target_dir

from replay_client import ReplayClient, recorded_responses

CAMPAIGN = "exp2-8-kimi-k3-20260730-v1"
COMBINED_IDS = ("all-01", "all-02", "all-03", "all-04", "all-05")


def edited_snapshot(base: Snapshot, system_prompt: str) -> Snapshot:
    return Snapshot(
        features=base.features,
        system_prompt=system_prompt,
        status_sections=base.status_sections,
        tool_descriptions=base.tool_descriptions,
    )


def require_target() -> None:
    if not (resolve_target_dir() / TARGET_MODULE_NAME).is_file():
        pytest.skip("system-hint target not found")


def recorded_case_path(case_id: str, condition: str = "combined") -> Path:
    return (
        resolve_target_dir() / "runs" / CAMPAIGN / "cases" / f"combined__{case_id}__{condition}.json"
    )


def run_recorded(
    case_id: str, snapshot: Snapshot, run_root: Path, condition: str | None = None
) -> tuple[dict, ReplayClient, object]:
    arm = condition or "combined"
    case_path = recorded_case_path(case_id, arm)
    if not case_path.is_file():
        pytest.skip(f"recorded case not found at {case_path}")
    recorded = json.loads(case_path.read_text(encoding="utf-8"))
    client = ReplayClient(recorded_responses(case_path))
    adapter = SystemHintAdapter(client=client, run_root=run_root)
    return recorded, client, adapter.run(snapshot, CaseRef("combined", case_id, condition))


@pytest.mark.parametrize("case_id", COMBINED_IDS)
def test_replayed_episode_matches_the_recorded_gates(
    case_id: str, tmp_path: Path, default_snapshot_path: Path
) -> None:
    recorded, _, result = run_recorded(case_id, Snapshot.load(default_snapshot_path), tmp_path)

    assert result.objective_pass == recorded["objective_pass"]
    assert dict(result.component_scores) == recorded["component_scores"]
    assert result.llm_turns == recorded["llm_turns"]
    assert result.tokens == recorded["usage"]["total_tokens"]
    assert result.evidence_path.is_file()


def test_control_arm_reproduces_an_objective_failure(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    recorded, _, result = run_recorded(
        "all-04", Snapshot.load(default_snapshot_path), tmp_path, condition="disabled"
    )

    assert recorded["objective_pass"] is False
    assert result.objective_pass is False
    assert dict(result.component_scores) == recorded["component_scores"]


def test_unknown_case_is_rejected(tmp_path: Path, default_snapshot_path: Path) -> None:
    adapter = SystemHintAdapter(client=object(), run_root=tmp_path)
    with pytest.raises(KeyError):
        adapter.run(Snapshot.load(default_snapshot_path), CaseRef("combined", "nope-99"))


def test_episode_request_uses_the_supplied_snapshot(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    base = Snapshot.load(default_snapshot_path)
    edited = edited_snapshot(base, "SNAPSHOT-MARKER-SYSTEM-PROMPT")

    _, client, _ = run_recorded("all-01", edited, tmp_path)

    assert client.requests
    system_messages = [
        message for message in client.requests[0]["messages"] if message["role"] == "system"
    ]
    assert system_messages
    assert system_messages[0]["content"] == "SNAPSHOT-MARKER-SYSTEM-PROMPT"


def test_failure_digest_reports_gates_and_transcript(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    case_path = recorded_case_path("all-04", "disabled")
    if not case_path.is_file():
        pytest.skip(f"recorded case not found at {case_path}")
    snapshot = Snapshot.load(default_snapshot_path)
    case = CaseRef("combined", "all-04", "disabled")
    adapter = SystemHintAdapter(client=ReplayClient(recorded_responses(case_path)), run_root=tmp_path)

    digest = adapter.failure_digest(snapshot, case, adapter.run(snapshot, case))

    assert "objective_pass=False" in digest
    assert "failed_gates=['timestamps']" in digest
    assert "termination=submit_result" in digest
    assert "-- transcript --" in digest
    assert "assistant: " in digest


def test_distinct_snapshots_use_distinct_evidence_dirs(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    require_target()
    adapter = SystemHintAdapter(client=object(), run_root=tmp_path)
    base = Snapshot.load(default_snapshot_path)
    case = CaseRef("combined", "all-01")

    assert adapter.episode_dir(base, case) == adapter.episode_dir(base, case)
    assert adapter.episode_dir(base, case) != adapter.episode_dir(edited_snapshot(base, "x"), case)


def test_paired_arms_keep_separate_evidence_on_disk(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    case_path = recorded_case_path("all-01")
    if not case_path.is_file():
        pytest.skip(f"recorded case not found at {case_path}")
    recorded = json.loads(case_path.read_text(encoding="utf-8"))
    responses = recorded_responses(case_path)
    adapter = SystemHintAdapter(client=ReplayClient(responses + responses), run_root=tmp_path)
    base = Snapshot.load(default_snapshot_path)
    case = CaseRef("combined", "all-01")

    baseline = adapter.run(base, case)
    candidate = adapter.run(edited_snapshot(base, "SNAPSHOT-MARKER"), case)

    assert baseline.evidence_path != candidate.evidence_path
    assert baseline.evidence_path.is_file()
    assert candidate.evidence_path.is_file()
    assert baseline.objective_pass == candidate.objective_pass == recorded["objective_pass"]
