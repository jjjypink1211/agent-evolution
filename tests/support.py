"""Shared builders for the evaluator, proposer, and loop tests."""

from __future__ import annotations

import json
from pathlib import Path

from agent_evolution.adapter import CaseRef, EpisodeResult

from scripted_model import ScriptedModel


def combined_cases(count: int) -> list[CaseRef]:
    """The first ``count`` cases of the ``combined`` suite."""
    return [CaseRef("combined", f"all-{index:02d}") for index in range(1, count + 1)]


def episode(passed: bool, *, tokens: int = 5, evidence: str = "episode.json") -> EpisodeResult:
    """A minimal :class:`EpisodeResult` for a scripted responder."""
    return EpisodeResult(
        objective_pass=passed,
        component_scores={"gate": passed},
        llm_turns=1,
        tokens=tokens,
        evidence_path=Path(evidence),
    )


def system_prompt_edits(*values: str) -> ScriptedModel:
    """A scripted proposer model that proposes one ``system_prompt`` edit per value."""
    return ScriptedModel(
        replies=[
            json.dumps(
                {"kind": "system_prompt", "key": "", "value": value, "reason": f"try {value}"}
            )
            for value in values
        ]
    )
