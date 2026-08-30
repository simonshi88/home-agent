"""Static Home Jarvis leader/specialist team for the lightweight runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentscope.tool import FunctionTool, Toolkit

from ..agent import build_agent
from ..audit import AuditLogger
from ..chat import ConfirmationCallback, Conversation
from ..config import Settings
from ..exercise_tool import build_exercise_tool
from ..mcp_client import build_baby_toolkit, build_mcp_clients, connect_available_mcp
from ..paperless_tool import build_paperless_tools
from .prompts import BABY_PROMPT, EXERCISE_PROMPT, JARVIS_PROMPT, PAPERLESS_PROMPT


class TeamConversation:
    """Leader conversation whose delegation preserves child events and HITL."""

    def __init__(
        self,
        leader: Conversation,
        specialists: dict[str, Conversation],
    ) -> None:
        self.leader = leader
        self.specialists = specialists
        self._confirm: ConfirmationCallback | None = None
        self._emit: Any | None = None

    async def reply(self, text: str, confirm: ConfirmationCallback, emit=None) -> str:
        self._confirm = confirm
        self._emit = emit
        try:
            return await self.leader.reply(text, confirm=confirm, emit=emit)
        finally:
            self._confirm = None
            self._emit = None

    async def delegate(self, specialist: str, task: str) -> str:
        """Run a specialist inside the current leader turn."""
        if self._confirm is None:
            raise RuntimeError("specialist delegation requires an active turn")
        return await self.specialists[specialist].reply(
            task,
            confirm=self._confirm,
            emit=self._emit,
        )


@dataclass
class HomeJarvisTeam:
    """One session-scoped leader and its capability-isolated specialists."""

    conversation: TeamConversation
    clients: tuple[Any, ...]
    unavailable: tuple[str, ...]


async def build_home_jarvis_team(
    settings: Settings,
    audit: AuditLogger,
    *,
    leader_state: Any | None = None,
    owner_id: str = "local",
    voice: bool = False,
) -> HomeJarvisTeam:
    """Build one isolated Home Jarvis team for a logical conversation."""
    clients = build_mcp_clients(settings)
    clients, unavailable = await connect_available_mcp(clients)

    baby = Conversation(
        build_agent(
            settings,
            build_baby_toolkit(clients),
            name="baby_specialist",
            system_prompt=BABY_PROMPT,
        ),
        settings.user_name,
        audit,
    )
    exercise = Conversation(
        build_agent(
            settings,
            Toolkit(tools=[build_exercise_tool(settings.database_url)]),
            name="exercise_specialist",
            system_prompt=EXERCISE_PROMPT,
        ),
        settings.user_name,
        audit,
    )
    paperless = Conversation(
        build_agent(
            settings,
            Toolkit(tools=build_paperless_tools(settings, owner_id)),
            name="paperless_specialist",
            system_prompt=PAPERLESS_PROMPT,
        ),
        settings.user_name,
        audit,
    )

    holder: dict[str, TeamConversation] = {}

    async def delegate_to_baby(task: str) -> str:
        """把育儿、BabyBuddy 查询或记录任务交给 Baby 专项 Agent。"""
        return await holder["team"].delegate("baby", task)

    async def delegate_to_exercise(task: str) -> str:
        """把动作资料、器械或目标肌群查询交给 Exercise 专项 Agent。"""
        return await holder["team"].delegate("exercise", task)

    async def delegate_to_paperless(task: str) -> str:
        """把家庭文档查询、分类或上传任务交给 Paperless 专项 Agent。"""
        return await holder["team"].delegate("paperless", task)

    leader_tools = Toolkit(
        tools=[
            FunctionTool(delegate_to_baby, is_read_only=True),
            FunctionTool(delegate_to_exercise, is_read_only=True),
            FunctionTool(delegate_to_paperless, is_read_only=True),
        ],
    )
    leader = Conversation(
        build_agent(
            settings,
            leader_tools,
            name="home_jarvis",
            system_prompt=JARVIS_PROMPT,
            state=leader_state,
        ),
        settings.user_name,
        audit,
    )
    team_conversation = TeamConversation(
        leader,
        {"baby": baby, "exercise": exercise, "paperless": paperless},
    )
    holder["team"] = team_conversation
    return HomeJarvisTeam(team_conversation, clients, unavailable)
