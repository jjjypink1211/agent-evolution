"""The ``evaluate`` command prints the paired report and writes per-case evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from agent_evolution import cli, system_hint_adapter
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


def test_evaluate_passes_workers_to_the_report(tmp_path: Path, monkeypatch) -> None:
    baseline, candidate, out = tmp_path / "baseline", tmp_path / "candidate", tmp_path / "out"
    write_snapshot(baseline, "baseline")
    write_snapshot(candidate, "candidate")
    cases = combined_cases(3)
    install_adapter(monkeypatch, cases, {case.case_id for case in cases})

    seen: dict = {}
    original = cli.evaluate

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "evaluate", spy)

    cli.main(evaluate_args(baseline, candidate, out) + ["--workers", "3"])

    assert seen["max_workers"] == 3


def write_protocol(target: Path, provider: str, base_url: str = "https://example.invalid/v1") -> Path:
    target.mkdir(parents=True, exist_ok=True)
    path = target / "experiment_protocol.json"
    path.write_text(
        json.dumps({"provider": {"name": provider, "base_url": base_url}}), encoding="utf-8"
    )
    return path


def install_fake_openai(monkeypatch) -> dict:
    seen: dict = {}
    fake_openai = ModuleType("openai")

    def fake_client(**kwargs):
        seen["client"] = kwargs
        return object()

    fake_openai.OpenAI = fake_client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    return seen


class RecordingAdapter:
    def __init__(self, client, run_root, target_dir, protocol_path=None) -> None:
        self.client = client
        self.run_root = run_root
        self.target_dir = target_dir
        self.protocol_path = protocol_path


def test_build_adapter_keys_off_the_protocol_provider(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    write_protocol(target, "deepseek")
    monkeypatch.setenv("MOONSHOT_API_KEY", "stale-kimi-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    seen = install_fake_openai(monkeypatch)
    monkeypatch.setattr(system_hint_adapter, "SystemHintAdapter", RecordingAdapter)

    adapter = cli._build_adapter(argparse.Namespace(target_dir=target), tmp_path / "out")

    assert seen["client"] == {
        "api_key": "deepseek-key",
        "base_url": "https://example.invalid/v1",
    }
    assert adapter.target_dir == target
    assert adapter.protocol_path == target / "experiment_protocol.json"


def test_build_adapter_reads_an_overriding_protocol(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    write_protocol(target, "deepseek")
    override = tmp_path / "evolution_protocol.json"
    override.write_text(
        json.dumps({"provider": {"name": "kimi", "base_url": "https://override.invalid/v1"}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-key")
    monkeypatch.setattr(system_hint_adapter, "SystemHintAdapter", RecordingAdapter)
    seen = install_fake_openai(monkeypatch)

    adapter = cli._build_adapter(
        argparse.Namespace(target_dir=target, protocol=override), tmp_path / "out"
    )

    assert seen["client"] == {
        "api_key": "kimi-key",
        "base_url": "https://override.invalid/v1",
    }
    assert adapter.protocol_path == override


def test_build_adapter_honours_the_protocol_environment_variable(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "target"
    write_protocol(target, "deepseek")
    override = tmp_path / "from-env.json"
    override.write_text(
        json.dumps({"provider": {"name": "kimi", "base_url": "https://env.invalid/v1"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(system_hint_adapter.PROTOCOL_ENV_VAR, str(override))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-key")
    monkeypatch.setattr(system_hint_adapter, "SystemHintAdapter", RecordingAdapter)
    install_fake_openai(monkeypatch)

    adapter = cli._build_adapter(argparse.Namespace(target_dir=target), tmp_path / "out")

    assert adapter.protocol_path == override


def test_build_adapter_reports_the_provider_whose_key_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "target"
    write_protocol(target, "deepseek")
    monkeypatch.setenv("MOONSHOT_API_KEY", "stale-kimi-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        cli._build_adapter(argparse.Namespace(target_dir=target), tmp_path / "out")

    assert "DEEPSEEK_API_KEY" in str(excinfo.value)
