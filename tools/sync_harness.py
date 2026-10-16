#!/usr/bin/env python3
"""Install the canonical harness snapshot into the target loop's bundled default.

The system-hint target loop reads its harness from ``harness_snapshot/`` next to
``run_experiment_2_8.py``. That directory must stay identical to the canonical
snapshot in ``snapshots/system-hint/``; this tool copies the canonical snapshot
over it.

The frozen golden fixture (``tests/fixtures/system_hint_harness.json``) records
the pre-refactor behaviour and is deliberately *not* written by this tool. If the
default harness is intentionally changed, update the fixture in the same review
so the equivalence test keeps documenting the change.

Usage:
    python tools/sync_harness.py [--target DIR] [--snapshot DIR] [--check]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_evolution.snapshot import Snapshot
from agent_evolution.target_harness import DEFAULT_TARGET_DIR

DEFAULT_SNAPSHOT = REPO_ROOT / "snapshots" / "system-hint"
TARGET_HARNESS_DIR_NAME = "harness_snapshot"


def sync(snapshot_dir: Path, target_dir: Path, check: bool) -> bool:
    canonical = Snapshot.load(snapshot_dir)
    bundled_dir = target_dir / TARGET_HARNESS_DIR_NAME
    if check:
        if not bundled_dir.is_dir():
            print(f"missing bundled harness at {bundled_dir}", file=sys.stderr)
            return False
        if Snapshot.load(bundled_dir) != canonical:
            print(f"bundled harness at {bundled_dir} differs from {snapshot_dir}", file=sys.stderr)
            return False
        print(f"bundled harness up to date: {bundled_dir}")
        return True
    if bundled_dir.exists():
        shutil.rmtree(bundled_dir)
    canonical.save(bundled_dir)
    print(f"installed canonical snapshot -> {bundled_dir}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET_DIR)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args(argv)
    return 0 if sync(args.snapshot, args.target, args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
