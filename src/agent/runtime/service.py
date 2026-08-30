"""HTTP-facing orchestration without exposing model or MCP credentials."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..agents import build_home_jarvis_team
from ..audit import AuditLogger
from ..config import Settings
from ..errors import MCPConnectionError
from ..mcp_client import close_all_mcp
from .store import (
    ChatMessageRecord,
    ConfirmationRecord,
    ConversationRecord,
    ServiceStore,
)


class ServiceError(RuntimeError):
    """Base error intended for the HTTP adapter."""


class MCPUnavailableError(ServiceError):
    """Raised when a configured MCP server cannot be reached or connected."""


class BusySessionError(ServiceError):
    """Raised when a session has an unfinished chat turn."""


class ConfirmationStateError(ServiceError):
    """Raised when a confirmation cannot safely be resolved."""


@dataclass(frozen=True)
class ChatOutcome:
    """The API-safe result of a chat or confirmation operation."""

    status: str
    message: str
    confirmation: ConfirmationRecord | None = None


@dataclass
class _ConversationRuntime:
    conversation: Any
    clients: tuple[Any, ...]
    active_turn: "_TurnState | None" = None


@dataclass
class _TurnState:
    session_id: str
    owner_id: str
    response: asyncio.Future[ChatOutcome]
    persist_history: bool = False
    voice_confirmation: bool = False
    emit: Any | None = None
    task: asyncio.Task[None] | None = None


@dataclass
class _PendingExecution:
    record: ConfirmationRecord
    turn: _TurnState
    decision: asyncio.Future[bool]


@dataclass
class TodaySnapshot:
    """Best-effort, read-only view used by the phone dashboard."""

    last_feeding: str | None = None
    sleep_status: str | None = None
    diaper_count: int | None = None
    recent_records: list[str] = field(default_factory=list)
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_feeding": self.last_feeding,
            "sleep_status": self.sleep_status,
            "diaper_count": self.diaper_count,
            "recent_records": self.recent_records,
            "message": self.message,
        }


class AgentService:
    """Own live AgentScope state while persisting only safe service metadata."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.web_settings = settings.web_settings()
        self.store = ServiceStore(self.web_settings.database_path)
        self.audit = AuditLogger(settings.audit_path)
        self._conversations: dict[str, _ConversationRuntime] = {}
        self._pending: dict[str, _PendingExecution] = {}
        self._started = False

    async def start(self) -> None:
        """Invalidate stale work left by a prior process before accepting requests."""
        expired = self.store.expire_pending_confirmations()
        if expired:
            self.audit.log("confirmation_restart_expired", count=expired)
        self._started = True

    async def stop(self) -> None:
        """Cancel suspended turns before closing their isolated MCP transports."""
        runtimes = tuple(self._conversations.values())
        for runtime in runtimes:
            if runtime.active_turn and runtime.active_turn.task:
                runtime.active_turn.task.cancel()
        await asyncio.gather(
            *(
                runtime.active_turn.task
                for runtime in runtimes
                if runtime.active_turn and runtime.active_turn.task
            ),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(close_all_mcp(runtime.clients) for runtime in runtimes),
            return_exceptions=True,
        )
        self._conversations.clear()
        self._pending.clear()
        self._started = False

    async def chat(
        self,
        *,
        session_id: str,
        owner_id: str,
        text: str,
        timezone: str,
        voice_confirmation: bool = False,
        emit: Any | None = None,
    ) -> ChatOutcome:
        """Start one turn with server-derived local-time context."""
        self._require_started()
        self.store.ensure_session(session_id, owner_id)
        runtime = await self._runtime_for(
            session_id,
            owner_id=owner_id,
            voice_confirmation=voice_confirmation,
        )
        active_turn = runtime.active_turn
        if active_turn and active_turn.task and not active_turn.task.done():
            raise BusySessionError("this conversation is waiting for confirmation")

        response = asyncio.get_running_loop().create_future()
        turn = _TurnState(
            session_id=session_id,
            owner_id=owner_id,
            response=response,
            persist_history=not voice_confirmation,
            voice_confirmation=voice_confirmation,
            emit=emit,
        )
        if turn.persist_history:
            self.store.record_chat_message(
                session_id=session_id,
                owner_id=owner_id,
                role="user",
                content=text,
            )
        runtime.active_turn = turn
        turn.task = asyncio.create_task(
            self._run_turn(runtime, turn, _with_local_time(text, timezone)),
        )
        return await response

    async def confirm(
        self,
        *,
        confirmation_id: str,
        owner_id: str,
        approved: bool,
    ) -> ChatOutcome:
        """Resolve a single live confirmation, then wait for the next turn outcome."""
        pending = self._pending.get(confirmation_id)
        record = self.store.resolve_confirmation(
            confirmation_id,
            owner_id=owner_id,
            approved=approved,
        )
        if record is None:
            raise ConfirmationStateError("confirmation was not found")
        if record.state not in {"allowed", "denied"} or pending is None:
            raise ConfirmationStateError(
                "confirmation is expired, already used, or cannot survive a restart",
            )

        self._pending.pop(confirmation_id, None)
        response = asyncio.get_running_loop().create_future()
        pending.turn.response = response
        pending.decision.set_result(approved)
        self.audit.log(
            "confirmation_resolved",
            confirmation_id=record.id,
            session_id=record.session_id,
            decision="allow" if approved else "deny",
        )
        return await response

    async def today(self, *, owner_id: str) -> TodaySnapshot:
        """Collect a dashboard snapshot through read-only agent behavior."""
        self._require_started()
        try:
            team = await build_home_jarvis_team(self.settings, self.audit)
        except MCPConnectionError as exc:
            raise MCPUnavailableError(str(exc)) from exc
        if team.unavailable:
            self.audit.log("mcp_unavailable", servers=list(team.unavailable))
        try:

            async def allow_read_tools(tool_calls: tuple[Any, ...]) -> list[bool]:
                decisions = [
                    self._is_read_only_tool(str(tool_call.name))
                    for tool_call in tool_calls
                ]
                denied = [
                    str(tool_call.name)
                    for tool_call, allowed in zip(tool_calls, decisions, strict=True)
                    if not allowed
                ]
                if denied:
                    self.audit.log(
                        "today_non_read_tool_denied",
                        owner_id=owner_id,
                        tool_names=denied,
                    )
                return decisions

            reply = await team.conversation.reply(
                _TODAY_PROMPT,
                confirm=allow_read_tools,
            )
            return _parse_today_snapshot(reply)
        finally:
            await close_all_mcp(team.clients)

    def conversations(self, *, owner_id: str) -> list[ConversationRecord]:
        """List persisted browser conversations owned by the active cookie session."""
        self._require_started()
        return self.store.list_conversations(owner_id=owner_id)

    def conversation_messages(
        self,
        *,
        session_id: str,
        owner_id: str,
    ) -> list[ChatMessageRecord] | None:
        """List persisted messages only when the browser owns the conversation."""
        self._require_started()
        return self.store.list_chat_messages(
            session_id=session_id,
            owner_id=owner_id,
        )

    async def delete_conversation(self, *, session_id: str, owner_id: str) -> bool:
        """Remove an owned browser conversation and dispose of its live runtime."""
        self._require_started()
        if (
            self.store.list_chat_messages(
                session_id=session_id,
                owner_id=owner_id,
            )
            is None
        ):
            return False
        runtime = self._conversations.get(session_id)
        if runtime and runtime.active_turn and runtime.active_turn.task:
            runtime.active_turn.task.cancel()
            await asyncio.gather(runtime.active_turn.task, return_exceptions=True)
        for confirmation_id, pending in tuple(self._pending.items()):
            if pending.record.session_id == session_id:
                self._pending.pop(confirmation_id, None)
        runtime = self._conversations.pop(session_id, None)
        if runtime is not None:
            await close_all_mcp(runtime.clients)
        deleted = self.store.delete_conversation(
            session_id=session_id,
            owner_id=owner_id,
        )
        if deleted:
            self.audit.log("conversation_deleted", session_id=session_id)
        return deleted

    async def _runtime_for(
        self,
        session_id: str,
        *,
        owner_id: str,
        voice_confirmation: bool,
    ) -> _ConversationRuntime:
        runtime = self._conversations.get(session_id)
        if runtime is not None:
            return runtime
        from agentscope.message import AssistantMsg, UserMsg
        from agentscope.state import AgentState

        history = self.store.list_chat_messages(
            session_id=session_id,
            owner_id=owner_id,
        )
        context = []
        for message in history or []:
            if message.role == "user":
                context.append(
                    UserMsg(
                        name=self.settings.user_name,
                        content=message.content,
                        id=message.id,
                        created_at=message.created_at,
                    ),
                )
            elif message.status != "failed":
                context.append(
                    AssistantMsg(
                        name="agent",
                        content=message.content,
                        id=message.id,
                        created_at=message.created_at,
                    ),
                )
        agent_state = AgentState(session_id=session_id, context=context)
        try:
            team = await build_home_jarvis_team(
                self.settings,
                self.audit,
                leader_state=agent_state,
                owner_id=owner_id,
                voice=voice_confirmation,
            )
        except MCPConnectionError as exc:
            raise MCPUnavailableError(str(exc)) from exc
        if team.unavailable:
            self.audit.log(
                "mcp_unavailable",
                session_id=session_id,
                servers=list(team.unavailable),
            )
        runtime = _ConversationRuntime(team.conversation, team.clients)
        self._conversations[session_id] = runtime
        return runtime

    async def _run_turn(
        self,
        runtime: _ConversationRuntime,
        turn: _TurnState,
        text: str,
    ) -> None:
        try:
            reply_kwargs = {
                "confirm": (
                    self._auto_confirm_tools
                    if turn.voice_confirmation
                    else lambda calls: self._confirm_tools(turn, calls)
                ),
            }
            if turn.emit is not None:
                reply_kwargs["emit"] = turn.emit
            reply = await runtime.conversation.reply(text, **reply_kwargs)
            reply = _normalize_babybuddy_media_links(
                reply,
                self.settings.babybuddy_media_url,
            )
            outcome = ChatOutcome(status="completed", message=reply)
            self._set_response(turn, outcome)
            self._record_turn(turn, outcome)
        except asyncio.CancelledError:
            self._set_response(
                turn,
                ChatOutcome(status="failed", message="服务正在停止，请重新提交。"),
            )
            raise
        except Exception:
            self.audit.log("turn_failed", session_id=turn.session_id)
            outcome = ChatOutcome(
                status="failed",
                message="暂时无法处理请求，请稍后重试。",
            )
            self._set_response(turn, outcome)
            self._record_turn(turn, outcome)
        finally:
            if runtime.active_turn is turn:
                runtime.active_turn = None

    async def _auto_confirm_tools(self, tool_calls: tuple[Any, ...]) -> list[bool]:
        """Let the voice-agent prompt collect confirmation for BabyBuddy calls."""
        decisions = [
            str(tool_call.name).startswith("mcp__babybuddy__")
            or self._is_read_only_tool(str(tool_call.name))
            for tool_call in tool_calls
        ]
        self.audit.log(
            "voice_tools_auto_allowed",
            tool_names=[
                str(tool_call.name)
                for tool_call, allowed in zip(tool_calls, decisions, strict=True)
                if allowed
            ],
        )
        return decisions

    async def _confirm_tools(
        self,
        turn: _TurnState,
        tool_calls: tuple[Any, ...],
    ) -> list[bool]:
        """Allow a turn containing only known read tools without prompting."""
        if all(
            self._is_read_only_tool(str(tool_call.name)) for tool_call in tool_calls
        ):
            self.audit.log(
                "read_tools_auto_allowed",
                session_id=turn.session_id,
                tool_names=[str(tool_call.name) for tool_call in tool_calls],
            )
            return [True] * len(tool_calls)
        return await self._confirm_calls(turn, tool_calls)

    async def _confirm_calls(
        self,
        turn: _TurnState,
        tool_calls: tuple[Any, ...],
    ) -> list[bool]:
        tool_names = tuple(str(tool_call.name) for tool_call in tool_calls)
        record = self.store.create_confirmation(
            session_id=turn.session_id,
            owner_id=turn.owner_id,
            tool_names=tool_names,
            description=_confirmation_description(tool_names),
            ttl_seconds=self.web_settings.confirmation_ttl,
        )
        decision = asyncio.get_running_loop().create_future()
        self._pending[record.id] = _PendingExecution(
            record=record,
            turn=turn,
            decision=decision,
        )
        self.audit.log(
            "confirmation_pending",
            confirmation_id=record.id,
            session_id=turn.session_id,
            tool_names=list(tool_names),
        )
        self._set_response(
            turn,
            ChatOutcome(
                status="needs_confirmation",
                message=record.description,
                confirmation=record,
            ),
        )
        try:
            approved = await asyncio.wait_for(
                asyncio.shield(decision),
                timeout=self.web_settings.confirmation_ttl,
            )
        except TimeoutError:
            self._pending.pop(record.id, None)
            self.store.expire_confirmation(record.id)
            self.audit.log(
                "confirmation_expired",
                confirmation_id=record.id,
                session_id=turn.session_id,
            )
            return [False] * len(tool_calls)
        return [approved] * len(tool_calls)

    def _set_response(self, turn: _TurnState, outcome: ChatOutcome) -> None:
        if not turn.response.done():
            if turn.persist_history:
                self.store.record_chat_message(
                    session_id=turn.session_id,
                    owner_id=turn.owner_id,
                    role="assistant",
                    content=outcome.message,
                    status=outcome.status,
                )
            turn.response.set_result(outcome)

    def _record_turn(self, turn: _TurnState, outcome: ChatOutcome) -> None:
        encoded = outcome.message.encode("utf-8")
        self.store.record_turn(
            session_id=turn.session_id,
            owner_id=turn.owner_id,
            status=outcome.status,
            text_sha256=hashlib.sha256(encoded).hexdigest(),
            text_length=len(outcome.message),
        )

    def _is_read_only_tool(self, tool_name: str) -> bool:
        """Allow an explicit read allowlist or stable read verbs, never mutations."""
        if tool_name in self.settings.web_read_tool_allowlist:
            return True
        if tool_name in {
            "delegate_to_baby",
            "delegate_to_exercise",
            "delegate_to_paperless",
            "query_exercises",
            "query_paperless",
        }:
            return True
        return any(
            marker in tool_name
            for marker in ("_list_", "_get_", "_retrieve_", "_search_")
        )

    def _require_started(self) -> None:
        if not self._started:
            raise ServiceError("agent service has not started")


