from __future__ import annotations

from types import SimpleNamespace

from agent.config import Settings
from agent.runtime.service import AgentService, _ConversationRuntime


class WaitingConversation:
    def __init__(self, tool_name: str = "create_feeding") -> None:
        self.decisions = None
        self.tool_name = tool_name

    async def reply(self, text, confirm):
        self.decisions = await confirm(
            (SimpleNamespace(id="tool-1", name=self.tool_name, input="{}"),),
        )
        return "已记录。"


def _settings(tmp_path) -> Settings:
    return Settings(
        model_provider="ollama",
        api_key="http://localhost:11434",
        web_password="family-password",
        web_session_secret="x" * 32,
        web_database_path=str(tmp_path / "service.sqlite3"),
        audit_path=str(tmp_path / "audit.jsonl"),
    )


async def test_service_waits_for_http_confirmation_before_resuming(
    tmp_path, monkeypatch
) -> None:
    service = AgentService(_settings(tmp_path))
    conversation = WaitingConversation()
    runtime = _ConversationRuntime(conversation=conversation, client=None)

    async def runtime_for(session_id: str, *, voice_confirmation: bool):
        return runtime

    monkeypatch.setattr(service, "_runtime_for", runtime_for)
    await service.start()
    try:
        pending = await service.chat(
            session_id="phone-parent-a",
            owner_id="browser-a",
            text="记录喂奶",
            timezone="Asia/Shanghai",
        )
        assert pending.status == "needs_confirmation"
        assert pending.confirmation is not None
        assert conversation.decisions is None

        result = await service.confirm(
            confirmation_id=pending.confirmation.id,
            owner_id="browser-a",
            approved=True,
        )

        assert result.status == "completed"
        assert conversation.decisions == [True]
    finally:
        await service.stop()


async def test_service_auto_allows_read_only_chat_tools(tmp_path, monkeypatch) -> None:
    service = AgentService(_settings(tmp_path))
    conversation = WaitingConversation("mcp__babybuddy__feedings_get_feeding")
    runtime = _ConversationRuntime(conversation=conversation, client=None)

    async def runtime_for(session_id: str, *, voice_confirmation: bool):
        return runtime

    monkeypatch.setattr(service, "_runtime_for", runtime_for)
    await service.start()
    try:
        result = await service.chat(
            session_id="phone-parent-a",
            owner_id="browser-a",
            text="上一次喂奶是什么时候？",
            timezone="Asia/Shanghai",
        )
        assert result.status == "completed"
        assert conversation.decisions == [True]
    finally:
        await service.stop()


async def test_voice_service_leaves_confirmation_to_the_conversation(
    tmp_path,
    monkeypatch,
) -> None:
    service = AgentService(_settings(tmp_path))
    conversation = WaitingConversation("mcp__babybuddy__feedings_create_feeding")
    runtime = _ConversationRuntime(conversation=conversation, client=None)

    async def runtime_for(session_id: str, *, voice_confirmation: bool):
        assert voice_confirmation is True
        return runtime

    monkeypatch.setattr(service, "_runtime_for", runtime_for)
    await service.start()
    try:
        result = await service.chat(
            session_id="ha-session-a",
            owner_id="ha-owner-a",
            text="确认记录喂奶",
            timezone="Asia/Shanghai",
            voice_confirmation=True,
        )
        assert result.status == "completed"
        assert conversation.decisions == [True]
    finally:
        await service.stop()


async def test_browser_chat_persists_original_messages_and_outcomes(
    tmp_path,
    monkeypatch,
) -> None:
    service = AgentService(_settings(tmp_path))
    conversation = WaitingConversation()
    runtime = _ConversationRuntime(conversation=conversation, client=None)

    async def runtime_for(session_id: str, *, voice_confirmation: bool):
        return runtime

    monkeypatch.setattr(service, "_runtime_for", runtime_for)
    await service.start()
    try:
        pending = await service.chat(
            session_id="phone-parent-a",
            owner_id="browser-a",
            text="记录喂奶",
            timezone="Asia/Shanghai",
        )
        assert pending.confirmation is not None
        await service.confirm(
            confirmation_id=pending.confirmation.id,
            owner_id="browser-a",
            approved=True,
        )

        messages = service.conversation_messages(
            session_id="phone-parent-a",
            owner_id="browser-a",
        )

        assert messages is not None
        message_values = [
            (message.role, message.content, message.status) for message in messages
        ]
        assert message_values == [
            ("user", "记录喂奶", None),
            ("assistant", pending.message, "needs_confirmation"),
            ("assistant", "已记录。", "completed"),
        ]
        assert "trusted_runtime_context" not in messages[0].content
    finally:
        await service.stop()


async def test_home_assistant_chat_does_not_persist_browser_history(
    tmp_path,
    monkeypatch,
) -> None:
    service = AgentService(_settings(tmp_path))
    conversation = WaitingConversation("mcp__babybuddy__feedings_get_feeding")
    runtime = _ConversationRuntime(conversation=conversation, client=None)

    async def runtime_for(session_id: str, *, voice_confirmation: bool):
        return runtime

    monkeypatch.setattr(service, "_runtime_for", runtime_for)
    await service.start()
    try:
        await service.chat(
            session_id="ha-session-a",
            owner_id="ha-owner-a",
            text="上一次喂奶是什么时候？",
            timezone="Asia/Shanghai",
            voice_confirmation=True,
        )

        assert service.conversations(owner_id="ha-owner-a") == []
    finally:
        await service.stop()


def test_today_allows_only_read_tool_names(tmp_path) -> None:
    service = AgentService(_settings(tmp_path))

    assert service._is_read_only_tool("mcp__babybuddy__children_list_children")
    assert service._is_read_only_tool("mcp__babybuddy__feedings_get_feeding")
    assert not service._is_read_only_tool("mcp__babybuddy__diapers_create_change")
