"""The adapter seam: run one ``(snapshot, case)`` episode into an ``EpisodeResult``.

Upper layers (the paired evaluator, the proposer, the evolution loop) depend only
on this module: the :class:`Adapter` protocol, :class:`CaseRef` and
:class:`EpisodeResult`. They never import a target loop's internals. Concrete
adapters live beside this module and are wired in from the outside.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

from agent_evolution.snapshot import Snapshot


@dataclass(frozen=True)
class CaseRef:
    """An opaque handle to one case of a target's protocol.

    ``condition`` defaults to the target's enabled (intervention) condition for
    the suite; pass it explicitly to score a control arm instead.
    """

    suite: str
    case_id: str
    condition: str | None = None


@dataclass(frozen=True)
class EpisodeResult:
    """The normalised outcome of a single episode.

    This is the only shape upper layers read; everything target-specific stays
    behind the adapter.
    """

    objective_pass: bool
    component_scores: Mapping[str, bool]
    llm_turns: int
    tokens: int
    evidence_path: Path


@runtime_checkable
class Adapter(Protocol):
    """Runs one ``(snapshot, case)`` pair into an :class:`EpisodeResult`."""

    def run(self, snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        """Run ``case`` against ``snapshot`` and return its normalised result."""
        ...

    def cases_for(self, suite: str) -> Sequence[CaseRef]:
        """Return the cases that make up ``suite``."""
        ...


__all__ = [
    "Adapter",
    "CaseRef",
    "EpisodeResult",
]
