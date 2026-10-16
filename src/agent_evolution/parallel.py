"""Run one snapshot's episode batch, optionally concurrently, order preserved.

Episodes in a batch are independent: each writes its own evidence directory and
issues its own model calls, so a batch may run on a thread pool. The target loop,
however, keeps its loaded harness in a module-global, so every episode in a batch
must share one snapshot - whose harness content is identical whichever episode
directory it was saved to - and two *different* snapshots must never be in flight
at once. Callers therefore pass one snapshot and get results back in case order.

Concurrency is opt-in: the default is one worker, so callers that assert call
order (the test doubles) keep their behaviour. Raise it with ``max_workers`` or
the ``AGENT_EVOLUTION_WORKERS`` environment variable.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

from agent_evolution.adapter import Adapter, CaseRef, EpisodeResult
from agent_evolution.snapshot import Snapshot

DEFAULT_WORKERS = 1
WORKERS_ENV_VAR = "AGENT_EVOLUTION_WORKERS"


def resolve_workers(count: int, max_workers: int | None = None) -> int:
    """How many episodes of a ``count``-case batch to run at once.

    ``None`` falls back to ``AGENT_EVOLUTION_WORKERS`` and then to
    :data:`DEFAULT_WORKERS`; a non-positive or unparsable value is treated as the
    default. The result never exceeds ``count``.
    """
    if count <= 0:
        return 0
    requested = _env_workers() if max_workers is None else max_workers
    try:
        requested = int(requested)
    except (TypeError, ValueError):
        requested = DEFAULT_WORKERS
    if requested < 1:
        requested = DEFAULT_WORKERS
    return min(count, requested)


def run_batch(
    adapter: Adapter,
    snapshot: Snapshot,
    cases: Sequence[CaseRef],
    *,
    max_workers: int | None = None,
) -> list[EpisodeResult]:
    """Run every case against ``snapshot`` and return the results in case order."""
    ordered = list(cases)
    workers = resolve_workers(len(ordered), max_workers)
    if workers <= 1:
        return [adapter.run(snapshot, case) for case in ordered]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda case: adapter.run(snapshot, case), ordered))


def _env_workers() -> int:
    raw = os.environ.get(WORKERS_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_WORKERS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_WORKERS


__all__ = [
    "DEFAULT_WORKERS",
    "WORKERS_ENV_VAR",
    "resolve_workers",
    "run_batch",
]
