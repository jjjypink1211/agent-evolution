"""Offline harness evolution: propose snapshot edits, score paired episodes, accept or roll back."""

from agent_evolution.adapter import Adapter, CaseRef, EpisodeResult
from agent_evolution.paired import Decision, PairedReport, evaluate
from agent_evolution.snapshot import Change, Snapshot, SnapshotError

__all__ = [
    "Adapter",
    "CaseRef",
    "Change",
    "Decision",
    "EpisodeResult",
    "PairedReport",
    "Snapshot",
    "SnapshotError",
    "evaluate",
]
