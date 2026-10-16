"""Concrete adapter that drives the refactored system-hint target loop.

This is the only module that knows how to get an :class:`EpisodeResult` out of
``ai-agent-book``'s ``run_experiment_2_8.py``. Upper layers import
:mod:`agent_evolution.adapter`, never the coupling in here.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.snapshot import Snapshot
from agent_evolution.target_harness import TARGET_MODULE_NAME, load_module, resolve_target_dir
from agent_evolution.text import clip

PROTOCOL_NAME = "experiment_protocol.json"

DIGEST_TURN_LIMIT = 24
DIGEST_CHARS = 400

# Which env vars may hold the key for which provider, mirroring the target's own
# ``agentbook.providers.registry``. The run's credential must come from the
# provider the protocol names, never from whichever key happens to be set first.
PROVIDER_KEY_VARS: dict[str, tuple[str, ...]] = {
    "dashscope": ("DASHSCOPE_API_KEY",),
    "siliconflow": ("SILICONFLOW_API_KEY",),
    "doubao": ("ARK_API_KEY",),
    "kimi": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "zhipu": ("ZHIPU_API_KEY",),
    "krill": ("KRILL_API_KEY",),
    "atlascloud": ("ATLASCLOUD_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "ollama": ("OLLAMA_API_KEY",),
}

# Names the chapters use interchangeably, mapped to the canonical ones above.
PROVIDER_ALIASES: dict[str, str] = {
    "moonshot": "kimi",
    "ark": "doubao",
    "google": "gemini",
    "qwen": "dashscope",
    "bailian": "dashscope",
}


def provider_key_vars(provider: str) -> tuple[str, ...]:
    """Return the env vars that may hold ``provider``'s key, most specific first.

    An alias resolves to its canonical provider; an unknown provider yields an
    empty tuple so callers fail loudly rather than reaching for an unrelated key.
    """
    name = provider.strip().lower()
    return PROVIDER_KEY_VARS.get(PROVIDER_ALIASES.get(name, name), ())


def resolve_api_key(provider: str, env: Mapping[str, str] | None = None) -> str | None:
    """Return the first non-blank key configured for ``provider``, or ``None``."""
    source = os.environ if env is None else env
    for name in provider_key_vars(provider):
        value = source.get(name, "").strip()
        if value:
            return value
    return None


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
        run_id = self._run_id(case, condition)
        episode_dir = self.run_root / snapshot.fingerprint() / run_id
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

    def episode_dir(self, snapshot: Snapshot, case: CaseRef) -> Path:
        """Where ``case``'s evidence lives for ``snapshot``.

        Keyed by the snapshot's fingerprint so the baseline and the candidate of a
        paired run never overwrite (or resume) each other's episodes.
        """
        condition = case.condition or enabled_condition(self._protocol, case.suite)
        return self.run_root / snapshot.fingerprint() / self._run_id(case, condition)

    @staticmethod
    def _run_id(case: CaseRef, condition: str) -> str:
        return f"{case.suite}__{case.case_id}__{condition}"

    def failure_digest(self, snapshot: Snapshot, case: CaseRef, result: EpisodeResult) -> str:
        """Explain why an episode failed, from its own evidence file."""
        evidence = json.loads(Path(result.evidence_path).read_text(encoding="utf-8"))
        failed = sorted(name for name, ok in result.component_scores.items() if not ok)
        lines = [
            f"case {case.suite}/{case.case_id} (condition {evidence.get('condition', case.condition)})",
            f"objective_pass={result.objective_pass} failed_gates={failed or 'none'}",
            f"complete={evidence.get('complete')} termination={evidence.get('termination')} "
            f"llm_turns={result.llm_turns} tokens={result.tokens}",
            "-- transcript --",
        ]
        for message in evidence.get("messages", [])[-DIGEST_TURN_LIMIT:]:
            lines.append(f"{message.get('role')}: {clip(message.get('content'), DIGEST_CHARS)}")
        failed_tools = [event for event in evidence.get("tool_events", []) if not event.get("ok")]
        if failed_tools:
            lines.append("-- failed tools --")
            for event in failed_tools:
                lines.append(
                    f"{event.get('name')}{event.get('arguments')}: "
                    f"{clip(event.get('content'), DIGEST_CHARS)}"
                )
        return "\n".join(lines)

    def suites(self) -> tuple[str, ...]:
        """Return every suite the protocol defines, in declaration order."""
        return tuple(self._protocol["cases"].keys())

    def cases_for(self, suite: str) -> tuple[CaseRef, ...]:
        """Return the protocol's cases for ``suite``, each with its default condition."""
        return tuple(CaseRef(suite, protocol_case["id"]) for protocol_case in self._suite_cases(suite))

    def _suite_cases(self, suite: str) -> list[dict[str, Any]]:
        cases = self._protocol["cases"].get(suite)
        if cases is None:
            raise KeyError(f"unknown suite {suite!r}")
        return cases

    def _resolve_case(self, case: CaseRef) -> tuple[int, dict[str, Any]]:
        for index, protocol_case in enumerate(self._suite_cases(case.suite)):
            if protocol_case["id"] == case.case_id:
                return index, protocol_case
        raise KeyError(f"unknown case {case.suite}/{case.case_id}")


__all__ = [
    "PROVIDER_ALIASES",
    "PROVIDER_KEY_VARS",
    "SystemHintAdapter",
    "enabled_condition",
    "provider_key_vars",
    "resolve_api_key",
]
