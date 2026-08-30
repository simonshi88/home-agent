from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from agent.chat import Conversation


class FakeTextBlockDeltaEvent:
    def __init__(self, delta: str) -> None:
        self.delta = delta


class FakeRequireUserConfirmEvent:
    def __init__(self, tool_calls, reply_id: str) -> None:
        self.tool_calls = tool_calls
        self.reply_id = reply_id


class FakeConfirmResult:
    def __init__(self, *, confirmed: bool, tool_call) -> None:
        self.confirmed = confirmed
        self.tool_call = tool_call


class FakeUserConfirmResultEvent:
    def __init__(self, *, reply_id: str, confirm_results) -> None:
        self.reply_id = reply_id
        self.confirm_results = confirm_results


class FakeUserMsg:
    def __init__(self, *, name: str, content: str) -> None:
        self.name = name
        self.content = content


class FakeAgent:
    def __init__(self) -> None:
        self.confirm_results = None

    async def reply_stream(self, inputs):
        if isinstance(inputs, FakeUserMsg):
            yield FakeTextBlockDeltaEvent("请确认。")
            yield FakeRequireUserConfirmEvent(
                [
                    SimpleNamespace(id="tool-1", name="write_a", input="{}"),
                    SimpleNamespace(id="tool-2", name="write_b", input="{}"),
                ],
                reply_id="reply-1",
            )
        else:
            self.confirm_results = inputs.confirm_results
            yield FakeTextBlockDeltaEvent("处理完成。")


class FakeConcurrentAgent:
    def __init__(self) -> None:
        self.calls = [
            SimpleNamespace(id="tool-1", name="read_a", input="{}"),
            SimpleNamespace(id="tool-2", name="read_b", input="{}"),
        ]
        self.confirm_results = None

    async def reply_stream(self, inputs):
        if isinstance(inputs, FakeUserMsg):
            yield FakeRequireUserConfirmEvent([self.calls[0]], "reply-1")
            yield FakeRequireUserConfirmEvent([self.calls[1]], "reply-1")
        else:
            self.confirm_results = inputs.confirm_results
            yield FakeTextBlockDeltaEvent("全部完成。")


@pytest.fixture
def fake_agentscope(monkeypatch: pytest.MonkeyPatch) -> None:
    event = ModuleType("agentscope.event")
    event.ConfirmResult = FakeConfirmResult
    event.RequireUserConfirmEvent = FakeRequireUserConfirmEvent
    event.TextBlockDeltaEvent = FakeTextBlockDeltaEvent
    event.UserConfirmResultEvent = FakeUserConfirmResultEvent
    message = ModuleType("agentscope.message")
    message.UserMsg = FakeUserMsg
    monkeypatch.setitem(sys.modules, "agentscope.event", event)
    monkeypatch.setitem(sys.modules, "agentscope.message", message)


async def test_conversation_confirms_all_calls_as_one_group(fake_agentscope) -> None:
    agent = FakeAgent()
    conversation = Conversation(agent=agent, user_name="parent")
    captured = []

    async def confirm(tool_calls):
        captured.append(tool_calls)
        return [True, False]

    reply = await conversation.reply("记录一下", confirm=confirm)

    assert reply == "请确认。处理完成。"
    assert len(captured) == 1
    assert [call.name for call in captured[0]] == ["write_a", "write_b"]
    assert [result.confirmed for result in agent.confirm_results] == [True, False]


async def test_conversation_does_not_drop_concurrent_confirmation_events(
    fake_agentscope,
) -> None:
    agent = FakeConcurrentAgent()
    conversation = Conversation(agent=agent, user_name="parent")
    captured = []

    async def confirm(tool_calls):
        captured.append(tool_calls)
        return [True] * len(tool_calls)

    reply = await conversation.reply("并发查询", confirm=confirm)

    assert reply == "全部完成。"
    assert [[call.id for call in calls] for calls in captured] == [
        ["tool-1", "tool-2"],
    ]
    assert [result.tool_call.id for result in agent.confirm_results] == [
        "tool-1",
        "tool-2",
    ]
