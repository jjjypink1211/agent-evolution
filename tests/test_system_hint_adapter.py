"""SystemHintAdapter reproduces the target's own gates, offline, from recordings.

It also drives the target with an evidence-only policy double, to prove that a
snapshot feature flip reaches the objective gate (see ADR-0006).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_evolution.adapter import CaseRef
from agent_evolution.edit import ON, Edit, EditKind
from agent_evolution.snapshot import Snapshot
from agent_evolution.system_hint_adapter import SystemHintAdapter, provider_key_vars, resolve_api_key
from agent_evolution.target_harness import TARGET_MODULE_NAME, resolve_target_dir

from policy_client import EvidencePolicyClient
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


def without_feature(base: Snapshot, feature: str) -> Snapshot:
    return Snapshot(
        features=tuple(name for name in base.features if name != feature),
        system_prompt=base.system_prompt,
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


def run_policy(
    snapshot: Snapshot, case_id: str, run_root: Path
) -> tuple[EvidencePolicyClient, object]:
    client = EvidencePolicyClient()
    adapter = SystemHintAdapter(client=client, run_root=run_root)
    return client, adapter.run(snapshot, CaseRef("combined", case_id))


def test_flipping_a_feature_off_moves_the_objective_gate(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    require_target()
    base = Snapshot.load(default_snapshot_path)

    _, enabled = run_policy(base, "all-01", tmp_path)
    _, disabled = run_policy(without_feature(base, "timestamps"), "all-01", tmp_path)

    assert dict(enabled.component_scores) == {
        "timestamps": True,
        "tool_counter": True,
        "todo_list": True,
        "detailed_errors": True,
        "system_state": True,
    }
    assert enabled.objective_pass is True
    assert disabled.component_scores["timestamps"] is False
    assert all(
        ok for name, ok in disabled.component_scores.items() if name != "timestamps"
    )
    assert disabled.objective_pass is False


def test_flipping_a_feature_on_moves_the_objective_gate(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    require_target()
    reduced = without_feature(Snapshot.load(default_snapshot_path), "timestamps")
    enabled = Edit(EditKind.FEATURE, key="timestamps", value=ON).apply(reduced)

    _, off = run_policy(reduced, "all-01", tmp_path)
    _, on = run_policy(enabled, "all-01", tmp_path)

    assert off.component_scores["timestamps"] is False
    assert off.objective_pass is False
    assert dict(on.component_scores) == {
        "timestamps": True,
        "tool_counter": True,
        "todo_list": True,
        "detailed_errors": True,
        "system_state": True,
    }
    assert on.objective_pass is True


def test_feature_flip_reaches_the_surface_the_agent_sees(
    tmp_path: Path, default_snapshot_path: Path
) -> None:
    require_target()
    base = Snapshot.load(default_snapshot_path)

    on_client, _ = run_policy(base, "all-01", tmp_path)
    off_client, _ = run_policy(without_feature(base, "timestamps"), "all-01", tmp_path)

    stamp = re.compile(r"\[2025-\d\d-\d\d [\d:]{8}\]")
    assert stamp.search(json.dumps(on_client.requests, ensure_ascii=False))
    assert not stamp.search(json.dumps(off_client.requests, ensure_ascii=False))


def test_provider_key_vars_follow_the_named_provider() -> None:
    assert provider_key_vars("deepseek") == ("DEEPSEEK_API_KEY",)
    assert provider_key_vars("kimi") == ("MOONSHOT_API_KEY", "KIMI_API_KEY")
    assert provider_key_vars("moonshot") == provider_key_vars("kimi")


def test_provider_key_vars_are_empty_for_an_unknown_provider() -> None:
    assert provider_key_vars("mystery-provider") == ()


def test_resolve_api_key_keys_off_the_provider_not_the_environment_order() -> None:
    env = {"MOONSHOT_API_KEY": "kimi-key", "DEEPSEEK_API_KEY": "deepseek-key"}

    assert resolve_api_key("deepseek", env) == "deepseek-key"
    assert resolve_api_key("moonshot", env) == "kimi-key"
    assert resolve_api_key("openai", env) is None


def test_resolve_api_key_ignores_blank_values() -> None:
    assert resolve_api_key("deepseek", {"DEEPSEEK_API_KEY": "   "}) is None
