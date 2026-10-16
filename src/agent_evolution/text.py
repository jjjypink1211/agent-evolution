"""Small text helpers shared by snapshot edits and failure digests."""

from __future__ import annotations


def clip(value: object, limit: int) -> str:
    """Collapse whitespace in ``value`` and truncate it to ``limit`` characters."""
    collapsed = " ".join(("" if value is None else str(value)).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 3)] + "..."


__all__ = ["clip"]
