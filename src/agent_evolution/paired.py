"""Paired evaluation of a candidate harness against a baseline (ADR-0003).

The evaluator is target-agnostic: it drives an :class:`Adapter` over an explicit
list of :class:`CaseRef` cases, runs every case against both the baseline and the
candidate snapshot, and decides accept-or-rollback from the paired outcomes. It
never inspects a target loop or a snapshot diff directly.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from agent_evolution.adapter import Adapter, CaseRef, EpisodeResult
from agent_evolution.parallel import run_batch
from agent_evolution.snapshot import Snapshot

DEFAULT_RESAMPLES = 10000
DEFAULT_SEED = 20261015
DEFAULT_CONFIDENCE = 0.95

SUMMARY_JSON = "summary.json"
SUMMARY_TEXT = "summary.txt"


class Decision(StrEnum):
    """Whether a candidate harness is kept or reverted."""

    ACCEPT = "accept"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class CaseOutcome:
    """One case, run against the baseline and the candidate snapshot."""

    case: CaseRef
    baseline: EpisodeResult
    candidate: EpisodeResult

    @property
    def delta(self) -> int:
        """Paired pass difference for this case: +1 win, 0 tie, -1 loss."""
        return int(self.candidate.objective_pass) - int(self.baseline.objective_pass)


@dataclass(frozen=True)
class PairedReport:
    """The paired pass rate, per-case detail, and the accept/rollback decision."""

    suite: str
    baseline_label: str
    candidate_label: str
    outcomes: tuple[CaseOutcome, ...]
    baseline_passes: int
    candidate_passes: int
    confidence_low: float
    confidence_high: float
    confidence: float
    resamples: int
    seed: int
    token_budget: int | None
    baseline_tokens: int
    candidate_tokens: int
    decision: Decision
    reason: str

    @property
    def count(self) -> int:
        return len(self.outcomes)

    @property
    def net_passes(self) -> int:
        """How many more cases the candidate passes than the baseline."""
        return self.candidate_passes - self.baseline_passes

    @property
    def baseline_pass_rate(self) -> float:
        return self.baseline_passes / self.count if self.count else 0.0

    @property
    def candidate_pass_rate(self) -> float:
        return self.candidate_passes / self.count if self.count else 0.0


def paired_outcomes(
    adapter: Adapter,
    baseline: Snapshot,
    candidate: Snapshot,
    cases: Sequence[CaseRef],
    *,
    max_workers: int | None = None,
) -> tuple[CaseOutcome, ...]:
    """Run every case against both snapshots and pair the results.

    The two arms run one whole batch after the other - never interleaved - so
    only one snapshot is in flight at a time (the target loop keeps its loaded
    harness in a module-global). ``max_workers`` runs each batch's episodes
    concurrently; see :mod:`agent_evolution.parallel`.
    """
    ordered = list(cases)
    baseline_results = run_batch(adapter, baseline, ordered, max_workers=max_workers)
    candidate_results = run_batch(adapter, candidate, ordered, max_workers=max_workers)
    return tuple(
        CaseOutcome(case, base, cand)
        for case, base, cand in zip(ordered, baseline_results, candidate_results)
    )


def candidate_outcomes(
    adapter: Adapter,
    candidate: Snapshot,
    cases: Sequence[CaseRef],
    baseline_results: Sequence[EpisodeResult],
    *,
    max_workers: int | None = None,
) -> tuple[CaseOutcome, ...]:
    """Pair precomputed baseline episodes with freshly run candidate episodes.

    The evolution loop has already run the baseline to gather the proposer's
    failure digests, so it hands those episodes in rather than paying to run the
    same baseline twice in one round. ``max_workers`` runs the candidate episodes
    concurrently; see :mod:`agent_evolution.parallel`.
    """
    if len(baseline_results) != len(cases):
        raise ValueError(
            f"baseline_results has {len(baseline_results)} episodes for {len(cases)} cases"
        )
    candidate_results = run_batch(adapter, candidate, list(cases), max_workers=max_workers)
    return tuple(
        CaseOutcome(case, base, cand)
        for case, base, cand in zip(cases, baseline_results, candidate_results)
    )


def bootstrap_interval(
    deltas: Sequence[int],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean paired delta, reproducible by seed."""
    values = list(deltas)
    count = len(values)
    if count == 0:
        return 0.0, 0.0
    generator = random.Random(seed)
    means = sorted(
        sum(values[generator.randrange(count)] for _ in range(count)) / count
        for _ in range(resamples)
    )
    lower = max(0, min(resamples - 1, int((1 - confidence) / 2 * resamples)))
    upper = max(0, min(resamples - 1, int((1 + confidence) / 2 * resamples)))
    return means[lower], means[upper]


