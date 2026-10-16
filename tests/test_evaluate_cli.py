"""The ``evaluate`` command prints the paired report and writes per-case evidence."""

from __future__ import annotations

import json
from pathlib import Path

from agent_evolution import cli
from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.snapshot import Snapshot

from fake_adapter import FakeAdapter
from support import combined_cases, episode


def write_snapshot(root: Path, system_prompt: str) -> None:
    Snapshot(system_prompt=system_prompt).save(root)


def install_adapter(monkeypatch, cases, passing_case_ids) -> None:
    def responder(snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        passed = snapshot.system_prompt == "candidate" and case.case_id in passing_case_ids
        return episode(
            passed,
            tokens=3,
            evidence=f"{snapshot.system_prompt}__{case.case_id}.json",
        )

    adapter = FakeAdapter(responder=responder, cases=tuple(cases))
    monkeypatch.setattr(cli, "_build_adapter", lambda args, out_dir: adapter)


def evaluate_args(baseline: Path, candidate: Path, out: Path) -> list[str]:
    return [
        "evaluate",
        "--suite",
        "combined",
        "--baseline",
        str(baseline),
        "--candidate",
        str(candidate),
        "--out",
        str(out),
    ]


def test_evaluate_accepts_and_writes_summary(tmp_path: Path, capsys, monkeypatch) -> None:
    baseline, candidate, out = tmp_path / "baseline", tmp_path / "candidate", tmp_path / "out"
    write_snapshot(baseline, "baseline")
    write_snapshot(candidate, "candidate")
    cases = combined_cases(5)
    install_adapter(monkeypatch, cases, {case.case_id for case in cases})

    exit_code = cli.main(evaluate_args(baseline, candidate, out))

    assert exit_code == 0
    assert "decision: accept" in capsys.readouterr().out
    payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "accept"
    assert len(payload["cases"]) == 5
    assert (out / "summary.txt").is_file()


def test_evaluate_rolls_back_with_a_nonzero_exit_code(tmp_path: Path, capsys, monkeypatch) -> None:
    baseline, candidate, out = tmp_path / "baseline", tmp_path / "candidate", tmp_path / "out"
    write_snapshot(baseline, "baseline")
    write_snapshot(candidate, "candidate")
    install_adapter(monkeypatch, combined_cases(3), set())

    exit_code = cli.main(evaluate_args(baseline, candidate, out))

    assert exit_code == 1
    assert "decision: rollback" in capsys.readouterr().out


def test_evaluate_only_runs_the_requested_suite(tmp_path: Path, monkeypatch) -> None:
    baseline, candidate, out = tmp_path / "baseline", tmp_path / "candidate", tmp_path / "out"
    write_snapshot(baseline, "baseline")
    write_snapshot(candidate, "candidate")
    cases = combined_cases(3) + [CaseRef("todo_list", "todo-01")]
    install_adapter(monkeypatch, cases, {case.case_id for case in cases})

    cli.main(evaluate_args(baseline, candidate, out))

    payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert payload["suite"] == "combined"
    assert all(case["suite"] == "combined" for case in payload["cases"])
    assert len(payload["cases"]) == 3
