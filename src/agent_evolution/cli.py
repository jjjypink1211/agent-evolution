"""Command line interface for the harness evolution system."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from agent_evolution.adapter import Adapter
from agent_evolution.evolve import (
    DEFAULT_MAX_FAILURES,
    DEFAULT_MAX_ROLLBACKS,
    DEFAULT_ROUNDS,
    HISTORY_JSON,
    RoundRecord,
    render_history,
    run_evolution,
    save_run,
)
from agent_evolution.paired import (
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    Decision,
    evaluate,
    render_report,
    save_report,
)
from agent_evolution.proposer import Proposer
from agent_evolution.snapshot import Change, ChangeKind, Snapshot

DEFAULT_SUITE = "combined"

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


def _default_out_dir(args: argparse.Namespace) -> Path:
    return Path("runs") / "paired" / f"{args.suite}__{args.baseline.name}__vs__{args.candidate.name}"


def _build_adapter(args: argparse.Namespace, out_dir: Path) -> Adapter:
    from agent_evolution.system_hint_adapter import (
        SystemHintAdapter,
        provider_key_vars,
        resolve_api_key,
        resolve_protocol_path,
    )
    from agent_evolution.target_harness import resolve_target_dir

    target_dir = Path(args.target_dir) if args.target_dir else resolve_target_dir()
    protocol_path = resolve_protocol_path(target_dir, getattr(args, "protocol", None))
    protocol = json.loads(protocol_path.read_text(encoding="utf-8-sig"))
    provider = protocol["provider"]["name"]
    key = resolve_api_key(provider)
    if not key:
        expected = provider_key_vars(provider)
        if not expected:
            raise SystemExit(f"no API key variable is known for provider {provider!r}")
        raise SystemExit(f"one of {', '.join(expected)} is required to run the {provider} target")

    from openai import OpenAI

    client = OpenAI(api_key=key, base_url=protocol["provider"]["base_url"])
    return SystemHintAdapter(
        client=client,
        run_root=out_dir,
        target_dir=target_dir,
        protocol_path=protocol_path,
    )


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
        max_workers=args.workers,
    )
    save_report(report, out_dir)
    print(render_report(report))
    print(f"saved: {out_dir / 'summary.json'}")
    return 0 if report.decision is Decision.ACCEPT else 1


def _run_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _build_proposer(args: argparse.Namespace) -> Proposer:
    return Proposer.from_env()


def _select_suites(adapter: Adapter, requested: Sequence[str]) -> list[str]:
    """Expand ``all`` to every suite the target defines, else keep the order asked for."""
    if "all" in requested:
        return list(adapter.suites())
    return list(dict.fromkeys(requested))


def _round_line(record: RoundRecord) -> str:
    return (
        f"round {record.index:02d}: {record.proposal.edit.describe()} -> "
        f"{record.report.decision.value} ({record.report.reason})"
    )


def _evolve(args: argparse.Namespace) -> int:
    run_dir = args.out if args.out is not None else Path("runs") / "evolve" / _run_stamp()
    requested = list(args.suite or [DEFAULT_SUITE])
    adapter = _build_adapter(args, run_dir / "episodes")
    suites = _select_suites(adapter, requested)
    if not suites:
        raise SystemExit("no suites selected")
    cases = [case for suite in suites for case in adapter.cases_for(suite)]
    report = run_evolution(
        adapter,
        _build_proposer(args),
        baseline=Snapshot.load(args.baseline),
        cases=cases,
        suites=suites,
        label="all" if "all" in requested else "+".join(requested),
        rounds=args.rounds,
        budget_tokens=args.budget_tokens,
        max_failures=args.max_failures,
        max_rollbacks=args.max_rollbacks,
        resamples=args.resamples,
        seed=args.seed,
        max_workers=args.workers,
        on_round=lambda record: print(_round_line(record)),
    )
    save_run(report, run_dir)
    print(render_history(report))
    print(f"saved: {run_dir / HISTORY_JSON}")
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
    evaluate_parser.add_argument(
        "--protocol",
        type=Path,
        default=None,
        help="protocol file to read (default: AGENT_EVOLUTION_PROTOCOL, else the target's own)",
    )
    evaluate_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="episodes to run at once (default: AGENT_EVOLUTION_WORKERS, else 1)",
    )

    evolve_parser = commands.add_parser(
        "evolve", help="search for a better harness over several rounds"
    )
    evolve_parser.add_argument(
        "--suite",
        action="append",
        default=None,
        help="suite to run (repeatable; 'all' for every suite; default combined)",
    )
    evolve_parser.add_argument("--baseline", type=Path, required=True, help="snapshot to evolve from")
    evolve_parser.add_argument("--out", type=Path, default=None, help="run directory for history")
    evolve_parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    evolve_parser.add_argument(
        "--budget-tokens",
        type=int,
        default=None,
        help="run-wide episode token cap; a round is not started if it would exceed it",
    )
    evolve_parser.add_argument("--max-failures", type=int, default=DEFAULT_MAX_FAILURES)
    evolve_parser.add_argument("--max-rollbacks", type=int, default=DEFAULT_MAX_ROLLBACKS)
    evolve_parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    evolve_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    evolve_parser.add_argument("--target-dir", type=Path, default=None)
    evolve_parser.add_argument(
        "--protocol",
        type=Path,
        default=None,
        help="protocol file to read (default: AGENT_EVOLUTION_PROTOCOL, else the target's own)",
    )
    evolve_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="episodes to run at once (default: AGENT_EVOLUTION_WORKERS, else 1)",
    )

    args = parser.parse_args(argv)
    if args.command == "evaluate":
        return _evaluate(args)
    if args.command == "evolve":
        return _evolve(args)
    if args.snapshot_command == "diff":
        return _diff(args.before, args.after)
    return _show(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
