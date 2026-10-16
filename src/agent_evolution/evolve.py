"""The evolution loop: propose one edit, paired-evaluate it, keep or roll back (ADR-0005).

One run drives the proposer (ADR-0004) and the paired evaluator (ADR-0003) for up
to ``rounds`` rounds against a fixed set of cases. Each round runs the current
baseline once - both to hand the proposer its failure digests and to avoid running
the baseline a second time inside the paired evaluation - asks for one edit, runs
the candidate, and keeps the candidate as the new baseline only when the paired
criterion accepts it. Every round's snapshots, edit, report and verdict, plus a
run-level history, are written to a run directory so any round can be inspected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Sequence

from agent_evolution.adapter import Adapter, CaseRef, EpisodeResult
from agent_evolution.paired import (
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    Decision,
    PairedReport,
    evaluate,
    save_report,
)
from agent_evolution.proposer import FailureReport, Proposal, ProposalError, Proposer
from agent_evolution.snapshot import Snapshot

DEFAULT_ROUNDS = 10
DEFAULT_MAX_FAILURES = 5
DEFAULT_MAX_ROLLBACKS = 3

ROUNDS_DIR = "rounds"
BASELINE_DIR = "baseline"
CANDIDATE_DIR = "candidate"
EDIT_JSON = "edit.json"
DECISION_JSON = "decision.json"
HISTORY_JSON = "history.json"
HISTORY_TEXT = "history.md"


class StopReason(StrEnum):
    """Why a run stopped before, or on, its last requested round."""

    ROUNDS = "rounds_exhausted"
    BUDGET = "token_budget_reached"
    ROLLBACKS = "too_many_rollbacks"
    PROPOSER = "proposer_failed"
    NO_CASES = "no_cases"


@dataclass(frozen=True)
class RoundRecord:
    """One round: the edit that was proposed and how the paired criterion judged it."""

    index: int
    baseline: Snapshot
    candidate: Snapshot
    proposal: Proposal
    report: PairedReport

    @property
    def accepted(self) -> bool:
        return self.report.decision is Decision.ACCEPT

    @property
    def tokens(self) -> int:
        """Every token this round spent: the baseline arm plus the candidate arm."""
        return self.report.baseline_tokens + self.report.candidate_tokens


@dataclass(frozen=True)
class RunReport:
    """The whole run: every round, why it stopped, and the final accepted baseline."""

    suite_label: str
    suites: tuple[str, ...]
    rounds_requested: int
    stop_reason: StopReason
    detail: str
    tokens_used: int
    budget_tokens: int | None
    max_rollbacks: int
    baseline: Snapshot
    rounds: tuple[RoundRecord, ...]

    @property
    def rounds_run(self) -> int:
        return len(self.rounds)

    @property
    def accepts(self) -> int:
        return sum(record.accepted for record in self.rounds)

    @property
    def rollbacks(self) -> int:
        return self.rounds_run - self.accepts

    @property
    def stopped_early(self) -> bool:
        return self.rounds_run < self.rounds_requested


def run_evolution(
    adapter: Adapter,
    proposer: Proposer,
    *,
    baseline: Snapshot,
    cases: Sequence[CaseRef],
    suites: Sequence[str],
    label: str,
    rounds: int = DEFAULT_ROUNDS,
    budget_tokens: int | None = None,
    max_failures: int = DEFAULT_MAX_FAILURES,
    max_rollbacks: int = DEFAULT_MAX_ROLLBACKS,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    on_round: Callable[[RoundRecord], None] | None = None,
) -> RunReport:
    """Search for a better baseline over ``rounds`` rounds, keeping the winner.

    Each accepted round replaces the baseline; a rolled-back round leaves the
    baseline untouched. ``budget_tokens`` caps the run's **episode** tokens (the
    target's own model calls; the proposer's calls are not counted): a round is
    only started when the tokens spent so far, plus one round like the last, stay
    within budget, so the run stops before the round that would exceed it.
    ``max_rollbacks`` (0 disables it) stops the run after that many consecutive
    rollbacks. ``max_failures`` caps how many failing episodes are shown to the
    proposer (0 shows none, a negative value shows all).
    """
    records: list[RoundRecord] = []
    tokens_used = 0
    last_round_tokens = 0
    consecutive_rollbacks = 0
    current = baseline
    stop_reason = StopReason.ROUNDS
    detail = ""
    if not cases:
        stop_reason = StopReason.NO_CASES
    else:
        for index in range(1, rounds + 1):
            if budget_tokens is not None and _over_budget(
                tokens_used, last_round_tokens, budget_tokens
            ):
                stop_reason = StopReason.BUDGET
                break
            baseline_outcomes = _run_cases(adapter, current, cases)
            failures = _failure_reports(adapter, current, baseline_outcomes, max_failures)
            try:
                proposal = proposer.propose(current, failures)
            except ProposalError as error:
                stop_reason, detail = StopReason.PROPOSER, str(error)
                break
            candidate = proposal.candidate(current)
            report = evaluate(
                adapter,
                baseline=current,
                candidate=candidate,
                cases=cases,
                suite=label,
                baseline_label=f"round-{index:02d}-baseline",
                candidate_label=f"round-{index:02d}-candidate",
                baseline_results=[result for _, result in baseline_outcomes],
                resamples=resamples,
                seed=seed,
            )
            record = RoundRecord(index, current, candidate, proposal, report)
            records.append(record)
            tokens_used += record.tokens
            last_round_tokens = record.tokens
            if on_round is not None:
                on_round(record)
            if record.accepted:
                current, consecutive_rollbacks = candidate, 0
            else:
                consecutive_rollbacks += 1
                if max_rollbacks and consecutive_rollbacks >= max_rollbacks:
                    stop_reason = StopReason.ROLLBACKS
                    break
    return RunReport(
        suite_label=label,
        suites=tuple(suites),
        rounds_requested=rounds,
        stop_reason=stop_reason,
        detail=detail,
        tokens_used=tokens_used,
        budget_tokens=budget_tokens,
        max_rollbacks=max_rollbacks,
        baseline=current,
        rounds=tuple(records),
    )


def _over_budget(spent: int, last_round: int, budget: int) -> bool:
    """Whether the budget is spent, or one more round like the last would exceed it."""
    if spent >= budget:
        return True
    return last_round > 0 and spent + last_round > budget


def _run_cases(
    adapter: Adapter, snapshot: Snapshot, cases: Sequence[CaseRef]
) -> list[tuple[CaseRef, EpisodeResult]]:
    return [(case, adapter.run(snapshot, case)) for case in cases]


def _failure_reports(
    adapter: Adapter,
    snapshot: Snapshot,
    outcomes: Sequence[tuple[CaseRef, EpisodeResult]],
    limit: int,
) -> tuple[FailureReport, ...]:
    failing = sorted(
        ((case, result) for case, result in outcomes if not result.objective_pass),
        key=lambda item: (item[0].suite, item[0].case_id),
    )
    selected = failing if limit < 0 else failing[:limit]
    return tuple(
        FailureReport(case=case, result=result, digest=adapter.failure_digest(snapshot, case, result))
        for case, result in selected
    )


def round_payload(record: RoundRecord) -> dict:
    """A JSON-serialisable view of one round for the run history."""
    return {
        "round": record.index,
        "edit": record.proposal.edit.to_payload(),
        "attempts": record.proposal.attempts,
        "baseline_fingerprint": record.baseline.fingerprint(),
        "candidate_fingerprint": record.candidate.fingerprint(),
        "decision": record.report.decision.value,
        "reason": record.report.reason,
        "net_passes": record.report.net_passes,
        "baseline_passes": record.report.baseline_passes,
        "candidate_passes": record.report.candidate_passes,
        "tokens": record.tokens,
    }


def history_payload(report: RunReport) -> dict:
    """A JSON-serialisable view of a whole run, including every round."""
    return {
        "suite_label": report.suite_label,
        "suites": list(report.suites),
        "rounds_requested": report.rounds_requested,
        "rounds_run": report.rounds_run,
        "accepts": report.accepts,
        "rollbacks": report.rollbacks,
        "tokens_used": report.tokens_used,
        "budget_tokens": report.budget_tokens,
        "max_rollbacks": report.max_rollbacks,
        "stop_reason": report.stop_reason.value,
        "detail": report.detail,
        "stopped_early": report.stopped_early,
        "baseline_fingerprint": report.baseline.fingerprint(),
        "rounds": [round_payload(record) for record in report.rounds],
    }


def render_history(report: RunReport) -> str:
    """A human-readable run history: the stop line and one row per round."""
    budget = "none" if report.budget_tokens is None else str(report.budget_tokens)
    stop = report.stop_reason.value + (f" - {report.detail}" if report.detail else "")
    lines = [
        f"evolution: suites={report.suite_label or '(unspecified)'} "
        f"rounds={report.rounds_run}/{report.rounds_requested}",
        f"  stop: {stop}",
        f"  accepts {report.accepts}, rollbacks {report.rollbacks}",
        f"  tokens used {report.tokens_used} (budget {budget})",
        f"  final baseline: {report.baseline.fingerprint()}",
        "",
        f"{'round':<7}{'decision':<10}{'net':<5}edit",
    ]
    for record in report.rounds:
        lines.append(
            f"{record.index:02d}     {record.report.decision.value:<10}"
            f"{record.report.net_passes:+d}   {record.proposal.edit.describe()}"
        )
    return "\n".join(lines)


def save_run(report: RunReport, run_dir: Path) -> Path:
    """Write the run's per-round artifacts, history, and final baseline to ``run_dir``."""
    run_dir = Path(run_dir)
    for record in report.rounds:
        round_dir = run_dir / ROUNDS_DIR / f"{record.index:02d}"
        record.baseline.save(round_dir / BASELINE_DIR)
        record.candidate.save(round_dir / CANDIDATE_DIR)
        _write_json(
            round_dir / EDIT_JSON,
            {**record.proposal.edit.to_payload(), "attempts": record.proposal.attempts},
        )
        save_report(record.report, round_dir)
        _write_json(
            round_dir / DECISION_JSON,
            {
                "decision": record.report.decision.value,
                "reason": record.report.reason,
                "net_passes": record.report.net_passes,
            },
        )
    report.baseline.save(run_dir / BASELINE_DIR)
    _write_json(run_dir / HISTORY_JSON, history_payload(report))
    (run_dir / HISTORY_TEXT).write_text(
        render_history(report) + "\n", encoding="utf-8", newline="\n"
    )
    return run_dir


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


__all__ = [
    "DEFAULT_MAX_FAILURES",
    "DEFAULT_MAX_ROLLBACKS",
    "DEFAULT_ROUNDS",
    "HISTORY_JSON",
    "HISTORY_TEXT",
    "RoundRecord",
    "RunReport",
    "StopReason",
    "history_payload",
    "render_history",
    "round_payload",
    "run_evolution",
    "save_run",
]
