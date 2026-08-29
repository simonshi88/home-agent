from __future__ import annotations

from fastapi.testclient import TestClient

from agent.config import Settings
from agent.runtime.service import ChatOutcome, TodaySnapshot
from agent.runtime.store import (
    ChatMessageRecord,
    ConfirmationRecord,
    ConversationRecord,
)
from agent.web.app import create_app


class FakeService:
    def __init__(self) -> None:
        self.chat_calls: list[tuple[str, str, str]] = []
        self.confirm_calls: list[tuple[str, str, bool]] = []
        self.history_calls: list[tuple[str, str | None]] = []
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def chat(
        self,
        *,
        session_id: str,
        owner_id: str,
        text: str,
        timezone: str,
        voice_confirmation: bool = False,
    ) -> ChatOutcome:
        self.chat_calls.append((session_id, owner_id, text))
        return ChatOutcome(
            status="needs_confirmation",
            message="确认写入吗？",
            confirmation=ConfirmationRecord(
                id="confirmation-1",
                session_id=session_id,
                owner_id=owner_id,
                state="pending",
                created_at="2026-07-21T00:00:00+00:00",
                expires_at="2026-07-21T00:05:00+00:00",
                tool_names=("create_feeding",),
                description="确认执行 Baby Buddy 操作：create_feeding？",
            ),
        )

    async def confirm(
        self,
        *,
        confirmation_id: str,
        owner_id: str,
        approved: bool,
    ) -> ChatOutcome:
        self.confirm_calls.append((confirmation_id, owner_id, approved))
        return ChatOutcome(status="completed", message="已记录。")

    def conversations(self, *, owner_id: str) -> list[ConversationRecord]:
        self.history_calls.append((owner_id, None))
        return [
            ConversationRecord(
                session_id="phone-parent-a",
                created_at="2026-07-21T00:00:00+00:00",
                updated_at="2026-07-21T00:01:00+00:00",
                title="宝宝刚喝了 120 毫升奶",
                message_count=2,
            )
        ]

    def conversation_messages(
        self,
        *,
        session_id: str,
        owner_id: str,
    ) -> list[ChatMessageRecord] | None:
        self.history_calls.append((owner_id, session_id))
        if session_id != "phone-parent-a":
            return None
        return [
            ChatMessageRecord(
                id="message-1",
                session_id=session_id,
                owner_id=owner_id,
                role="user",
                content="宝宝刚喝了 120 毫升奶",
                status=None,
                created_at="2026-07-21T00:00:00+00:00",
            ),
            ChatMessageRecord(
                id="message-2",
                session_id=session_id,
                owner_id=owner_id,
                role="assistant",
                content="确认写入吗？",
                status="needs_confirmation",
                created_at="2026-07-21T00:00:01+00:00",
            ),
        ]

    async def today(self, *, owner_id: str) -> TodaySnapshot:
        return TodaySnapshot(
            last_feeding="10:30 配方奶 120 ml",
            sleep_status="未在睡眠",
            diaper_count=3,
            recent_records=["10:30 喂奶 120 ml"],
        )


def _settings(tmp_path) -> Settings:
    return Settings(
        model_provider="ollama",
        api_key="http://localhost:11434",
        web_password="family-password",
        web_session_secret="x" * 32,
        web_database_path=str(tmp_path / "service.sqlite3"),
        ha_token="ha-shared-token",
    )


def test_health_is_public_and_does_not_use_agent_runtime(tmp_path) -> None:
    service = FakeService()
    app = create_app(_settings(tmp_path), service=service)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert service.chat_calls == []
    assert service.confirm_calls == []


def test_phone_api_requires_login_and_gates_confirmation(tmp_path) -> None:
    service = FakeService()
    app = create_app(_settings(tmp_path), service=service)

    with TestClient(app) as client:
        assert client.get("/api/today").status_code == 401
        assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
        assert (
            client.post("/api/login", json={"password": "family-password"}).status_code
            == 200
        )

        chat = client.post(
            "/api/chat",
            json={
                "session_id": "phone-parent-a",
                "text": "宝宝刚喝了 120 毫升奶",
                "timezone": "Asia/Shanghai",
            },
        )
        assert chat.status_code == 200
        assert chat.json()["status"] == "needs_confirmation"
        assert chat.json()["confirmation_id"] == "confirmation-1"

        confirmation = client.post(
            "/api/confirm",
            json={
                "confirmation_id": "confirmation-1",
                "approved": True,
                "timezone": "Asia/Shanghai",
            },
        )
        assert confirmation.json() == {"status": "completed", "message": "已记录。"}
        assert service.confirm_calls[0][0] == "confirmation-1"
        assert service.confirm_calls[0][2] is True

        today = client.get("/api/today")
        assert today.json()["diaper_count"] == 3
        assert client.get("/").status_code == 404

    assert service.started is True
    assert service.stopped is True


