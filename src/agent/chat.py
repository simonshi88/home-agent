"""Conversation orchestration on top of AgentScope's reply stream."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from .audit import AuditLogger

ConfirmationCallback = Callable[
    [tuple[Any, ...]],
    Sequence[bool] | Awaitable[Sequence[bool]],
]


class Conversation:
    """Keep one AgentScope Agent and its context for one conversation."""

    def __init__(
        self,
        agent: Any,
        user_name: str,
        audit: AuditLogger | None = None,
    ) -> None:
        self.agent = agent
        self.user_name = user_name
        self.audit = audit
        self._lock = asyncio.Lock()

    async def reply(
        self,
        text: str,
        confirm: ConfirmationCallback,
        emit: Callable[[Any], Any] | None = None,
    ) -> str:
        """Reply to one user turn, handling grouped AgentScope confirmations."""
        from agentscope.event import (
            ConfirmResult,
            RequireUserConfirmEvent,
            TextBlockDeltaEvent,
            UserConfirmResultEvent,
        )
        from agentscope.message import UserMsg

        async with self._lock:
            inputs: Any = UserMsg(name=self.user_name, content=text)
            output: list[str] = []
            while True:
                pending_events: list[RequireUserConfirmEvent] = []
                async for event in self.agent.reply_stream(inputs):
                    if emit is not None:
                        result = emit(event)
                        if inspect.isawaitable(result):
                            await result
                    if isinstance(event, TextBlockDeltaEvent):
                        output.append(event.delta)
                    elif isinstance(event, RequireUserConfirmEvent):
                        # A concurrent tool batch can emit one confirmation
                        # event per call.  The stream must be fully consumed:
                        # AgentScope does not emit the unhandled events again
                        # when the reply is resumed.
                        pending_events.append(event)

                if not pending_events:
                    break

                reply_ids = {event.reply_id for event in pending_events}
                if len(reply_ids) != 1:
                    raise RuntimeError(
                        "confirmation events from one reply have different ids",
                    )
                unique_calls: dict[str, Any] = {}
                for event in pending_events:
                    for tool_call in event.tool_calls:
                        unique_calls.setdefault(tool_call.id, tool_call)
                tool_calls = tuple(unique_calls.values())
                for tool_call in tool_calls:
                    if self.audit:
                        self.audit.tool_call(tool_call)

                decisions = confirm(tool_calls)
                if inspect.isawaitable(decisions):
                    decisions = await decisions
                confirmed_calls = tuple(bool(decision) for decision in decisions)
                if len(confirmed_calls) != len(tool_calls):
                    raise ValueError(
                        "confirmation callback must decide every tool call",
                    )

                confirmations = []
                for tool_call, confirmed in zip(
                    tool_calls,
                    confirmed_calls,
                    strict=True,
                ):
                    if self.audit:
                        self.audit.tool_call(
                            tool_call,
                            decision="allow" if confirmed else "deny",
                        )
                    confirmations.append(
                        ConfirmResult(
                            confirmed=confirmed,
                            tool_call=tool_call,
                        ),
                    )

                inputs = UserConfirmResultEvent(
                    reply_id=next(iter(reply_ids)),
                    confirm_results=confirmations,
                )

            reply = "".join(output)
            if self.audit:
                self.audit.log(
                    "assistant_reply",
                    text_sha256=_sha256(reply),
                    text_length=len(reply),
                )
            return reply


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
