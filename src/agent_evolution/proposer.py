"""The LLM proposer: exactly one harness edit per round, plus its rationale.

The proposer reads the current snapshot and a digest of the failing episodes and
asks a chat model for one :class:`~agent_evolution.edit.Edit`. It depends only on
the narrow :class:`ProposerModel` protocol, so tests drive it with a scripted
model and never touch the network. The endpoint is configured independently of the
target loop's own provider.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.edit import OFF, ON, Edit, EditError
from agent_evolution.snapshot import Snapshot

ENV_BASE_URL = "EVOLVER_BASE_URL"
ENV_API_KEY = "EVOLVER_API_KEY"
ENV_MODEL = "EVOLVER_MODEL"

DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_MODEL = "kimi-k3"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_REPAIRS = 1

_REPLY_CLIP = 1000

DEFAULT_INSTRUCTIONS = f"""You tune the harness of an agent loop by proposing exactly one edit per round.

An edit is a JSON object with these fields:
  "kind":  one of "feature", "system_prompt", "status_section", "tool_description"
  "key":   the feature / status section / tool name (empty for "system_prompt")
  "value": the replacement text, or "{ON}"/"{OFF}" for a "feature" edit
  "reason": one or two sentences explaining why this edit should help

Rules:
- Propose exactly one edit that changes exactly one thing.
- A "feature" edit turns one harness feature {ON} or {OFF}. A feature the arm's
  condition list does not include has no effect on the episode and will be rolled back.
- Do not re-apply an edit that is already in effect.
- Reply with only a JSON object of the form {{"edit": {{ ... }}}}: no prose, no code fences.
"""


class ProposalError(RuntimeError):
    """Raised when no usable proposal could be produced."""


@dataclass(frozen=True)
class FailureReport:
    """One failing episode, with the target's own digest of why it failed."""

    case: CaseRef
    result: EpisodeResult
    digest: str


@runtime_checkable
class ProposerModel(Protocol):
    """The minimal chat interface the proposer needs, easily faked in tests."""

    def complete(self, system: str, user: str) -> str:
        """Return the model's reply for one system+user exchange."""
        ...


@dataclass(frozen=True)
class Proposal:
    """A validated edit, the model's raw reply, and how many attempts it took."""

    edit: Edit
    raw: str
    attempts: int

    def candidate(self, snapshot: Snapshot) -> Snapshot:
        """Apply the edit to ``snapshot`` to get the candidate harness."""
        return self.edit.apply(snapshot)


@dataclass
class OpenAIChatModel:
    """A :class:`ProposerModel` backed by an OpenAI-compatible chat endpoint."""

    model: str = DEFAULT_MODEL
    client: Any = None
    temperature: float = DEFAULT_TEMPERATURE

    def complete(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "OpenAIChatModel":
        """Build a model from ``EVOLVER_API_KEY``/``EVOLVER_BASE_URL``/``EVOLVER_MODEL``."""
        source = os.environ if env is None else env
        api_key = source.get(ENV_API_KEY)
        if not api_key:
            raise ProposalError(f"{ENV_API_KEY} is required to call the proposer model")
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=source.get(ENV_BASE_URL, DEFAULT_BASE_URL))
        return cls(model=source.get(ENV_MODEL, DEFAULT_MODEL), client=client)


@dataclass
class Proposer:
    """Ask a model for one snapshot edit, retrying once on an unusable reply."""

    model: ProposerModel
    instructions: str = DEFAULT_INSTRUCTIONS
    max_repairs: int = DEFAULT_MAX_REPAIRS

    def propose(self, snapshot: Snapshot, failures: Sequence[FailureReport]) -> Proposal:
        """Return one applicable, reasoned edit for ``snapshot``, or raise :class:`ProposalError`.

        The edit is validated against ``snapshot`` here, so a returned proposal is
        always applicable; a reply that will not parse, carries no rationale, or
        will not apply gets at most ``max_repairs`` corrective retries.
        """
        request = render_request(snapshot, failures)
        prompt = request
        last_error: Exception | None = None
        for attempt in range(1, self.max_repairs + 2):
            raw = self.model.complete(self.instructions, prompt)
            try:
                edit = _decode_edit(raw)
                if not edit.reason.strip():
                    raise EditError("edit is missing the required 'reason'")
                edit.apply(snapshot)
            except ValueError as error:
                last_error = error
                prompt = _repair_prompt(request, raw, error)
                continue
            return Proposal(edit=edit, raw=raw, attempts=attempt)
        raise ProposalError(
            f"model returned no usable edit after {self.max_repairs + 1} attempt(s): {last_error}"
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Proposer":
        """A proposer wired to the independently-configured ``EVOLVER_*`` endpoint."""
        return cls(model=OpenAIChatModel.from_env(env))


def snapshot_text(snapshot: Snapshot) -> str:
    """Render the whole harness surface as text for the model to read."""
    lines = [
        f"features: {list(snapshot.features)}",
        "system_prompt:",
        snapshot.system_prompt,
        "status sections:",
    ]
    lines.extend(f"  {name}: {text}" for name, text in sorted(snapshot.status_sections.items()))
    lines.append("tool descriptions:")
    lines.extend(f"  {name}: {text}" for name, text in sorted(snapshot.tool_descriptions.items()))
    return "\n".join(lines)


def render_request(snapshot: Snapshot, failures: Sequence[FailureReport]) -> str:
    """The user turn: the current harness plus every failing episode's digest."""
    lines = ["# Current harness", snapshot_text(snapshot), "", "# Failing episodes"]
    if not failures:
        lines.append("(none)")
    for report in failures:
        lines.append(f"## {report.case.suite}/{report.case.case_id}")
        lines.append(report.digest)
    lines.append("")
    lines.append("Propose exactly one edit as a JSON object.")
    return "\n".join(lines)


def _repair_prompt(request: str, raw: str, error: Exception) -> str:
    return (
        f"{request}\n\n"
        f"Your previous reply was rejected: {raw[:_REPLY_CLIP]}\n"
        f"Problem: {error}\n"
        "Reply again with only the JSON edit object."
    )


def _decode_edit(raw: str) -> Edit:
    """Read the model's reply as an edit.

    The documented reply is ``{"edit": { ... }}``; a bare ``{ ... }`` edit object is
    accepted too, and one layer of ``` fence is stripped before parsing.
    """
    payload = _load_json(raw)
    if isinstance(payload, dict) and "edit" in payload:
        payload = payload["edit"]
    return Edit.from_payload(payload)


def _load_json(text: str) -> Any:
    stripped = text.strip()
    candidates = [stripped]
    if stripped.startswith("```") and "\n" in stripped:
        candidates.append(stripped.split("\n", 1)[1].rsplit("```", 1)[0])
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        if not candidate.strip():
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as error:
            last_error = error
    raise last_error or ValueError("model reply was empty")


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_INSTRUCTIONS",
    "DEFAULT_MODEL",
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MODEL",
    "FailureReport",
    "OpenAIChatModel",
    "Proposal",
    "ProposalError",
    "Proposer",
    "ProposerModel",
    "render_request",
    "snapshot_text",
]
