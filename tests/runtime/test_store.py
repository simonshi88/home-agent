from __future__ import annotations

import pytest

from agent.runtime.store import ServiceStore


def test_confirmation_is_owned_and_consumed_once(tmp_path) -> None:
    store = ServiceStore(str(tmp_path / "service.sqlite3"))
    store.ensure_session("phone-a", "browser-a")
    record = store.create_confirmation(
        session_id="phone-a",
        owner_id="browser-a",
        tool_names=("mcp__babybuddy__feedings_create",),
        description="确认执行 Baby Buddy 操作？",
        ttl_seconds=60,
    )

    resolved = store.resolve_confirmation(
        record.id,
        owner_id="browser-a",
        approved=True,
    )
    repeated = store.resolve_confirmation(
        record.id,
        owner_id="browser-a",
        approved=False,
    )

    assert resolved is not None
    assert resolved.state == "allowed"
    assert repeated is not None
    assert repeated.state == "allowed"


def test_session_cannot_be_reused_by_another_browser(tmp_path) -> None:
    store = ServiceStore(str(tmp_path / "service.sqlite3"))
    store.ensure_session("phone-a", "browser-a")

    with pytest.raises(PermissionError):
        store.ensure_session("phone-a", "browser-b")


def test_startup_expires_unresumable_confirmation(tmp_path) -> None:
    store = ServiceStore(str(tmp_path / "service.sqlite3"))
    store.ensure_session("phone-a", "browser-a")
    record = store.create_confirmation(
        session_id="phone-a",
        owner_id="browser-a",
        tool_names=("write_record",),
        description="确认执行 Baby Buddy 操作？",
        ttl_seconds=60,
    )

    assert store.expire_pending_confirmations() == 1
    expired = store.get_confirmation(record.id)

    assert expired is not None
    assert expired.state == "expired"


def test_chat_messages_are_owner_scoped_and_ordered(tmp_path) -> None:
    store = ServiceStore(str(tmp_path / "service.sqlite3"))
    store.ensure_session("phone-a", "browser-a")
    store.ensure_session("phone-b", "browser-b")
    store.record_chat_message(
        session_id="phone-a",
        owner_id="browser-a",
        role="user",
        content="宝宝刚喝了 120 毫升奶",
    )
    store.record_chat_message(
        session_id="phone-a",
        owner_id="browser-a",
        role="assistant",
        content="确认写入吗？",
        status="needs_confirmation",
    )

    messages = store.list_chat_messages(session_id="phone-a", owner_id="browser-a")
    conversations = store.list_conversations(owner_id="browser-a")

    assert messages is not None
    message_values = [
        (message.role, message.content, message.status) for message in messages
    ]
    assert message_values == [
        ("user", "宝宝刚喝了 120 毫升奶", None),
        ("assistant", "确认写入吗？", "needs_confirmation"),
    ]
    assert conversations[0].session_id == "phone-a"
    assert store.list_chat_messages(session_id="phone-a", owner_id="browser-b") is None
    assert store.list_conversations(owner_id="browser-b") == []
