"""Command line interface for the harness evolution system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from agent_evolution.snapshot import Change, ChangeKind, Snapshot

_MARKERS = {
    ChangeKind.ADDED: "+",
    ChangeKind.REMOVED: "-",
    ChangeKind.CHANGED: "~",
}
_MAX_SUMMARY = 120


def _configure_output() -> None:
    """Keep harness texts (which may be non-ASCII) printable on any console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _summarize(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    text = " ".join(str(value).split())
    if len(text) > _MAX_SUMMARY:
        return text[: _MAX_SUMMARY - 3] + "..."
    return text


def _format_change(change: Change) -> str:
    marker = _MARKERS[change.kind]
    if change.kind is ChangeKind.ADDED:
        return f"{marker} {change.key}: {_summarize(change.after)}"
    if change.kind is ChangeKind.REMOVED:
        return f"{marker} {change.key}: {_summarize(change.before)}"
    return (
        f"{marker} {change.key}: "
        f"{_summarize(change.before)} -> {_summarize(change.after)}"
    )


def _diff(before: Path, after: Path) -> int:
    changes = Snapshot.load(before).diff(Snapshot.load(after))
    if not changes:
        print("no differences")
        return 0
    for change in changes:
        print(_format_change(change))
    return 1


def _show(path: Path) -> int:
    snapshot = Snapshot.load(path)
    print(f"schema_version: {snapshot.schema_version}")
    print(f"features: {', '.join(snapshot.features) or '(none)'}")
    print(f"system_prompt: {snapshot.system_prompt}")
    for name, text in sorted(snapshot.status_sections.items()):
        print(f"status[{name}]: {text}")
    for name, text in sorted(snapshot.tool_descriptions.items()):
        print(f"tool[{name}]: {text}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _configure_output()
    parser = argparse.ArgumentParser(prog="agent-evolution", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = commands.add_parser("snapshot", help="inspect harness snapshots")
    snapshot_commands = snapshot_parser.add_subparsers(dest="snapshot_command", required=True)

    diff_parser = snapshot_commands.add_parser("diff", help="show field-level differences")
    diff_parser.add_argument("before", type=Path)
    diff_parser.add_argument("after", type=Path)

    show_parser = snapshot_commands.add_parser("show", help="print a snapshot")
    show_parser.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    if args.snapshot_command == "diff":
        return _diff(args.before, args.after)
    return _show(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
