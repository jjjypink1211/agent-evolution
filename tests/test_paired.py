"""Accept/rollback decisions on constructed fake data, and report persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.paired import (
    Decision,
    bootstrap_interval,
    evaluate,
    render_report,
    report_payload,
    save_report,
)
from agent_evolution.snapshot import Snapshot

from fake_adapter import FakeAdapter
from support import combined_cases, episode

BASELINE = Snapshot(system_prompt="baseline")
CANDIDATE = Snapshot(system_prompt="candidate")


def ids(count: int) -> list[str]:
    return [case.case_id for case in combined_cases(count)]


def run_evaluation(
    baseline_passes: dict[str, bool],
    candidate_passes: dict[str, bool],
    *,
    candidate_tokens: int = 5,
    token_budget: int | None = None,
):
    cases = tuple(CaseRef("combined", case_id) for case_id in baseline_passes)

    def responder(snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        table = candidate_passes if snapshot is CANDIDATE else baseline_passes
        tokens = candidate_tokens if snapshot is CANDIDATE else 5
        return episode(
            bool(table[case.case_id]),
            tokens=tokens,
            evidence=f"{snapshot.system_prompt}__{case.case_id}.json",
        )

    return evaluate(
        FakeAdapter(responder=responder),
        baseline=BASELINE,
        candidate=CANDIDATE,
        cases=cases,
        suite="combined",
        token_budget=token_budget,
    )


def test_strict_improvement_is_accepted() -> None:
    case_ids = ids(5)
    report = run_evaluation(dict.fromkeys(case_ids, False), dict.fromkeys(case_ids, True))
    assert report.decision is Decision.ACCEPT
    assert (report.baseline_passes, report.candidate_passes) == (0, 5)
    assert report.net_passes == 5


def test_tie_rolls_back() -> None:
    case_ids = ids(5)
    report = run_evaluation(dict.fromkeys(case_ids, True), dict.fromkeys(case_ids, True))
    assert report.decision is Decision.ROLLBACK
    assert report.net_passes == 0


def test_regression_rolls_back() -> None:
    case_ids = ids(4)
    report = run_evaluation(dict.fromkeys(case_ids, True), dict.fromkeys(case_ids, False))
    assert report.decision is Decision.ROLLBACK
    assert report.net_passes == -4
    assert "no strict improvement" in report.reason


def test_insignificant_single_win_rolls_back() -> None:
    case_ids = ids(5)
    candidate = dict.fromkeys(case_ids, False)
    candidate[case_ids[0]] = True
    report = run_evaluation(dict.fromkeys(case_ids, False), candidate)
    assert report.net_passes == 1
    assert report.confidence_low <= 0
    assert report.decision is Decision.ROLLBACK
    assert "not significant" in report.reason


def test_significant_majority_is_accepted() -> None:
    case_ids = ids(10)
    candidate = dict.fromkeys(case_ids, False)
    for case_id in case_ids[:8]:
        candidate[case_id] = True
    report = run_evaluation(dict.fromkeys(case_ids, False), candidate)
    assert report.net_passes == 8
    assert report.confidence_low > 0
    assert report.decision is Decision.ACCEPT


def test_token_budget_is_enforced() -> None:
    case_ids = ids(3)
    report = run_evaluation(
        dict.fromkeys(case_ids, False),
        dict.fromkeys(case_ids, True),
        candidate_tokens=100,
        token_budget=10,
    )
    assert report.net_passes == 3
    assert report.decision is Decision.ROLLBACK
    assert "token budget exceeded" in report.reason


def test_single_case_fallback_accepts() -> None:
    report = run_evaluation({"all-01": False}, {"all-01": True})
    assert report.decision is Decision.ACCEPT
    assert "fallback" in report.reason


def test_bootstrap_interval_is_reproducible() -> None:
    deltas = [1, 0, 1, 1, 0, 0, 1]
    assert bootstrap_interval(deltas, resamples=2000, seed=7) == bootstrap_interval(
        deltas, resamples=2000, seed=7
    )


def test_decisions_are_reproducible() -> None:
    case_ids = ids(6)
    candidate = dict.fromkeys(case_ids, False)
    for case_id in case_ids[:4]:
        candidate[case_id] = True
    first = run_evaluation(dict.fromkeys(case_ids, False), candidate)
    second = run_evaluation(dict.fromkeys(case_ids, False), candidate)
    assert report_payload(first) == report_payload(second)


def test_save_report_writes_summary_and_per_case_evidence(tmp_path: Path) -> None:
    case_ids = ids(3)
    report = run_evaluation(dict.fromkeys(case_ids, False), dict.fromkeys(case_ids, True))

    save_report(report, tmp_path)

    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "accept"
    assert payload["net_passes"] == 3
    assert [case["case_id"] for case in payload["cases"]] == case_ids
    assert all(case["candidate_evidence"] for case in payload["cases"])
    assert (tmp_path / "summary.txt").is_file()


def test_render_report_lists_every_case() -> None:
    case_ids = ids(3)
    report = run_evaluation(dict.fromkeys(case_ids, False), dict.fromkeys(case_ids, True))

    text = render_report(report)

    assert "decision: accept" in text
    assert all(case_id in text for case_id in case_ids)


def test_baseline_results_are_reused_instead_of_rerun() -> None:
    cases = tuple(CaseRef("combined", case_id) for case_id in ids(3))
    baseline_results = [
        episode(False, tokens=7, evidence=f"pre__{case.case_id}.json") for case in cases
    ]

    def responder(snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        return episode(True, tokens=5, evidence=f"cand__{case.case_id}.json")

    adapter = FakeAdapter(responder=responder)
    report = evaluate(
        adapter,
        baseline=BASELINE,
        candidate=CANDIDATE,
        cases=cases,
        suite="combined",
        baseline_results=baseline_results,
    )

    assert report.decision is Decision.ACCEPT
    assert (report.baseline_passes, report.candidate_passes) == (0, 3)
    assert report.baseline_tokens == 21
    assert [case for _, case in adapter.calls] == list(cases)
    assert all(snapshot is CANDIDATE for snapshot, _ in adapter.calls)


def test_baseline_results_must_line_up_with_cases() -> None:
    cases = tuple(CaseRef("combined", case_id) for case_id in ids(3))
    with pytest.raises(ValueError, match="baseline_results"):
        evaluate(
            FakeAdapter(),
            baseline=BASELINE,
            candidate=CANDIDATE,
            cases=cases,
            suite="combined",
            baseline_results=[episode(False)],
        )