def evaluate(
    adapter: Adapter,
    *,
    baseline: Snapshot,
    candidate: Snapshot,
    cases: Sequence[CaseRef],
    suite: str,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
    baseline_results: Sequence[EpisodeResult] | None = None,
    token_budget: int | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
    max_workers: int | None = None,
) -> PairedReport:
    """Pair-evaluate ``candidate`` against ``baseline`` and decide keep-or-revert.

    Accept when the candidate passes strictly more cases **and** the bootstrap
    lower bound of the paired delta exceeds zero **and** the token cost is within
    budget. On a degenerate interval (a single case) a strict improvement of at
    least one case is enough (ADR-0003).

    ``baseline_results`` lets a caller that has already run the baseline episodes
    (the evolution loop, to build the proposer's failure digests) reuse them
    instead of running the baseline a second time; it must line up one-to-one with
    ``cases``. ``max_workers`` runs each arm's episodes concurrently.
    """
    if baseline_results is None:
        outcomes = paired_outcomes(adapter, baseline, candidate, cases, max_workers=max_workers)
    else:
        outcomes = candidate_outcomes(
            adapter, candidate, cases, baseline_results, max_workers=max_workers
        )
    baseline_passes = sum(int(outcome.baseline.objective_pass) for outcome in outcomes)
    candidate_passes = sum(int(outcome.candidate.objective_pass) for outcome in outcomes)
    baseline_tokens = sum(outcome.baseline.tokens for outcome in outcomes)
    candidate_tokens = sum(outcome.candidate.tokens for outcome in outcomes)
    net = candidate_passes - baseline_passes
    low, high = bootstrap_interval(
        [outcome.delta for outcome in outcomes],
        resamples=resamples,
        seed=seed,
        confidence=confidence,
    )
    decision, reason = _decide(
        count=len(outcomes),
        net=net,
        low=low,
        candidate_tokens=candidate_tokens,
        token_budget=token_budget,
        confidence=confidence,
    )
    return PairedReport(
        suite=suite,
        baseline_label=baseline_label,
        candidate_label=candidate_label,
        outcomes=outcomes,
        baseline_passes=baseline_passes,
        candidate_passes=candidate_passes,
        confidence_low=low,
        confidence_high=high,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
        token_budget=token_budget,
        baseline_tokens=baseline_tokens,
        candidate_tokens=candidate_tokens,
        decision=decision,
        reason=reason,
    )


def _decide(
    *,
    count: int,
    net: int,
    low: float,
    candidate_tokens: int,
    token_budget: int | None,
    confidence: float,
) -> tuple[Decision, str]:
    percent = round(confidence * 100)
    if count == 0:
        return Decision.ROLLBACK, "no cases to evaluate"
    if token_budget is not None and candidate_tokens > token_budget:
        return Decision.ROLLBACK, f"token budget exceeded: {candidate_tokens} > {token_budget}"
    if net <= 0:
        return Decision.ROLLBACK, f"no strict improvement: net {net:+d} cases"
    if count < 2:
        return (
            Decision.ACCEPT,
            f"single-case fallback: net {net:+d} with no interval power",
        )
    if low > 0:
        return (
            Decision.ACCEPT,
            f"strict improvement (net {net:+d}) with bootstrap {percent}% lower bound {low:+.3f} > 0",
        )
    return (
        Decision.ROLLBACK,
        f"bootstrap {percent}% lower bound {low:+.3f} <= 0: improvement not significant",
    )


