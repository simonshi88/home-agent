from __future__ import annotations

from types import SimpleNamespace

from agent.agents.team import build_home_jarvis_team
from agent.audit import AuditLogger
from agent.config import Settings


async def test_home_jarvis_team_keeps_tools_on_specialists(
    tmp_path,
    monkeypatch,
) -> None:
    settings = Settings(api_key="test-key")
    baby_client = SimpleNamespace(
        name="babybuddy",
        is_stateful=False,
        is_connected=True,
    )
    captured = {}

    monkeypatch.setattr(
        "agent.agents.team.build_mcp_clients",
        lambda value: (baby_client,),
    )

    async def connect(clients):
        return tuple(clients), ()

    monkeypatch.setattr("agent.agents.team.connect_available_mcp", connect)

    def build(settings, toolkit, *, name, **kwargs):
        captured[name] = toolkit
        return SimpleNamespace(name=name)

    monkeypatch.setattr("agent.agents.team.build_agent", build)

    team = await build_home_jarvis_team(
        settings,
        AuditLogger(tmp_path / "audit.jsonl"),
    )

    leader_tools = captured["home_jarvis"].tool_groups[0].tools
    baby_group = captured["baby_specialist"].tool_groups[0]
    exercise_group = captured["exercise_specialist"].tool_groups[0]
    paperless_group = captured["paperless_specialist"].tool_groups[0]
    assert [tool.name for tool in leader_tools] == [
        "delegate_to_baby",
        "delegate_to_exercise",
        "delegate_to_paperless",
    ]
    assert baby_group.tools == []
    assert baby_group.mcps == [baby_client]
    assert [tool.name for tool in exercise_group.tools] == ["query_exercises"]
    assert exercise_group.mcps == []
    assert [tool.name for tool in paperless_group.tools] == [
        "query_paperless",
        "upload_paperless_document",
    ]
    assert paperless_group.mcps == []
    assert team.clients == (baby_client,)
