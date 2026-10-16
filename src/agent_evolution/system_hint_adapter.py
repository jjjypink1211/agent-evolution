"""Concrete adapter that drives the refactored system-hint target loop.

This is the only module that knows how to get an :class:`EpisodeResult` out of
``ai-agent-book``'s ``run_experiment_2_8.py``. Upper layers import
:mod:`agent_evolution.adapter`, never the coupling in here.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.snapshot import Snapshot
from agent_evolution.target_harness import TARGET_MODULE_NAME, load_module, resolve_target_dir

PROTOCOL_NAME = "experiment_protocol.json"


def enabled_condition(protocol: Mapping[str, Any], suite: str) -> str:
    """Return the intervention condition a suite's contrast turns on."""
    for contrast in protocol["contrasts"]:
        if contrast["suite"] == suite:
            return contrast["enabled"]
    return suite


class SystemHintAdapter:
    """Run one system-hint campaign case for a given harness snapshot."""

    def __init__(
        self,
        client: Any,
        run_root: Path | None = None,
        target_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.target_dir = Path(target_dir) if target_dir is not None else resolve_target_dir()
        module_path = self.target_dir / TARGET_MODULE_NAME
        if not module_path.is_file():
            raise FileNotFoundError(f"system-hint target not found at {module_path}")
        self._module = load_module(module_path)
        self._protocol_bytes = (self.target_dir / PROTOCOL_NAME).read_bytes()
        self._protocol = json.loads(self._protocol_bytes)
        self._protocol_hash = hashlib.sha256(self._protocol_bytes).hexdigest()
        self._temp_root: tempfile.TemporaryDirectory | None = None
        if run_root is None:
            self._temp_root = tempfile.TemporaryDirectory(prefix="agent-evolution-episodes-")
            run_root = self._temp_root.name
        self.run_root = Path(run_root)

    def run(self, snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        """Materialise ``snapshot``, run ``case`` once, and normalise the outcome."""
        index, protocol_case = self._resolve_case(case)
        condition = case.condition or enabled_condition(self._protocol, case.suite)
        order = self._module.condition_order(case.suite, index)
        if condition not in order:
            raise ValueError(f"condition {condition!r} is not in {case.suite}'s arm order {order}")
        run_id = f"{case.suite}__{case.case_id}__{condition}"
        episode_dir = self.run_root / run_id
        episode_dir.mkdir(parents=True, exist_ok=True)
        harness_dir = episode_dir / self._module.HARNESS_DIR_NAME
        snapshot.save(harness_dir)
        self._module.set_harness(harness_dir)
        evidence = self._module.run_one(
            self.client,
            self._protocol,
            self._protocol_hash,
            episode_dir,
            case.suite,
            protocol_case,
            condition,
            order,
            order.index(condition),
        )
        return EpisodeResult(
            objective_pass=bool(evidence["objective_pass"]),
            component_scores=dict(evidence["component_scores"]),
            llm_turns=int(evidence["llm_turns"]),
            tokens=int(evidence["usage"]["total_tokens"]),
            evidence_path=episode_dir / "cases" / f"{run_id}.json",
        )

    def _resolve_case(self, case: CaseRef) -> tuple[int, dict[str, Any]]:
        cases = self._protocol["cases"].get(case.suite)
        if cases is None:
            raise KeyError(f"unknown suite {case.suite!r}")
        for index, protocol_case in enumerate(cases):
            if protocol_case["id"] == case.case_id:
                return index, protocol_case
        raise KeyError(f"unknown case {case.suite}/{case.case_id}")


__all__ = [
    "SystemHintAdapter",
    "enabled_condition",
]
