"""The adapter seam: run one ``(snapshot, case)`` episode into an ``EpisodeResult``.

Upper layers (the paired evaluator, the proposer, the evolution loop) depend only
on this module: the :class:`Adapter` protocol, :class:`CaseRef` and
:class:`EpisodeResult`. They never import a target loop's internals. Concrete
adapters live beside this module and are wired in from the outside.

The protocol has four parts: list the target's suites (:meth:`Adapter.suites`),
enumerate a suite's cases (:meth:`Adapter.cases_for`), run one episode
(:meth:`Adapter.run`), and explain a failure in prose
(:meth:`Adapter.failure_digest`) so the proposer can stay target-agnostic.
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

    def suites(self) -> Sequence[str]:
        """Return every suite the target defines, in a stable order.

        The loop uses this to expand ``--suite all`` into a full run without
        knowing a target's protocol itself.
        """
        ...

    def cases_for(self, suite: str) -> Sequence[CaseRef]:
        """Return the cases that make up ``suite``."""
        ...

    def failure_digest(self, snapshot: Snapshot, case: CaseRef, result: EpisodeResult) -> str:
        """Render a compact, target-specific digest of why ``result`` failed.

        Only the target knows how to read its own trajectory and gate detail, so it
        formats the failure here; the proposer consumes the text and never the
        target's evidence format.
        """
        ...


__all__ = [
    "Adapter",
    "CaseRef",
    "EpisodeResult",
]
