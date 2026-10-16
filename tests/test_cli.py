from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agent_evolution.cli import main
from agent_evolution.snapshot import Snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_snapshot(root: Path, **kwargs) -> None:
    Snapshot(**kwargs).save(root)


def test_diff_reports_no_differences(tmp_path: Path, capsys) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_snapshot(before, features=("tool_counter",))
    write_snapshot(after, features=("tool_counter",))
    assert main(["snapshot", "diff", str(before), str(after)]) == 0
    assert capsys.readouterr().out.strip() == "no differences"


def test_diff_lists_changes_and_exits_nonzero(tmp_path: Path, capsys) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_snapshot(
        before,
        features=("tool_counter",),
        system_prompt="before",
        status_sections={"tool_counter": "TOOL COUNTS: {rendered}."},
    )
    write_snapshot(
        after,
        features=("tool_counter", "todo_list"),
        system_prompt="after",
        status_sections={"tool_counter": "TOOL COUNTS: {rendered}. Switch."},
    )
    assert main(["snapshot", "diff", str(before), str(after)]) == 1
    output = capsys.readouterr().out
    assert "~ features:" in output
    assert "~ status[tool_counter]:" in output
    assert "~ system_prompt:" in output


def test_show_prints_harness_surface(tmp_path: Path, capsys) -> None:
    root = tmp_path / "snap"
    write_snapshot(
        root,
        features=("tool_counter",),
        system_prompt="You are an audited local-sandbox agent.",
        status_sections={"tool_counter": "TOOL COUNTS: {rendered}."},
        tool_descriptions={"read_record": "Read one named record."},
    )
    assert main(["snapshot", "show", str(root)]) == 0
    output = capsys.readouterr().out
    assert "features: tool_counter" in output
    assert "status[tool_counter]: TOOL COUNTS: {rendered}." in output
    assert "tool[read_record]: Read one named record." in output


def test_diff_does_not_crash_on_a_non_ascii_console(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_snapshot(before, tool_descriptions={"read_record": "Read one named record."})
    write_snapshot(
        after,
        tool_descriptions={"read_record": "Read one named record \u2192 prefer the newest."},
    )

    environment = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "src"), PYTHONIOENCODING="gbk")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_evolution",
            "snapshot",
            "diff",
            str(before),
            str(after),
        ],
        capture_output=True,
        env=environment,
    )
    assert result.returncode == 1
    assert b"Traceback" not in result.stderr
