"""Declarative harness snapshots: load, save, and diff.

A snapshot is a directory holding a declarative, diffable representation of an
agent loop's harness: the system-prompt text, the ``<agent_status>`` section
templates, the tool description texts, and the catalogue of known ``features``.
Loop control flow is deliberately out of scope, and which features a run enables
remains the target protocol's decision, not the snapshot's.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator, Mapping

SCHEMA_VERSION = 1

METADATA_NAME = "snapshot.json"
SYSTEM_PROMPT_NAME = "system_prompt.txt"
STATUS_DIR = "status"
TOOLS_DIR = "tools"

RENDERED_PLACEHOLDER = "{rendered}"
_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")


class SnapshotError(ValueError):
    """Raised when a snapshot on disk is malformed."""


class ChangeKind(StrEnum):
    """How one field differs between two snapshots."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass(frozen=True)
class Change:
    """One field-level difference between two snapshots."""

    kind: ChangeKind
    key: str
    before: Any = None
    after: Any = None


def _check_key(key: str, group: str) -> None:
    if not _KEY_PATTERN.match(key):
        raise SnapshotError(f"{group} key {key!r} must match [a-z0-9_]+")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").removesuffix("\n")


def _load_group(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        path.stem: _read_text(path)
        for path in sorted(directory.glob("*.txt"))
    }


def _diff_group(group: str, before: Mapping[str, str], after: Mapping[str, str]) -> Iterator[Change]:
    for key in sorted(set(before) | set(after)):
        if key not in before:
            yield Change(ChangeKind.ADDED, f"{group}[{key}]", None, after[key])
        elif key not in after:
            yield Change(ChangeKind.REMOVED, f"{group}[{key}]", before[key], None)
        elif before[key] != after[key]:
            yield Change(ChangeKind.CHANGED, f"{group}[{key}]", before[key], after[key])


@dataclass(frozen=True)
class Snapshot:
    """The mutable harness surface of an agent loop."""

    features: tuple[str, ...] = ()
    system_prompt: str = ""
    status_sections: Mapping[str, str] = field(default_factory=dict)
    tool_descriptions: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", tuple(self.features))
        object.__setattr__(self, "status_sections", dict(self.status_sections))
        object.__setattr__(self, "tool_descriptions", dict(self.tool_descriptions))
        for key in self.status_sections:
            _check_key(key, STATUS_DIR)
        for key in self.tool_descriptions:
            _check_key(key, TOOLS_DIR)

    def render_status_section(self, feature: str, rendered: str) -> str:
        """Render one ``<agent_status>`` section template with its dynamic tail."""
        return self.status_sections[feature].format(rendered=rendered)

    def fingerprint(self) -> str:
        """A stable content hash of the harness surface, for evidence isolation."""
        payload = json.dumps(
            {
                "schema_version": self.schema_version,
                "features": list(self.features),
                "system_prompt": self.system_prompt,
                "status_sections": dict(sorted(self.status_sections.items())),
                "tool_descriptions": dict(sorted(self.tool_descriptions.items())),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def save(self, root: Path) -> None:
        """Write this snapshot to a directory, replacing any stale contents."""
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        metadata = {"schema_version": self.schema_version, "features": list(self.features)}
        (root / METADATA_NAME).write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _write_text(root / SYSTEM_PROMPT_NAME, self.system_prompt)
        for name, mapping in ((STATUS_DIR, self.status_sections), (TOOLS_DIR, self.tool_descriptions)):
            directory = root / name
            if directory.is_dir():
                for stale in directory.glob("*.txt"):
                    stale.unlink()
            else:
                directory.mkdir(parents=True)
            for key, text in sorted(mapping.items()):
                _write_text(directory / f"{key}.txt", text)

    @classmethod
    def load(cls, root: Path) -> "Snapshot":
        """Read a snapshot directory back into a :class:`Snapshot`."""
        root = Path(root)
        metadata_path = root / METADATA_NAME
        if not metadata_path.is_file():
            raise SnapshotError(f"missing {METADATA_NAME} in {root}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        features = metadata.get("features")
        if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
            raise SnapshotError("features must be a list of strings")
        system_prompt_path = root / SYSTEM_PROMPT_NAME
        return cls(
            features=tuple(features),
            system_prompt=_read_text(system_prompt_path) if system_prompt_path.is_file() else "",
            status_sections=_load_group(root / STATUS_DIR),
            tool_descriptions=_load_group(root / TOOLS_DIR),
            schema_version=int(metadata.get("schema_version", SCHEMA_VERSION)),
        )

    def diff(self, other: "Snapshot") -> tuple[Change, ...]:
        """Return the field-level differences from this snapshot to ``other``."""
        changes: list[Change] = []
        if self.schema_version != other.schema_version:
            changes.append(
                Change(ChangeKind.CHANGED, "schema_version", self.schema_version, other.schema_version)
            )
        if self.features != other.features:
            changes.append(
                Change(ChangeKind.CHANGED, "features", list(self.features), list(other.features))
            )
        if self.system_prompt != other.system_prompt:
            changes.append(
                Change(ChangeKind.CHANGED, "system_prompt", self.system_prompt, other.system_prompt)
            )
        changes.extend(_diff_group(STATUS_DIR, self.status_sections, other.status_sections))
        changes.extend(_diff_group(TOOLS_DIR, self.tool_descriptions, other.tool_descriptions))
        changes.sort(key=lambda change: (change.key, change.kind))
        return tuple(changes)


__all__ = [
    "Change",
    "ChangeKind",
    "RENDERED_PLACEHOLDER",
    "SCHEMA_VERSION",
    "Snapshot",
    "SnapshotError",
    "STATUS_DIR",
    "TOOLS_DIR",
]
