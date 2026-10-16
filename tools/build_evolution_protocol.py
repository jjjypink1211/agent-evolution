#!/usr/bin/env python3
"""Derive the evolution-only protocol from the target's frozen one.

The target's ``experiment_protocol.json`` anchors published evidence: its
``protocol_sha256`` is recorded in the frozen campaign and its README states the
preregistered case count. Editing it in place would invalidate that evidence, so
this tool *derives* ``protocols/system-hint-evolution.json`` instead and never
writes the frozen file.

The derived protocol differs in exactly one thing: ``cases.todo_list`` gains five
more cases of the same shape as the frozen five (a plain token and four ``.txt``
deliverables). The frozen five are enough when the model under test fails most of
them, but a net gain of +4-of-5 sits exactly on the bootstrap threshold, so a
wider case set makes acceptance depend on the edit rather than on the draw.

Usage:
    python tools/build_evolution_protocol.py [--source FILE] [--out FILE] [--check]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_evolution.system_hint_adapter import PROTOCOL_NAME
from agent_evolution.target_harness import DEFAULT_TARGET_DIR

DEFAULT_SOURCE = DEFAULT_TARGET_DIR / PROTOCOL_NAME
DEFAULT_OUT = REPO_ROOT / "protocols" / "system-hint-evolution.json"

# Five more todo_list cases, same shape as the frozen ones: one plain token and
# four ``.txt`` sandbox artifacts, all names unique across the whole protocol.
# The gate is generic over ``artifacts``/``token``, so widening the case set is
# pure data - it must not change what the cases ask for.
EXTRA_TODO_CASES: list[dict[str, object]] = [
    {
        "id": "todo-06",
        "token": "FOXTROT-962",
        "artifacts": ["intake.txt", "forecast.txt", "controls.txt", "closure.txt"],
    },
    {
        "id": "todo-07",
        "token": "GOLF-073",
        "artifacts": ["briefing.txt", "drafting.txt", "checklist.txt", "finale.txt"],
    },
    {
        "id": "todo-08",
        "token": "HOTEL-184",
        "artifacts": ["capture.txt", "modelling.txt", "appraisal.txt", "handover.txt"],
    },
    {
        "id": "todo-09",
        "token": "INDIA-295",
        "artifacts": ["catalogue.txt", "estimation.txt", "validating.txt", "submission.txt"],
    },
    {
        "id": "todo-10",
        "token": "JULIET-306",
        "artifacts": ["gathering.txt", "processing.txt", "reviewing.txt", "delivering.txt"],
    },
]

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(source_bytes: bytes) -> dict:
    """Return the evolution protocol: the frozen one, with five more todo cases."""
    protocol = json.loads(source_bytes)
    derived = copy.deepcopy(protocol)
    frozen_todo = protocol["cases"]["todo_list"]
    derived["cases"]["todo_list"] = copy.deepcopy(frozen_todo) + copy.deepcopy(
        EXTRA_TODO_CASES
    )
    derived["evolution_extension"] = {
        "purpose": "widen the todo_list case set for evolution only, without touching the frozen protocol",
        "source_protocol": PROTOCOL_NAME,
        "source_protocol_sha256": sha256(source_bytes),
        "added_cases": {
            "suite": "todo_list",
            "ids": [case["id"] for case in EXTRA_TODO_CASES],
        },
    }
    return derived


def render(protocol: dict) -> str:
    return json.dumps(protocol, indent=2, ensure_ascii=False) + "\n"


def run(source: Path, out: Path, check: bool) -> bool:
    if not source.is_file():
        print(f"source protocol not found at {source}", file=sys.stderr)
        return False
    expected = render(build(source.read_bytes()))
    if check:
        if not out.is_file():
            print(f"missing derived protocol at {out}", file=sys.stderr)
            return False
        if out.read_text(encoding="utf-8") != expected:
            print(f"derived protocol at {out} is stale; re-run without --check", file=sys.stderr)
            return False
        print(f"derived protocol up to date: {out}")
        return True
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(expected)
    print(f"wrote {out}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args(argv)
    return 0 if run(args.source, args.out, args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
