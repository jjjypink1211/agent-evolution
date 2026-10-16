"""The evolution-only protocol: a wider ``todo_list`` that leaves the frozen one alone.

The target's ``experiment_protocol.json`` anchors published evidence, so it must
never be edited to widen the case set. ``tools/build_evolution_protocol.py``
derives ``protocols/system-hint-evolution.json`` instead. These tests pin the
derivation (source-verbatim apart from ``cases`` and ``evolution_extension``) and
the adapter's ability to read it from an explicit path or the environment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_evolution.adapter import CaseRef
from agent_evolution.snapshot import Snapshot
from agent_evolution.system_hint_adapter import (
    PROTOCOL_ENV_VAR,
    PROTOCOL_NAME,
    SystemHintAdapter,
    resolve_protocol_path,
)

from build_evolution_protocol import DEFAULT_OUT, EXTRA_TODO_CASES, build, render, sha256

from replay_client import ReplayClient

REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVED_PATH = REPO_ROOT / "protocols" / "system-hint-evolution.json"
SNAPSHOT_ROOT = REPO_ROOT / "snapshots" / "system-hint"

# A provider response that stops without calling a tool: enough to drive one real
# offline episode to its (failing) objective gate without any network access.
STALLED_RESPONSE: dict = {
    "id": "stalled-response",
    "model": "policy",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "nothing to do", "tool_calls": None},
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def frozen_source(target_module_path: Path) -> Path:
    return target_module_path.parent / PROTOCOL_NAME


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_resolve_protocol_path_prefers_explicit_then_env_then_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    monkeypatch.delenv(PROTOCOL_ENV_VAR, raising=False)
    assert resolve_protocol_path(target) == target / PROTOCOL_NAME

    monkeypatch.setenv(PROTOCOL_ENV_VAR, str(tmp_path / "env.json"))
    assert resolve_protocol_path(target) == tmp_path / "env.json"

    explicit = tmp_path / "explicit.json"
    assert resolve_protocol_path(target, explicit) == explicit


def test_derived_protocol_is_the_builder_output(target_module_path: Path) -> None:
    assert DEFAULT_OUT == DERIVED_PATH
    expected = render(build(frozen_source(target_module_path).read_bytes()))
    assert DERIVED_PATH.read_text(encoding="utf-8") == expected


def test_derived_protocol_matches_the_frozen_one_apart_from_the_extension(
    target_module_path: Path,
) -> None:
    source = load(frozen_source(target_module_path))
    derived = load(DERIVED_PATH)

    assert set(derived) - set(source) == {"evolution_extension"}
    assert set(source) - set(derived) == set()
    for key, value in source.items():
        if key == "cases":
            continue
        assert derived[key] == value, key

    assert set(derived["cases"]) == set(source["cases"])
    for suite, cases in source["cases"].items():
        if suite == "todo_list":
            continue
        assert derived["cases"][suite] == cases, suite

    frozen_todo = source["cases"]["todo_list"]
    assert derived["cases"]["todo_list"][: len(frozen_todo)] == frozen_todo


def test_extension_records_the_frozen_source_it_was_derived_from(
    target_module_path: Path,
) -> None:
    source_path = frozen_source(target_module_path)
    derived = load(DERIVED_PATH)
    extension = derived["evolution_extension"]

    assert extension["source_protocol"] == PROTOCOL_NAME
    assert extension["source_protocol_sha256"] == sha256(source_path.read_bytes())
    assert extension["source_protocol_sha256"] == hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    added = derived["cases"]["todo_list"][len(load(source_path)["cases"]["todo_list"]) :]
    assert extension["added_cases"] == {
        "suite": "todo_list",
        "ids": [case["id"] for case in added],
    }
    assert added


def test_added_todo_cases_are_unique_and_well_formed(target_module_path: Path) -> None:
    derived = load(DERIVED_PATH)
    todo = derived["cases"]["todo_list"]
    ids = [case["id"] for case in todo]

    assert len(todo) == 10
    assert len(ids) == len(set(ids))
    assert len({case["token"] for case in todo}) == len(todo)
    for case in todo:
        assert len(case["artifacts"]) == 4
        assert all(name.endswith(".txt") for name in case["artifacts"])


def test_added_cases_keep_the_frozen_case_shape(target_module_path: Path) -> None:
    """Widening must add equivalent cases, not harder ones.

    A previous derivation both retargeted the provider and hardened the cases
    (more deliverables, confusable tokens). It was measured and rejected: the
    cheaper provider passed every hardened case, and the loop's real blocker was
    its failure digest, not the case difficulty. Widening may only add cases of
    the shape the frozen protocol already declares.
    """
    source = load(frozen_source(target_module_path))
    derived = load(DERIVED_PATH)

    frozen_shapes = {
        len(case["artifacts"]) for case in source["cases"]["todo_list"]
    }
    added = derived["cases"]["todo_list"][len(source["cases"]["todo_list"]) :]
    assert {len(case["artifacts"]) for case in added} <= frozen_shapes
    assert [case["id"] for case in added] == [case["id"] for case in EXTRA_TODO_CASES]


def test_adapter_reads_the_derived_protocol_without_touching_the_frozen_default(
    target_module_path: Path, tmp_path: Path
) -> None:
    derived_adapter = SystemHintAdapter(
        client=object(), run_root=tmp_path, protocol_path=DERIVED_PATH
    )
    assert derived_adapter.protocol_path == DERIVED_PATH
    assert [case.case_id for case in derived_adapter.cases_for("todo_list")] == [
        "todo-01",
        "todo-02",
        "todo-03",
        "todo-04",
        "todo-05",
        "todo-06",
        "todo-07",
        "todo-08",
        "todo-09",
        "todo-10",
    ]

    frozen_adapter = SystemHintAdapter(
        client=object(), run_root=tmp_path, target_dir=target_module_path.parent
    )
    assert frozen_adapter.protocol_path == frozen_source(target_module_path)
    assert len(frozen_adapter.cases_for("todo_list")) == 5


def test_added_case_drives_the_real_target_under_the_derived_protocol(
    target_module_path: Path, tmp_path: Path
) -> None:
    """An added case must run end to end, tagged with the derived protocol's hash."""
    client = ReplayClient([STALLED_RESPONSE] * 16)
    adapter = SystemHintAdapter(
        client=client, run_root=tmp_path, protocol_path=DERIVED_PATH
    )

    result = adapter.run(Snapshot.load(SNAPSHOT_ROOT), CaseRef("todo_list", "todo-06"))

    evidence = json.loads(Path(result.evidence_path).read_text(encoding="utf-8"))
    assert evidence["case_id"] == "todo-06"
    assert evidence["protocol_sha256"] == sha256(DERIVED_PATH.read_bytes())
    assert evidence["protocol_sha256"] != sha256(frozen_source(target_module_path).read_bytes())
    assert result.objective_pass is False
    assert "FOXTROT-962" in json.dumps(client.requests)
