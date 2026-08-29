from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("agentscope")

from agent.config import Settings  # noqa: E402
from agent.errors import MCPConnectionError  # noqa: E402
from agent.mcp_client import (  # noqa: E402
    build_baby_toolkit,
    build_mcp_client,
    build_mcp_clients,
    connect_available_mcp,
)


class _FakeClient:
    """Minimal stand-in for an AgentScope MCPClient connect handshake."""

    def __init__(self, name: str, error: BaseException | None = None) -> None:
        self.name = name
        self._error = error
        self.connected = False

    async def connect(self) -> None:
        if self._error is not None:
            raise self._error
        self.connected = True


async def test_connect_available_mcp_skips_unreachable_servers() -> None:
    healthy = _FakeClient("babybuddy")
    broken = _FakeClient("training", RuntimeError("502 Bad Gateway"))

    connected, unavailable = await connect_available_mcp((healthy, broken))

    assert connected == (healthy,)
    assert unavailable == ("training",)


async def test_connect_available_mcp_treats_transport_cancellation_as_an_outage() -> (
    None
):
    # The MCP SDK cancels the caller's scope when its HTTP request fails, which
    # surfaces as CancelledError rather than a normal exception.
    healthy = _FakeClient("babybuddy")
    broken = _FakeClient("training", asyncio.CancelledError())

    connected, unavailable = await connect_available_mcp((healthy, broken))

    assert connected == (healthy,)
    assert unavailable == ("training",)


async def test_connect_available_mcp_raises_when_nothing_is_reachable() -> None:
    clients = (
        _FakeClient("babybuddy", RuntimeError("down")),
        _FakeClient("training", RuntimeError("down")),
    )

    with pytest.raises(MCPConnectionError):
        await connect_available_mcp(clients)


def test_build_mcp_client_uses_streamable_http() -> None:
    settings = Settings(api_key="test-key")
    client = build_mcp_client(settings)

    assert client.name == "babybuddy"
    assert client.is_stateful is True
    assert client.mcp_config.type == "http_mcp"
    assert client.mcp_config.url == settings.mcp_url


def test_build_mcp_clients_returns_only_babybuddy() -> None:
    settings = Settings(api_key="test-key")
    clients = build_mcp_clients(settings)

    assert [client.name for client in clients] == ["babybuddy"]


def test_baby_toolkit_owns_only_mcp_clients() -> None:
    # AgentScope requires stateful MCP clients to be connected before they
    # enter a Toolkit. Stateless HTTP clients are suitable for this assembly
    # unit test; connection lifecycle is covered separately.
    settings = Settings(
        api_key="test-key",
        mcp_stateful=False,
    )
    clients = build_mcp_clients(settings)
    toolkit = build_baby_toolkit(clients)

    assert tuple(toolkit.tool_groups[0].mcps) == clients
    assert toolkit.tool_groups[0].tools == []
