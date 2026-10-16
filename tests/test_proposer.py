"""The proposer turns a scripted model reply into one validated, applicable edit."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from agent_evolution.adapter import CaseRef, EpisodeResult
from agent_evolution.edit import ON, Edit, EditKind
from agent_evolution.proposer import (
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    FailureReport,
    OpenAIChatModel,
    ProposalError,
    Proposer,
    render_request,
    snapshot_text,
)
from agent_evolution.snapshot import Snapshot

from scripted_model import ScriptedModel


def snapshot() -> Snapshot:
    return Snapshot(
        features=("tool_counter",),
        system_prompt="You are an audited agent.",
        status_sections={"tool_counter": "TOOL COUNTS: {rendered}."},
        tool_descriptions={"read_record": "Read one named record."},
    )


def failure(digest: str = "case combined/all-01: failed_gates=['timestamps']") -> FailureReport:
    return FailureReport(
        case=CaseRef("combined", "all-01"),
        result=EpisodeResult(
            objective_pass=False,
            component_scores={"timestamps": False, "tool_counter": True},
            llm_turns=4,
            tokens=1200,
            evidence_path=Path("episode.json"),
        ),
        digest=digest,
    )


def reply(**edit_fields: str) -> str:
    payload = {"kind": "feature", "key": "todo_list", "value": ON, "reason": "why"}
    payload.update(edit_fields)
    return json.dumps(payload)


def test_propose_parses_a_json_edit() -> None:
    model = ScriptedModel(replies=[reply()])
    proposal = Proposer(model=model).propose(snapshot(), [failure()])

    assert proposal.edit == Edit(EditKind.FEATURE, "todo_list", ON, "why")
    assert proposal.attempts == 1
    assert proposal.candidate(snapshot()).features == ("tool_counter", "todo_list")


def test_propose_accepts_an_edit_wrapper() -> None:
    wrapped = {"edit": {"kind": "feature", "key": "todo_list", "value": ON, "reason": "why"}}
    model = ScriptedModel(replies=[json.dumps(wrapped)])
    assert Proposer(model=model).propose(snapshot(), [failure()]).edit.key == "todo_list"


def test_a_reply_without_a_reason_is_repaired() -> None:
    unreasoned = json.dumps({"kind": "feature", "key": "todo_list", "value": ON})
    model = ScriptedModel(replies=[unreasoned, reply()])
    proposal = Proposer(model=model).propose(snapshot(), [failure()])

    assert proposal.attempts == 2
    assert "reason" in model.calls[1][1]


def test_propose_tolerates_a_fenced_code_block() -> None:
    fenced = "```json\n" + reply() + "\n```"
    model = ScriptedModel(replies=[fenced])
    assert Proposer(model=model).propose(snapshot(), [failure()]).edit.key == "todo_list"


def test_unparseable_reply_is_repaired_once() -> None:
    model = ScriptedModel(replies=["I cannot help with that.", reply()])
    proposal = Proposer(model=model).propose(snapshot(), [failure()])

    assert proposal.attempts == 2
    assert len(model.calls) == 2
    assert "rejected" in model.calls[1][1]


def test_repairs_are_exhausted() -> None:
    model = ScriptedModel(replies=["nope", "still nope"])
    with pytest.raises(ProposalError, match="no usable edit"):
        Proposer(model=model).propose(snapshot(), [failure()])
    assert len(model.calls) == 2


def test_retries_can_be_disabled() -> None:
    model = ScriptedModel(replies=["nope", reply()])
    with pytest.raises(ProposalError):
        Proposer(model=model, max_repairs=0).propose(snapshot(), [failure()])
    assert len(model.calls) == 1


def test_an_edit_that_changes_nothing_is_repaired() -> None:
    already_on = reply(key="tool_counter", value=ON)
    model = ScriptedModel(replies=[already_on, already_on])
    with pytest.raises(ProposalError):
        Proposer(model=model).propose(snapshot(), [failure()])


def test_the_request_carries_the_snapshot_and_every_digest() -> None:
    model = ScriptedModel(replies=[reply()])
    proposer = Proposer(model=model)
    proposer.propose(snapshot(), [failure("DIGEST-XYZ")])

    system, user = model.calls[0]
    assert "exactly one edit" in system
    assert "features: ['tool_counter']" in user
    assert "DIGEST-XYZ" in user


def test_the_request_notes_when_nothing_failed() -> None:
    assert "(none)" in render_request(snapshot(), [])


def test_snapshot_text_lists_every_surface() -> None:
    text = snapshot_text(snapshot())
    assert "system_prompt:" in text
    assert "  tool_counter: TOOL COUNTS: {rendered}." in text
    assert "  read_record: Read one named record." in text


def test_openai_chat_model_sends_system_and_user() -> None:
    seen: dict = {}

    class Completions:
        def create(self, **kwargs):
            seen.update(kwargs)
            message = types.SimpleNamespace(content="hello")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions()))
    model = OpenAIChatModel(model="kimi-k3", client=client, temperature=0.0)

    assert model.complete("sys", "usr") == "hello"
    assert seen["model"] == "kimi-k3"
    assert seen["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert seen["temperature"] == 0.0


def test_from_env_uses_dedicated_variables(monkeypatch) -> None:
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    stub = types.ModuleType("openai")
    stub.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", stub)

    proposer = Proposer.from_env(
        {ENV_API_KEY: "k", ENV_BASE_URL: "https://example.test/v1", ENV_MODEL: "m"}
    )

    assert isinstance(proposer.model, OpenAIChatModel)
    assert proposer.model.model == "m"
    assert captured == {"api_key": "k", "base_url": "https://example.test/v1"}


def test_from_env_requires_the_api_key() -> None:
    with pytest.raises(ProposalError, match=ENV_API_KEY):
        Proposer.from_env({})
