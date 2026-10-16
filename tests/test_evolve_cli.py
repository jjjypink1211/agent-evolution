"""The ``evolve`` command drives the loop and writes a whole run's history."""

from __future__ import annotations

import json
from pathlib import Path

from agent_evolution import cli
from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.proposer import Proposer
from agent_evolution.snapshot import Snapshot

from fake_adapter import FakeAdapter
from scripted_model import ScriptedModel
from support import episode, system_prompt_edits

CASES = tuple(CaseRef("combined", f"all-{index:02d}") for index in range(1, 6))


def install(monkeypatch, adapter: FakeAdapter, model: ScriptedModel) -> None:
    monkeypatch.setattr(cli, "_build_adapter", lambda args, out_dir: adapter)
    monkeypatch.setattr(cli, "_build_proposer", lambda args: Proposer(model=model))


def baseline_dir(tmp_path: Path, prompt: str = "v0") -> Path:
    path = tmp_path / "baseline"
    Snapshot(system_prompt=prompt).save(path)
    return path


def evolve_args(baseline: Path, out: Path, *extra: str) -> list[str]:
    return ["evolve", "--baseline", str(baseline), "--out", str(out), *extra]


def test_evolve_command_accepts_and_writes_history(tmp_path: Path, capsys, monkeypatch) -> None:
    def responder(snapshot: Snapshot, case: CaseRef) -> EpisodeResult:
        return episode(
            snapshot.system_prompt == "v1",
            tokens=1,
            evidence=f"{snapshot.system_prompt}__{case.case_id}.json",
        )

    install(monkeypatch, FakeAdapter(responder=responder, cases=CASES), system_prompt_edits("v1"))
    out = tmp_path / "run"

    exit_code = cli.main(evolve_args(baseline_dir(tmp_path), out, "--rounds", "1"))

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "round 01:" in output
    assert "stop: rounds_exhausted" in output
    payload = json.loads((out / "history.json").read_text(encoding="utf-8"))
    assert payload["rounds_run"] == 1
    assert payload["accepts"] == 1
    assert (out / "rounds" / "01" / "summary.json").is_file()


def test_evolve_all_expands_to_every_suite(tmp_path: Path, monkeypatch) -> None:
    cases = (CaseRef("combined", "all-01"), CaseRef("todo_list", "todo-01"))
    adapter = FakeAdapter(responder=lambda snapshot, case: episode(True), cases=cases)
    install(monkeypatch, adapter, system_prompt_edits("v1"))
    out = tmp_path / "run"

    cli.main(evolve_args(baseline_dir(tmp_path), out, "--suite", "all", "--rounds", "1"))

    payload = json.loads((out / "history.json").read_text(encoding="utf-8"))
    assert payload["suites"] == ["combined", "todo_list"]
    assert payload["suite_label"] == "all"


def test_evolve_exits_zero_even_when_the_proposer_fails(tmp_path: Path, monkeypatch) -> None:
    adapter = FakeAdapter(responder=lambda snapshot, case: episode(False), cases=CASES)
    install(monkeypatch, adapter, ScriptedModel(replies=["nope", "nope"]))
    out = tmp_path / "run"

    exit_code = cli.main(evolve_args(baseline_dir(tmp_path), out, "--rounds", "3"))

    assert exit_code == 0
    payload = json.loads((out / "history.json").read_text(encoding="utf-8"))
    assert payload["stop_reason"] == "proposer_failed"
    assert payload["rounds_run"] == 0


def test_select_suites_expands_all_and_dedupes() -> None:
    adapter = FakeAdapter(cases=(CaseRef("combined", "all-01"), CaseRef("todo_list", "todo-01")))

    assert cli._select_suites(adapter, ["all"]) == ["combined", "todo_list"]
    assert cli._select_suites(adapter, ["combined", "combined"]) == ["combined"]
