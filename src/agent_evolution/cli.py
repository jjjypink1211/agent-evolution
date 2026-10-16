"""Command line interface for the harness evolution system."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from agent_evolution.adapter import Adapter
from agent_evolution.paired import (
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    Decision,
    evaluate,
    render_report,
    save_report,
)
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


API_KEY_ENV_VARS = ("MOONSHOT_API_KEY", "KIMI_API_KEY")


def _default_out_dir(args: argparse.Namespace) -> Path:
    return Path("runs") / "paired" / f"{args.suite}__{args.baseline.name}__vs__{args.candidate.name}"


def _build_adapter(args: argparse.Namespace, out_dir: Path) -> Adapter:
    from openai import OpenAI

    from agent_evolution.system_hint_adapter import PROTOCOL_NAME, SystemHintAdapter
    from agent_evolution.target_harness import resolve_target_dir

    key = next((os.getenv(name) for name in API_KEY_ENV_VARS if os.getenv(name)), None)
    if not key:
        raise SystemExit(f"one of {', '.join(API_KEY_ENV_VARS)} is required to run evaluate")
    target_dir = Path(args.target_dir) if args.target_dir else resolve_target_dir()
    protocol = json.loads((target_dir / PROTOCOL_NAME).read_text(encoding="utf-8-sig"))
    client = OpenAI(api_key=key, base_url=protocol["provider"]["base_url"])
    return SystemHintAdapter(client=client, run_root=out_dir, target_dir=target_dir)


def _evaluate(args: argparse.Namespace) -> int:
    out_dir = args.out if args.out is not None else _default_out_dir(args)
    adapter = _build_adapter(args, out_dir)
    report = evaluate(
        adapter,
        baseline=Snapshot.load(args.baseline),
        candidate=Snapshot.load(args.candidate),
        cases=adapter.cases_for(args.suite),
        suite=args.suite,
        baseline_label=str(args.baseline),
        candidate_label=str(args.candidate),
        token_budget=args.token_budget,
        resamples=args.resamples,
        seed=args.seed,
    )
    save_report(report, out_dir)
    print(render_report(report))
    print(f"saved: {out_dir / 'summary.json'}")
    return 0 if report.decision is Decision.ACCEPT else 1


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

    evaluate_parser = commands.add_parser(
        "evaluate", help="paired-evaluate a candidate snapshot against a baseline"
    )
    evaluate_parser.add_argument("--suite", required=True, help="protocol suite to run")
    evaluate_parser.add_argument("--baseline", type=Path, required=True)
    evaluate_parser.add_argument("--candidate", type=Path, required=True)
    evaluate_parser.add_argument("--out", type=Path, default=None, help="evidence and report dir")
    evaluate_parser.add_argument("--token-budget", type=int, default=None)
    evaluate_parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    evaluate_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    evaluate_parser.add_argument("--target-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "evaluate":
        return _evaluate(args)
    if args.snapshot_command == "diff":
        return _diff(args.before, args.after)
    return _show(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
