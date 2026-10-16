"""A single, typed harness edit and how it applies to a snapshot.

The proposer emits exactly one :class:`Edit`. Keeping the edit typed (rather than
a patch string) makes "one edit" checkable, keeps the loop deterministic, and lets
the change be described both to a human and back to the model.

A ``FEATURE`` edit turns one harness feature on or off in the snapshot, which is a
legitimate edit here; what it changes is the target's business - a target enables
the intersection of the snapshot's features with the arm's protocol condition list,
so flipping a feature the arm does not list is a no-op (ADR-0006).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from agent_evolution.snapshot import Snapshot, SnapshotError
from agent_evolution.text import clip

ON = "on"
OFF = "off"

_PREVIEW = 60


class EditError(ValueError):
    """Raised when an edit is malformed or changes nothing on a snapshot."""


class EditKind(StrEnum):
    """The four surfaces a single edit may touch."""

    FEATURE = "feature"
    SYSTEM_PROMPT = "system_prompt"
    STATUS_SECTION = "status_section"
    TOOL_DESCRIPTION = "tool_description"


_GROUP = {
    EditKind.STATUS_SECTION: "status",
    EditKind.TOOL_DESCRIPTION: "tools",
}


@dataclass(frozen=True)
class Edit:
    """One declarative change to a snapshot, plus the rationale for making it.

    For ``FEATURE`` the ``value`` is ``"on"`` or ``"off"`` (the feature is named by
    ``key``); for the text kinds ``value`` is the replacement text and ``key`` names
    the section/tool (empty for ``SYSTEM_PROMPT``).
    """

    kind: EditKind
    key: str = ""
    value: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", EditKind(self.kind))
        if self.kind is EditKind.SYSTEM_PROMPT:
            object.__setattr__(self, "key", "")
        elif not self.key:
            raise EditError(f"{self.kind.value} edit needs a key")
        if self.kind is EditKind.FEATURE and self.value not in (ON, OFF):
            raise EditError(f"feature edit value must be {ON!r} or {OFF!r}, got {self.value!r}")

    def apply(self, snapshot: Snapshot) -> Snapshot:
        """Return ``snapshot`` with exactly this edit applied.

        Raises :class:`EditError` when the edit would change nothing (an edit that
        is already in effect is a mistake, not a no-op, so it never yields a
        candidate) or when its key is not a valid snapshot key.
        """
        try:
            return self._apply(snapshot)
        except SnapshotError as error:
            raise EditError(f"{self.describe()}: {error}") from error

    def _apply(self, snapshot: Snapshot) -> Snapshot:
        if self.kind is EditKind.SYSTEM_PROMPT:
            candidate = replace(snapshot, system_prompt=self.value)
        elif self.kind is EditKind.FEATURE:
            present = self.key in snapshot.features
            if self.value == ON and present:
                raise EditError(f"feature {self.key!r} is already enabled")
            if self.value == OFF and not present:
                raise EditError(f"feature {self.key!r} is already disabled")
            if self.value == ON:
                candidate = replace(snapshot, features=(*snapshot.features, self.key))
            else:
                candidate = replace(
                    snapshot, features=tuple(name for name in snapshot.features if name != self.key)
                )
        elif self.kind is EditKind.STATUS_SECTION:
            sections = dict(snapshot.status_sections)
            sections[self.key] = self.value
            candidate = replace(snapshot, status_sections=sections)
        else:
            descriptions = dict(snapshot.tool_descriptions)
            descriptions[self.key] = self.value
            candidate = replace(snapshot, tool_descriptions=descriptions)
        if not snapshot.diff(candidate):
            raise EditError(f"edit changes nothing: {self.describe()}")
        return candidate

    def describe(self) -> str:
        """A one-line, human-readable form of the edit."""
        if self.kind is EditKind.SYSTEM_PROMPT:
            return f"system_prompt := {clip(self.value, _PREVIEW)}"
        if self.kind is EditKind.FEATURE:
            return f"feature[{self.key}] := {self.value}"
        return f"{_GROUP[self.kind]}[{self.key}] := {clip(self.value, _PREVIEW)}"

    def to_payload(self) -> dict[str, str]:
        """The JSON-serialisable shape the model emits and the loop records."""
        return {
            "kind": self.kind.value,
            "key": self.key,
            "value": self.value,
            "reason": self.reason,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "Edit":
        """Build an edit from a decoded JSON object, rejecting anything malformed."""
        if not isinstance(payload, dict):
            raise EditError(f"edit must be a JSON object, got {type(payload).__name__}")
        if "kind" not in payload:
            raise EditError("edit is missing 'kind'")
        try:
            kind = EditKind(payload["kind"])
        except ValueError as error:
            raise EditError(f"unknown edit kind {payload['kind']!r}") from error
        key, value, reason = payload.get("key", ""), payload.get("value", ""), payload.get("reason", "")
        for name, text in (("key", key), ("value", value), ("reason", reason)):
            if not isinstance(text, str):
                raise EditError(f"edit {name!r} must be a string")
        return cls(kind=kind, key=key, value=value, reason=reason)


__all__ = [
    "Edit",
    "EditError",
    "EditKind",
    "OFF",
    "ON",
]