def test_conversation_history_requires_login_and_uses_cookie_owner(tmp_path) -> None:
    service = FakeService()
    app = create_app(_settings(tmp_path), service=service)

    with TestClient(app) as client:
        assert client.get("/api/conversations").status_code == 401
        assert (
            client.get("/api/conversations/phone-parent-a/messages").status_code == 401
        )
        client.post("/api/login", json={"password": "family-password"})
        owner = client.get("/api/session").json()["owner_id"]

        conversations = client.get("/api/conversations")
        messages = client.get("/api/conversations/phone-parent-a/messages")
        missing = client.get("/api/conversations/another-owner/messages")

    assert conversations.json() == {
        "conversations": [
            {
                "session_id": "phone-parent-a",
                "created_at": "2026-07-21T00:00:00+00:00",
                "updated_at": "2026-07-21T00:01:00+00:00",
                "title": "宝宝刚喝了 120 毫升奶",
                "message_count": 2,
            }
        ]
    }
    assert messages.json()["messages"] == [
        {
            "id": "message-1",
            "session_id": "phone-parent-a",
            "role": "user",
            "content": "宝宝刚喝了 120 毫升奶",
            "status": None,
            "created_at": "2026-07-21T00:00:00+00:00",
        },
        {
            "id": "message-2",
            "session_id": "phone-parent-a",
            "role": "assistant",
            "content": "确认写入吗？",
            "status": "needs_confirmation",
            "created_at": "2026-07-21T00:00:01+00:00",
        },
    ]
    assert missing.status_code == 404
    assert service.history_calls == [
        (owner, None),
        (owner, "phone-parent-a"),
        (owner, "another-owner"),
    ]


def test_api_rejects_cross_origin_mutations(tmp_path) -> None:
    app = create_app(_settings(tmp_path), service=FakeService())

    with TestClient(app) as client:
        response = client.post(
            "/api/login",
            headers={"origin": "https://untrusted.example"},
            json={"password": "family-password"},
        )

    assert response.status_code == 403


def test_home_assistant_chat_uses_its_own_token_and_session(tmp_path) -> None:
    service = FakeService()
    app = create_app(_settings(tmp_path), service=service)

    with TestClient(app) as client:
        assert client.post("/chat", json={"text": "记录喂奶"}).status_code == 401

        response = client.post(
            "/chat",
            headers={"authorization": "Bearer ha-shared-token"},
            json={
                "text": "宝宝刚喝了 120 毫升奶",
                "conversation_id": "living-room-voice",
                "timezone": "Asia/Shanghai",
                "user_id": "parent-a",
            },
        )
        assert response.status_code == 200
        assert response.json()["reply"] == "确认写入吗？"
        assert response.json()["conversation_id"] == "living-room-voice"
        assert response.json()["confirmation_id"] == "confirmation-1"
        assert service.chat_calls[0][0].startswith("ha-session-")
        assert service.chat_calls[0][1].startswith("ha-owner-")

        confirmation = client.post(
            "/api/ha/chat",
            headers={"x-agent-ha-token": "ha-shared-token"},
            json={
                "text": "确认",
                "conversation_id": "living-room-voice",
                "confirmation_id": "confirmation-1",
                "approved": True,
                "user_id": "parent-a",
            },
        )
        assert confirmation.json() == {
            "reply": "已记录。",
            "conversation_id": "living-room-voice",
            "status": "completed",
            "message": "已记录。",
        }
        assert service.confirm_calls[0] == (
            "confirmation-1",
            service.chat_calls[0][1],
            True,
        )


def test_audio_is_reserved_for_a_later_transcription_service(tmp_path) -> None:
    app = create_app(_settings(tmp_path), service=FakeService())

    with TestClient(app) as client:
        client.post("/api/login", json={"password": "family-password"})
        response = client.post("/api/audio", json={})

    assert response.status_code == 501
    assert response.json()["status"] == "audio_not_configured"
