"""Offline harness evolution: propose snapshot edits, score paired episodes, accept or roll back."""

from agent_evolution.snapshot import Change, Snapshot, SnapshotError

__all__ = ["Change", "Snapshot", "SnapshotError"]