def _confirmation_description(tool_names: tuple[str, ...]) -> str:
    labels = "、".join(tool_names)
    if "upload_paperless_document" in tool_names:
        return "确认将这个文档上传到 Paperless？"
    return f"确认执行写入操作：{labels}？"


def _normalize_babybuddy_media_links(reply: str, public_origin: str) -> str:
    """Replace Baby Buddy's Docker-internal absolute media URLs."""
    return re.sub(
        r"https?://babybuddy(?::\d+)?(?=/media/)",
        public_origin.rstrip("/"),
        reply,
        flags=re.IGNORECASE,
    )


def _parse_today_snapshot(reply: str) -> TodaySnapshot:
    """Accept the requested JSON, but never manufacture missing Baby Buddy data."""
    try:
        parsed = json.loads(reply)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", reply, flags=re.DOTALL)
        if not match:
            return TodaySnapshot(message=reply or "暂时无法读取今日摘要。")
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return TodaySnapshot(message=reply or "暂时无法读取今日摘要。")
    if not isinstance(parsed, dict):
        return TodaySnapshot(message=reply or "暂时无法读取今日摘要。")
    diaper_count = parsed.get("diaper_count")
    if not isinstance(diaper_count, int):
        diaper_count = None
    recent = parsed.get("recent_records", [])
    if not isinstance(recent, list) or not all(
        isinstance(item, str) for item in recent
    ):
        recent = []
    return TodaySnapshot(
        last_feeding=_string_or_none(parsed.get("last_feeding")),
        sleep_status=_string_or_none(parsed.get("sleep_status")),
        diaper_count=diaper_count,
        recent_records=recent[:10],
        message=_string_or_none(parsed.get("message")) or "",
    )


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _with_local_time(text: str, timezone_name: str) -> str:
    local_time = datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name))
    return (
        "<trusted_runtime_context>\n"
        f"User timezone: {timezone_name}\n"
        f"Current server-derived local time: {local_time.isoformat()}\n"
        "Use this only to resolve relative times such as 'now' or 'just now'.\n"
        "</trusted_runtime_context>\n\n"
        f"<user_message>{text}</user_message>"
    )


_TODAY_PROMPT = """只读取 Baby Buddy 的真实数据，绝不创建、修改或删除记录。
请获取今天的摘要，并且只返回下列 JSON（不要 Markdown 或额外文字）：
{
  "last_feeding": "最近一次喂奶的时间、类型和量；没有则为 null",
  "sleep_status": "当前睡眠状态；没有则为 null",
  "diaper_count": 今天尿布次数，
  "recent_records": ["最近记录的简短列表"],
  "message": "可选的读取错误或说明"
}
若无法读取某项，使用 null 或 []，不要猜测数据。"""
