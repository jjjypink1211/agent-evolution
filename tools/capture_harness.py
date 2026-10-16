#!/usr/bin/env python3
"""Capture the system-hint harness into the default snapshot and golden fixture.

Usage:
    python tools/capture_harness.py [--target DIR] [--snapshot DIR] [--fixture FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_evolution.snapshot import Snapshot
from agent_evolution.target_harness import FEATURES, extract

DEFAULT_TARGET = Path(r"C:\agent\ai-agent-book\chapter2\system-hint")
DEFAULT_SNAPSHOT = REPO_ROOT / "snapshots" / "system-hint"
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "system_hint_harness.json"


def capture(target: Path, snapshot_dir: Path, fixture_path: Path) -> Snapshot:
    module_path = target / "run_experiment_2_8.py"
    if not module_path.is_file():
        raise FileNotFoundError(f"target harness not found at {module_path}")
    harness = extract(module_path)
    snapshot = Snapshot(
        features=FEATURES,
        system_prompt=harness["system_prompt"],
        status_sections=harness["status_sections"],
        tool_descriptions=harness["tool_descriptions"],
    )
    snapshot.save(snapshot_dir)
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(harness, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    snapshot = capture(args.target, args.snapshot, args.fixture)
    print(f"captured snapshot -> {args.snapshot}")
    print(f"captured fixture  -> {args.fixture}")
    print(f"features: {', '.join(snapshot.features)}")
    print(f"status sections: {', '.join(sorted(snapshot.status_sections))}")
    print(f"tools: {', '.join(sorted(snapshot.tool_descriptions))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
