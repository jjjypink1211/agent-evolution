"""A scripted :class:`ProposerModel` for deterministic proposer tests."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScriptedModel:
    """Return queued replies in order and record the prompts it was asked."""

    replies: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self.replies:
            raise AssertionError("scripted model ran out of replies")
        return self.replies.pop(0)