def report_payload(report: PairedReport) -> dict:
    """A JSON-serialisable view of a report, including every case and its evidence."""
    return {
        "suite": report.suite,
        "baseline_label": report.baseline_label,
        "candidate_label": report.candidate_label,
        "count": report.count,
        "baseline_passes": report.baseline_passes,
        "candidate_passes": report.candidate_passes,
        "net_passes": report.net_passes,
        "baseline_pass_rate": report.baseline_pass_rate,
        "candidate_pass_rate": report.candidate_pass_rate,
        "confidence": report.confidence,
        "confidence_interval": [report.confidence_low, report.confidence_high],
        "resamples": report.resamples,
        "seed": report.seed,
        "token_budget": report.token_budget,
        "baseline_tokens": report.baseline_tokens,
        "candidate_tokens": report.candidate_tokens,
        "decision": report.decision.value,
        "reason": report.reason,
        "cases": [
            {
                "suite": outcome.case.suite,
                "case_id": outcome.case.case_id,
                "condition": outcome.case.condition,
                "baseline_pass": outcome.baseline.objective_pass,
                "candidate_pass": outcome.candidate.objective_pass,
                "delta": outcome.delta,
                "baseline_tokens": outcome.baseline.tokens,
                "candidate_tokens": outcome.candidate.tokens,
                "baseline_evidence": str(outcome.baseline.evidence_path),
                "candidate_evidence": str(outcome.candidate.evidence_path),
            }
            for outcome in report.outcomes
        ],
    }


def render_report(report: PairedReport) -> str:
    """A human-readable report: pass rates, the interval, and one row per case."""
    percent = round(report.confidence * 100)
    budget = "none" if report.token_budget is None else str(report.token_budget)
    lines = [
        f"paired evaluation: suite={report.suite or '(unspecified)'} cases={report.count}",
        f"  baseline : {report.baseline_label}  "
        f"{report.baseline_passes}/{report.count} passed  {report.baseline_tokens} tokens",
        f"  candidate: {report.candidate_label}  "
        f"{report.candidate_passes}/{report.count} passed  {report.candidate_tokens} tokens",
        f"  net passes: {report.net_passes:+d}; "
        f"bootstrap {percent}% CI [{report.confidence_low:+.3f}, {report.confidence_high:+.3f}] "
        f"(resamples={report.resamples}, seed={report.seed})",
        f"  token budget: {budget}",
        f"  decision: {report.decision.value} - {report.reason}",
        "",
        f"{'case':<32}{'base':<6}{'cand':<6}{'d':<3}{'tokens (base -> cand)':<24}evidence",
    ]
    for outcome in report.outcomes:
        label = f"{outcome.case.suite}/{outcome.case.case_id}"
        if outcome.case.condition:
            label += f"/{outcome.case.condition}"
        base = "pass" if outcome.baseline.objective_pass else "fail"
        cand = "pass" if outcome.candidate.objective_pass else "fail"
        tokens = f"{outcome.baseline.tokens} -> {outcome.candidate.tokens}"
        lines.append(
            f"{label:<32}{base:<6}{cand:<6}{outcome.delta:+d} {tokens:<22}"
            f"{outcome.candidate.evidence_path}"
        )
    return "\n".join(lines)


def save_report(report: PairedReport, out_dir: Path) -> Path:
    """Write ``summary.json`` and ``summary.txt`` for a report into ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / SUMMARY_JSON).write_text(
        json.dumps(report_payload(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / SUMMARY_TEXT).write_text(
        render_report(report) + "\n", encoding="utf-8", newline="\n"
    )
    return out_dir


__all__ = [
    "CaseOutcome",
    "Decision",
    "PairedReport",
    "bootstrap_interval",
    "candidate_outcomes",
    "evaluate",
    "paired_outcomes",
    "render_report",
    "report_payload",
    "save_report",
]
