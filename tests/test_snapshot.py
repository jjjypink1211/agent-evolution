from __future__ import annotations

from pathlib import Path

import pytest

from agent_evolution.snapshot import SCHEMA_VERSION, Snapshot, SnapshotError


def sample() -> Snapshot:
    return Snapshot(
        features=("tool_counter", "todo_list"),
        system_prompt="You are an audited local-sandbox agent.",
        status_sections={
            "tool_counter": "TOOL COUNTS: {rendered}. Switch to a fallback.",
            "todo_list": "TODO LIST: {rendered}. Keep it visible.",
        },
        tool_descriptions={
            "read_record": "Read one named record.",
            "submit_result": "Submit the final result.",
        },
    )


def test_round_trip_is_stable(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    assert Snapshot.load(root) == sample()
    Snapshot.load(root).save(root)
    assert Snapshot.load(root) == sample()


def test_save_writes_one_file_per_section(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    assert (root / "snapshot.json").is_file()
    assert (root / "system_prompt.txt").read_text(encoding="utf-8") == (
        "You are an audited local-sandbox agent.\n"
    )
    assert sorted(path.name for path in (root / "status").glob("*.txt")) == [
        "todo_list.txt",
        "tool_counter.txt",
    ]
    assert sorted(path.name for path in (root / "tools").glob("*.txt")) == [
        "read_record.txt",
        "submit_result.txt",
    ]


def test_save_removes_stale_sections(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    trimmed = Snapshot(
        features=("tool_counter",),
        system_prompt=sample().system_prompt,
        status_sections={"tool_counter": sample().status_sections["tool_counter"]},
        tool_descriptions={"read_record": "Read one named record."},
    )
    trimmed.save(root)
    assert not (root / "status" / "todo_list.txt").exists()
    assert not (root / "tools" / "submit_result.txt").exists()
    assert Snapshot.load(root) == trimmed


def test_load_preserves_feature_order(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    assert Snapshot.load(root).features == ("tool_counter", "todo_list")


def test_metadata_defaults_to_current_schema_version(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    (root / "snapshot.json").write_text('{"features": []}\n', encoding="utf-8")
    assert Snapshot.load(root).schema_version == SCHEMA_VERSION


def test_load_rejects_missing_metadata(tmp_path: Path) -> None:
    (tmp_path / "system-hint").mkdir()
    with pytest.raises(SnapshotError):
        Snapshot.load(tmp_path / "system-hint")


def test_load_rejects_non_string_features(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    (root / "status").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "snapshot.json").write_text('{"features": [1, 2]}\n', encoding="utf-8")
    with pytest.raises(SnapshotError):
        Snapshot.load(root)


def test_rejects_unsafe_section_key() -> None:
    with pytest.raises(SnapshotError):
        Snapshot(status_sections={"Tool-Counter": "x"})


def test_diff_is_empty_for_identical_snapshots() -> None:
    assert sample().diff(sample()) == ()


def test_diff_reports_field_level_changes() -> None:
    before = Snapshot(
        features=("tool_counter",),
        system_prompt="before",
        status_sections={"tool_counter": "TOOL COUNTS: {rendered}."},
        tool_descriptions={"read_record": "Read one named record."},
    )
    after = Snapshot(
        features=("tool_counter", "todo_list"),
        system_prompt="after",
        status_sections={
            "tool_counter": "TOOL COUNTS: {rendered}. Switch.",
            "todo_list": "TODO LIST: {rendered}.",
        },
        tool_descriptions={
            "read_record": "Read one named record.",
            "probe_resource": "Probe a resource.",
        },
    )
    changes = {(change.kind, change.key) for change in before.diff(after)}
    assert changes == {
        ("changed", "features"),
        ("changed", "system_prompt"),
        ("changed", "status[tool_counter]"),
        ("added", "status[todo_list]"),
        ("added", "tools[probe_resource]"),
    }
    assert before.diff(after)[0].before is not None


def test_diff_reports_removals() -> None:
    before = Snapshot(status_sections={"todo_list": "TODO LIST: {rendered}."})
    after = Snapshot()
    changes = {change.kind: change for change in before.diff(after)}
    assert changes["removed"].key == "status[todo_list]"
    assert changes["removed"].after is None


def test_diff_detects_schema_version_change() -> None:
    before = Snapshot()
    after = Snapshot(schema_version=SCHEMA_VERSION + 1)
    assert before.diff(after)[0].key == "schema_version"


def test_render_status_section_substitutes_rendered_tail() -> None:
    snapshot = Snapshot(status_sections={"tool_counter": "TOOL COUNTS: {rendered}. Switch."})
    assert snapshot.render_status_section("tool_counter", "probe_resource=2") == (
        "TOOL COUNTS: probe_resource=2. Switch."
    )


def test_load_tolerates_utf8_bom_in_metadata(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    raw = (root / "snapshot.json").read_text(encoding="utf-8")
    (root / "snapshot.json").write_bytes(("\ufeff" + raw).encode("utf-8"))
    assert Snapshot.load(root).features == ("tool_counter", "todo_list")


def test_load_tolerates_utf8_bom_in_text_files(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    (root / "tools" / "read_record.txt").write_bytes(
        "\ufeffRead one named record.\n".encode("utf-8")
    )
    assert Snapshot.load(root).tool_descriptions["read_record"] == "Read one named record."


def test_load_preserves_multi_line_sections(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    Snapshot(status_sections={"tool_counter": "TOOL COUNTS: {rendered}.\nSwitch to a fallback."}).save(root)
    assert Snapshot.load(root).status_sections["tool_counter"] == (
        "TOOL COUNTS: {rendered}.\nSwitch to a fallback."
    )


def test_fingerprint_is_content_addressed(tmp_path: Path) -> None:
    root = tmp_path / "system-hint"
    sample().save(root)
    assert Snapshot.load(root).fingerprint() == sample().fingerprint()


def test_fingerprint_ignores_section_order() -> None:
    first = Snapshot(
        status_sections={"tool_counter": "A", "todo_list": "B"},
        tool_descriptions={"read_record": "C", "submit_result": "D"},
    )
    second = Snapshot(
        status_sections={"todo_list": "B", "tool_counter": "A"},
        tool_descriptions={"submit_result": "D", "read_record": "C"},
    )
    assert first.fingerprint() == second.fingerprint()


def test_fingerprint_changes_with_the_harness_surface() -> None:
    assert sample().fingerprint() != Snapshot(system_prompt="different").fingerprint()


def test_fingerprint_is_short_and_filesystem_safe() -> None:
    fingerprint = sample().fingerprint()
    assert fingerprint.isalnum()
    assert 8 <= len(fingerprint) <= 32

