"""A network-free test double implementing the :class:`Adapter` contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.snapshot import Snapshot


def _always_passes(snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
    return EpisodeResult(
        objective_pass=True,
        component_scores={},
        llm_turns=1,
        tokens=0,
        evidence_path=Path(f"{case.suite}__{case.case_id}__fake.json"),
    )


@dataclass
class FakeAdapter:
    """Record the calls it receives and return scripted results, with no network."""

    responder: Callable[[Snapshot, CaseRef], EpisodeResult] = _always_passes
    cases: tuple[CaseRef, ...] = ()
    calls: list[tuple[Snapshot, CaseRef]] = field(default_factory=list)

    def run(self, snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        self.calls.append((snapshot, case))
        return self.responder(snapshot, case)

    def cases_for(self, suite: str) -> tuple[CaseRef, ...]:
        return tuple(case for case in self.cases if case.suite == suite)
