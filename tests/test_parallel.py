"""The batch runner: opt-in concurrency that preserves case order."""

from __future__ import annotations

import threading
import time

from agent_evolution.parallel import (
    DEFAULT_WORKERS,
    WORKERS_ENV_VAR,
    resolve_workers,
    run_batch,
)
from agent_evolution.snapshot import Snapshot

from fake_adapter import FakeAdapter
from support import combined_cases, episode

SNAPSHOT = Snapshot(system_prompt="v0")


def ordered_results(max_workers: int | None):
    cases = combined_cases(5)

    def responder(snapshot: Snapshot, case) -> object:
        time.sleep(0.01 if case.case_id.endswith("01") else 0)
        return episode(True, evidence=f"{case.case_id}.json")

    adapter = FakeAdapter(responder=responder, cases=tuple(cases))
    return cases, run_batch(adapter, SNAPSHOT, cases, max_workers=max_workers)


def peak_overlap(max_workers: int | None):
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def responder(snapshot: Snapshot, case) -> object:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.02)
        with lock:
            state["active"] -= 1
        return episode(True)

    run_batch(FakeAdapter(responder=responder), SNAPSHOT, combined_cases(4), max_workers=max_workers)
    return state["peak"]


def test_resolve_workers_defaults_to_one() -> None:
    assert DEFAULT_WORKERS == 1
    assert resolve_workers(5) == 1


def test_resolve_workers_never_exceeds_the_batch() -> None:
    assert resolve_workers(3, max_workers=8) == 3


def test_resolve_workers_treats_nonpositive_as_the_default() -> None:
    assert resolve_workers(4, max_workers=0) == 1
    assert resolve_workers(4, max_workers=-2) == 1


def test_resolve_workers_with_no_cases_is_zero() -> None:
    assert resolve_workers(0, max_workers=4) == 0


def test_resolve_workers_reads_the_env_var(monkeypatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "3")
    assert resolve_workers(5) == 3


def test_resolve_workers_ignores_an_unparsable_env_var(monkeypatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "lots")
    assert resolve_workers(5) == 1


def test_resolve_workers_prefers_the_explicit_argument(monkeypatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "3")
    assert resolve_workers(5, max_workers=2) == 2


def test_default_is_sequential() -> None:
    assert peak_overlap(max_workers=1) == 1


def test_env_var_enables_concurrency(monkeypatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "4")
    assert peak_overlap(max_workers=None) > 1


def test_workers_overlap_the_episodes() -> None:
    assert peak_overlap(max_workers=4) > 1


def test_results_follow_case_order_despite_overlap() -> None:
    cases, results = ordered_results(max_workers=4)
    assert [result.evidence_path.name for result in results] == [
        f"{case.case_id}.json" for case in cases
    ]


def test_results_follow_case_order_when_sequential() -> None:
    cases, results = ordered_results(max_workers=1)
    assert [result.evidence_path.name for result in results] == [
        f"{case.case_id}.json" for case in cases
    ]


def test_every_episode_sees_the_same_snapshot() -> None:
    cases = tuple(combined_cases(4))
    adapter = FakeAdapter(responder=lambda snapshot, case: episode(True))
    run_batch(adapter, SNAPSHOT, cases, max_workers=4)
    assert all(snapshot is SNAPSHOT for snapshot, _ in adapter.calls)
    assert {case for _, case in adapter.calls} == set(cases)
