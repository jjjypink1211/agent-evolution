"""An OpenAI-compatible double whose moves are derived from the messages it sees.

Unlike :mod:`replay_client`, which replays a frozen transcript, this client reads
the harness surface it is actually handed - the task prompt and the tool results -
and answers from that evidence alone. It exists to prove that a feature flip
reaches the objective gate: with ``timestamps`` enabled the policy can compare the
two records and name the later one; with it disabled the timestamps are absent from
every message, so the policy has no evidence and cannot answer.

It only understands the ``combined`` suite's prompt, which is what the regression
test that uses it drives.
"""

from __future__ import annotations

import json
import re
from typing import Any

PATTERNS = {
    "records": re.compile(r"read records (\S+) and (\S+) "),
    "fallback": re.compile(r"retrieve (\S+) or, if unavailable, fallback (\S+);"),
    "artifacts": re.compile(r"create artifacts (.+?), each containing exactly (\S+);"),
    "requested": re.compile(r"document (\S+) and recover"),
    "package": re.compile(r"install package (\S+) with"),
}
TIMESTAMPED_RECORD = re.compile(r"\[([^\]]+)\]\s+payload-for-(\S+)")
COUNTER_SUFFIX = re.compile(r"\nTool call #\d+ for '[^']*'\.$")


def without_counter(content: str) -> str:
    """Drop the ``tool_counter`` feature's trailing breadcrumb from a tool result."""
    return COUNTER_SUFFIX.sub("", content)


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
    def __init__(self, owner: "EvidencePolicyClient") -> None:
        self._owner = owner

    def create(self, **request: Any) -> _Response:
        return self._owner._respond(request)


class _Chat:
    def __init__(self, owner: "EvidencePolicyClient") -> None:
        self.completions = _Completions(owner)


class EvidencePolicyClient:
    """Answer each turn from the evidence already gathered, never from a script."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._turn = 0
        self._actual_document: str | None = None
        self.chat = _Chat(self)

    def _respond(self, request: dict[str, Any]) -> _Response:
        self.requests.append(request)
        results: dict[str, list[str]] = {}
        for message in request["messages"]:
            if message.get("role") == "tool":
                results.setdefault(message["name"], []).append(message["content"])
        prompt = next(m["content"] for m in request["messages"] if m["role"] == "user")
        self._turn += 1
        calls = [
            {"id": f"policy-{self._turn}-{index}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(arguments)}}
            for index, (name, arguments) in enumerate(self._plan(prompt, results))
        ]
        return _Response({
            "id": f"policy-response-{self._turn}",
            "model": "policy",
            "choices": [{
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None, "tool_calls": calls},
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    def _plan(self, prompt: str, results: dict[str, list[str]]) -> list[tuple[str, dict]]:
        spec = self._parse(prompt)
        if not results:
            first, second = spec["records"]
            return [
                ("read_record", {"name": first}),
                ("read_record", {"name": second}),
                ("probe_resource", {"name": spec["primary"]}),
                ("probe_resource", {"name": spec["fallback"]}),
            ]
        if "write_artifact" not in results:
            calls = [
                ("write_artifact", {"file": name, "content": spec["token"]})
                for name in spec["artifacts"]
            ]
            calls.append(("read_document", {"file": spec["requested"]}))
            calls.append(("list_documents", {}))
            return calls
        if "inspect_system" not in results:
            available = json.loads(without_counter(results["list_documents"][-1]))
            self._actual_document = next(
                name for name in available if name != spec["requested"]
            )
            return [("read_document", {"file": self._actual_document}), ("inspect_system", {})]
        system = json.loads(without_counter(results["inspect_system"][-1]))
        return [
            ("install_package", {"manager": system["manager"], "package": spec["package"]}),
            ("submit_result", {
                "selected_record": self._later_record(results),
                "fallback": spec["fallback"],
                "artifacts": spec["artifacts"],
                "document": self._actual_document,
                "token": spec["token"],
                "manager": system["manager"],
                "package": spec["package"],
            }),
        ]

    @staticmethod
    def _parse(prompt: str) -> dict[str, Any]:
        matched = {name: pattern.search(prompt) for name, pattern in PATTERNS.items()}
        if not all(matched.values()):
            raise AssertionError(f"policy cannot read the combined task prompt: {prompt!r}")
        records, fallback = matched["records"], matched["fallback"]
        artifacts, requested, package = (
            matched["artifacts"], matched["requested"], matched["package"]
        )
        return {
            "records": (records.group(1), records.group(2)),
            "primary": fallback.group(1),
            "fallback": fallback.group(2),
            "artifacts": [name.strip() for name in artifacts.group(1).split(",")],
            "token": artifacts.group(2),
            "requested": requested.group(1),
            "package": package.group(1),
        }

    @staticmethod
    def _later_record(results: dict[str, list[str]]) -> str:
        stamped = {
            name: stamp
            for content in results.get("read_record", [])
            for stamp, name in TIMESTAMPED_RECORD.findall(content)
        }
        if len(stamped) < len(results.get("read_record", [])):
            return ""
        return max(stamped, key=lambda name: stamped[name])
