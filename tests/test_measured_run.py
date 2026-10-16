"""Pins the measured run so the README's claim survives a clean clone.

``runs/`` is gitignored, so ``runs/evolve-kimi-digest-fix`` cannot ship with the
repo. The numbers it produced are copied into ``tests/fixtures/`` (from that run's
``rounds/NN/summary.json``) and asserted here: the loop accepted an edit on round 1,
and the corrected accounting counts only the episodes that actually ran (ADR-0010).
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "evolve-kimi-digest-fix.json"


def measured_run() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_round_one_accepted_a_total_improvement() -> None:
    first = measured_run()["rounds"][0]

    assert first["decision"] == "accept"
    assert (first["baseline_passes"], first["candidate_passes"]) == (0, 5)
    assert first["net_passes"] == 5
    assert first["confidence_interval"][0] > 0


def test_every_other_round_rolled_back_without_a_strict_improvement() -> None:
    for round_ in measured_run()["rounds"][1:]:
        assert round_["decision"] == "rollback"
        assert round_["net_passes"] <= 0
        assert round_["confidence_interval"][0] <= 0


def test_the_reused_baselines_are_the_accepted_candidate() -> None:
    rounds = measured_run()["rounds"]

    assert rounds[0]["candidate_fingerprint"] == rounds[1]["baseline_fingerprint"]
    assert rounds[1]["baseline_fingerprint"] == rounds[2]["baseline_fingerprint"]
    assert [round_["baseline_reused"] for round_ in rounds] == [False, True, True]


def test_tokens_used_counts_only_the_episodes_that_ran() -> None:
    data = measured_run()

    spent = sum(
        (0 if round_["baseline_reused"] else round_["baseline_tokens"])
        + round_["candidate_tokens"]
        for round_ in data["rounds"]
    )
    assert spent == data["tokens_used_corrected"]

    evaluated = sum(
        round_["baseline_tokens"] + round_["candidate_tokens"] for round_ in data["rounds"]
    )
    assert evaluated == data["tokens_used_reported_before_fix"]
