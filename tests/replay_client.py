"""An OpenAI-compatible test double that replays recorded responses in order."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class _Message:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self, mode: str = "json", exclude_none: bool = False) -> dict[str, Any]:
        if not exclude_none:
            return dict(self._data)
        return {key: value for key, value in self._data.items() if value is not None}


class _Choice:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.message = _Message(data["message"])

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return dict(self._data)


class _Response:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.choices = [_Choice(choice) for choice in data["choices"]]

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return dict(self._data)


class _Completions:
    def __init__(self, owner: "ReplayClient") -> None:
        self._owner = owner

    def create(self, **request: Any) -> _Response:
        return self._owner._next(request)


class _Chat:
    def __init__(self, owner: "ReplayClient") -> None:
        self.completions = _Completions(owner)


class ReplayClient:
    """Return recorded responses in order and record the requests it was asked."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = [dict(response) for response in responses]
        self.requests: list[dict[str, Any]] = []
        self.chat = _Chat(self)

    def _next(self, request: dict[str, Any]) -> _Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("replay client ran out of recorded responses")
        return _Response(self._responses.pop(0))


def recorded_responses(case_path: Path) -> list[dict[str, Any]]:
    """The successful provider responses recorded for one campaign case."""
    evidence = json.loads(case_path.read_text(encoding="utf-8"))
    return [call["response"] for call in evidence["api_calls"] if call.get("response")]
