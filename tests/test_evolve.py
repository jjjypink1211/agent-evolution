"""The evolution loop: deterministic accept/rollback progression and its stop reasons."""

from __future__ import annotations

import json
from pathlib import Path

from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.evolve import (
    StopReason,
    history_payload,
    render_history,
    run_evolution,
    save_run,
)
from agent_evolution.proposer import Proposer
from agent_evolution.snapshot import Snapshot

from fake_adapter import FakeAdapter
from scripted_model import ScriptedModel
from support import episode, system_prompt_edits

CASES = tuple(CaseRef("combined", f"all-{index:02d}") for index in range(1, 6))
ALL_IDS = {case.case_id for case in CASES}


def adapter_for(passing: dict[str, set[str]]) -> FakeAdapter:
    def responder(snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        return episode(
            case.case_id in passing.get(snapshot.system_prompt, set()),
            tokens=5,
            evidence=f"{snapshot.system_prompt}__{case.case_id}.json",
        )

    return FakeAdapter(responder=responder, cases=CASES)


def run(passing, *prompts, **kwargs):
    return run_evolution(
        adapter_for(passing),
        Proposer(model=system_prompt_edits(*prompts)),
        baseline=Snapshot(system_prompt="v0"),
        cases=CASES,
        suites=("combined",),
        label="combined",
        **kwargs,
    )


def test_accept_then_rollback_keeps_the_best_baseline() -> None:
    passing = {"v0": set(), "v1": set(ALL_IDS), "v2": set(ALL_IDS), "v3": set()}

    report = run(passing, "v1", "v2", "v3", rounds=3)

    assert report.stop_reason is StopReason.ROUNDS
    assert report.rounds_run == 3
    assert (report.accepts, report.rollbacks) == (1, 2)
    assert [record.accepted for record in report.rounds] == [True, False, False]
    assert report.baseline.system_prompt == "v1"
    assert report.rounds[0].candidate.system_prompt == "v1"
    assert report.rounds[1].baseline.system_prompt == "v1"
    assert report.rounds[2].baseline.system_prompt == "v1"


def test_budget_stops_before_the_next_round() -> None:
    passing = {"v0": set(), "v1": set(ALL_IDS)}

    report = run(passing, "v1", "v2", rounds=10, budget_tokens=50)

    assert report.stop_reason is StopReason.BUDGET
    assert report.rounds_run == 1
    assert report.tokens_used == 50
    assert report.stopped_early


def test_budget_stops_before_the_round_that_would_exceed() -> None:
    passing = {"v0": set(), "v1": set(ALL_IDS), "v2": set(ALL_IDS), "v3": set(ALL_IDS)}

    report = run(passing, "v1", "v2", "v3", rounds=10, budget_tokens=100)

    assert report.stop_reason is StopReason.BUDGET
    assert report.rounds_run == 2
    assert report.tokens_used == 100


def test_rounds_are_exhausted_when_rollbacks_are_disabled() -> None:
    passing = {"v0": set(ALL_IDS), "v1": set(), "v2": set()}

    report = run(passing, "v1", "v2", rounds=2, max_rollbacks=0)

    assert report.stop_reason is StopReason.ROUNDS
    assert report.rounds_run == 2
    assert report.rollbacks == 2


def test_consecutive_rollbacks_stop_the_run() -> None:
    passing = {"v0": set(ALL_IDS), "v1": set(), "v2": set(), "v3": set()}

    report = run(passing, "v1", "v2", "v3", rounds=10, max_rollbacks=2)

    assert report.stop_reason is StopReason.ROLLBACKS
    assert report.rounds_run == 2


def test_a_proposer_that_cannot_propose_stops_gracefully() -> None:
    model = ScriptedModel(replies=["not json", "still not json"])

    report = run_evolution(
        adapter_for({"v0": set()}),
        Proposer(model=model),
        baseline=Snapshot(system_prompt="v0"),
        cases=CASES,
        suites=("combined",),
        label="combined",
        rounds=5,
    )

    assert report.stop_reason is StopReason.PROPOSER
    assert report.rounds_run == 0
    assert "no usable edit" in report.detail


def test_no_cases_stops_immediately() -> None:
    report = run_evolution(
        FakeAdapter(),
        Proposer(model=ScriptedModel()),
        baseline=Snapshot(),
        cases=(),
        suites=("combined",),
        label="combined",
        rounds=5,
    )

    assert report.stop_reason is StopReason.NO_CASES
    assert report.rounds_run == 0


def test_max_failures_caps_the_proposer_input() -> None:
    model = system_prompt_edits("v1")

    run_evolution(
        FakeAdapter(responder=lambda snapshot, case: episode(False), cases=CASES),
        Proposer(model=model),
        baseline=Snapshot(system_prompt="v0"),
        cases=CASES,
        suites=("combined",),
        label="combined",
        rounds=1,
        max_failures=2,
    )

    _, user = model.calls[0]
    assert "## combined/all-01" in user and "## combined/all-02" in user
    assert "## combined/all-03" not in user


def test_on_round_is_called_once_per_round() -> None:
    seen: list[int] = []

    run(
        {"v0": set(ALL_IDS), "v1": set(), "v2": set()},
        "v1",
        "v2",
        rounds=2,
        max_rollbacks=0,
        on_round=lambda record: seen.append(record.index),
    )

    assert seen == [1, 2]


def test_baseline_is_run_once_and_reused_across_rollbacks() -> None:
    adapter = adapter_for({"v0": set(ALL_IDS), "v1": set(), "v2": set()})

    run_evolution(
        adapter,
        Proposer(model=system_prompt_edits("v1", "v2")),
        baseline=Snapshot(system_prompt="v0"),
        cases=CASES,
        suites=("combined",),
        label="combined",
        rounds=2,
        max_rollbacks=0,
    )

    baseline_runs = [snapshot for snapshot, _ in adapter.calls if snapshot.system_prompt == "v0"]
    assert len(baseline_runs) == len(CASES)


def test_workers_do_not_change_the_decision() -> None:
    passing = {"v0": set(), "v1": set(ALL_IDS), "v2": set(ALL_IDS), "v3": set()}

    sequential = run(passing, "v1", "v2", "v3", rounds=3, max_workers=1)
    concurrent = run(passing, "v1", "v2", "v3", rounds=3, max_workers=4)

    assert [record.accepted for record in concurrent.rounds] == [
        record.accepted for record in sequential.rounds
    ]
    assert concurrent.baseline.system_prompt == sequential.baseline.system_prompt


def test_save_run_writes_round_artifacts_and_history(tmp_path: Path) -> None:
    report = run({"v0": set(), "v1": set(ALL_IDS)}, "v1", rounds=1)

    save_run(report, tmp_path)

    round_dir = tmp_path / "rounds" / "01"
    assert (tmp_path / "history.json").is_file()
    assert (tmp_path / "history.md").is_file()
    assert (tmp_path / "baseline" / "snapshot.json").is_file()
    assert (round_dir / "baseline" / "snapshot.json").is_file()
    assert (round_dir / "candidate" / "snapshot.json").is_file()
    assert (round_dir / "summary.json").is_file()
    assert (round_dir / "summary.txt").is_file()

    edit = json.loads((round_dir / "edit.json").read_text(encoding="utf-8"))
    assert edit["kind"] == "system_prompt" and edit["value"] == "v1"
    assert json.loads((round_dir / "decision.json").read_text(encoding="utf-8"))["decision"] == "accept"

    payload = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert payload["accepts"] == 1
    assert payload["stop_reason"] == "rounds_exhausted"
    assert payload["baseline_fingerprint"] == Snapshot(system_prompt="v1").fingerprint()


def test_render_history_summarises_the_run() -> None:
    report = run({"v0": set(), "v1": set(ALL_IDS)}, "v1", rounds=1)

    text = render_history(report)

    assert "stop: rounds_exhausted" in text
    assert "accepts 1, rollbacks 0" in text
    assert "system_prompt := v1" in text
    assert history_payload(report)["rounds"][0]["decision"] == "accept"
