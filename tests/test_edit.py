"""A typed edit changes exactly one snapshot field, or it is rejected."""

from __future__ import annotations

import pytest

from agent_evolution.edit import OFF, ON, Edit, EditError, EditKind
from agent_evolution.snapshot import Snapshot


def base() -> Snapshot:
    return Snapshot(
        features=("tool_counter",),
        system_prompt="You are an audited agent.",
        status_sections={"tool_counter": "TOOL COUNTS: {rendered}."},
        tool_descriptions={"read_record": "Read one named record."},
    )


def test_feature_edit_turns_a_feature_on() -> None:
    candidate = Edit(kind=EditKind.FEATURE, key="todo_list", value=ON).apply(base())
    assert candidate.features == ("tool_counter", "todo_list")


def test_feature_edit_turns_a_feature_off() -> None:
    candidate = Edit(kind=EditKind.FEATURE, key="tool_counter", value=OFF).apply(base())
    assert candidate.features == ()


def test_system_prompt_edit_replaces_the_prompt() -> None:
    candidate = Edit(kind=EditKind.SYSTEM_PROMPT, value="New prompt.").apply(base())
    assert candidate.system_prompt == "New prompt."


def test_status_section_edit_replaces_a_section() -> None:
    edit = Edit(kind=EditKind.STATUS_SECTION, key="tool_counter", value="TOOL COUNTS: {rendered}. Switch.")
    assert edit.apply(base()).status_sections["tool_counter"] == "TOOL COUNTS: {rendered}. Switch."


def test_tool_description_edit_replaces_a_description() -> None:
    edit = Edit(kind=EditKind.TOOL_DESCRIPTION, key="read_record", value="Read a record by name.")
    assert edit.apply(base()).tool_descriptions["read_record"] == "Read a record by name."


def test_apply_changes_exactly_one_field() -> None:
    snapshot = base()
    for edit in (
        Edit(kind=EditKind.FEATURE, key="todo_list", value=ON),
        Edit(kind=EditKind.SYSTEM_PROMPT, value="New prompt."),
        Edit(kind=EditKind.STATUS_SECTION, key="tool_counter", value="Changed."),
        Edit(kind=EditKind.TOOL_DESCRIPTION, key="read_record", value="Changed."),
    ):
        assert len(snapshot.diff(edit.apply(snapshot))) == 1


def test_enabling_an_enabled_feature_is_rejected() -> None:
    edit = Edit(kind=EditKind.FEATURE, key="tool_counter", value=ON)
    with pytest.raises(EditError, match="already enabled"):
        edit.apply(base())


def test_disabling_a_disabled_feature_is_rejected() -> None:
    edit = Edit(kind=EditKind.FEATURE, key="todo_list", value=OFF)
    with pytest.raises(EditError, match="already disabled"):
        edit.apply(base())


def test_a_no_op_text_edit_is_rejected() -> None:
    edit = Edit(kind=EditKind.SYSTEM_PROMPT, value="You are an audited agent.")
    with pytest.raises(EditError, match="changes nothing"):
        edit.apply(base())


def test_an_unsafe_section_key_is_rejected_on_apply() -> None:
    edit = Edit(kind=EditKind.STATUS_SECTION, key="Tool-Counter", value="x")
    with pytest.raises(EditError):
        edit.apply(base())


def test_a_feature_edit_needs_on_or_off() -> None:
    with pytest.raises(EditError, match="must be 'on' or 'off'"):
        Edit(kind=EditKind.FEATURE, key="todo_list", value="maybe")


def test_a_keyed_edit_needs_a_key() -> None:
    with pytest.raises(EditError, match="needs a key"):
        Edit(kind=EditKind.STATUS_SECTION, value="x")


def test_a_system_prompt_edit_drops_the_key() -> None:
    edit = Edit(kind=EditKind.SYSTEM_PROMPT, key="ignored", value="New prompt.")
    assert edit.key == ""


def test_a_string_kind_is_coerced() -> None:
    assert Edit(kind="feature", key="todo_list", value=ON).kind is EditKind.FEATURE


def test_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        Edit(kind="nonsense")


def test_payload_round_trip() -> None:
    edit = Edit(kind=EditKind.STATUS_SECTION, key="todo_list", value="TODO: {rendered}.", reason="why")
    assert Edit.from_payload(edit.to_payload()) == edit


def test_describe_names_the_targeted_field() -> None:
    assert Edit(kind=EditKind.FEATURE, key="todo_list", value=ON).describe() == "feature[todo_list] := on"
    assert Edit(kind=EditKind.STATUS_SECTION, key="todo_list", value="x").describe() == "status[todo_list] := x"
    assert Edit(kind=EditKind.TOOL_DESCRIPTION, key="read_record", value="x").describe() == "tools[read_record] := x"


def test_from_payload_rejects_malformed_shapes() -> None:
    for payload in ("not an object", [], {}, {"kind": "nonsense"}, {"kind": "feature", "value": 1}):
        with pytest.raises(EditError):
            Edit.from_payload(payload)
