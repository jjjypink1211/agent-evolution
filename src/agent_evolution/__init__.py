"""Offline harness evolution: propose snapshot edits, score paired episodes, accept or roll back."""

from agent_evolution.adapter import Adapter, CaseRef, EpisodeResult
from agent_evolution.edit import Edit, EditError, EditKind
from agent_evolution.paired import Decision, PairedReport, evaluate
from agent_evolution.proposer import (
    FailureReport,
    OpenAIChatModel,
    Proposal,
    ProposalError,
    Proposer,
    ProposerModel,
)
from agent_evolution.snapshot import Change, Snapshot, SnapshotError

__all__ = [
    "Adapter",
    "CaseRef",
    "Change",
    "Decision",
    "Edit",
    "EditError",
    "EditKind",
    "EpisodeResult",
    "FailureReport",
    "OpenAIChatModel",
    "PairedReport",
    "Proposal",
    "ProposalError",
    "Proposer",
    "ProposerModel",
    "Snapshot",
    "SnapshotError",
    "evaluate",
]
