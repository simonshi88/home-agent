"""AgentScope MCP client construction and lifecycle helpers."""

from __future__ import annotations

from typing import Any

from .config import Settings
from .errors import MCPConnectionError


def build_mcp_client(settings: Settings) -> Any:
    """Create the BabyBuddy MCP client using AgentScope's HTTP adapter."""
    from agentscope.mcp import HttpMCPConfig, MCPClient

    config = HttpMCPConfig(
        url=settings.mcp_url,
        timeout=settings.mcp_timeout,
    )
    return MCPClient(
        name="babybuddy",
        is_stateful=settings.mcp_stateful,
        mcp_config=config,
        enable_tools=list(settings.mcp_enable_tools) or None,
        disable_tools=list(settings.mcp_disable_tools) or None,
    )


async def connect_mcp(client: Any) -> None:
    """Connect a stateful client; stateless clients need no handshake here."""
    try:
        await client.connect()
    except Exception as exc:  # AgentScope transports expose provider errors.
        raise MCPConnectionError(
            "Unable to connect to the BabyBuddy MCP server",
        ) from exc


async def list_mcp_tools(client: Any) -> tuple[str, ...]:
    """Return the exposed MCP tool names without exposing tool arguments."""
    try:
        tools = await client.list_raw_tools()
    except Exception as exc:
        raise MCPConnectionError("Unable to discover BabyBuddy MCP tools") from exc
    return tuple(tool.name for tool in tools)


def build_toolkit(client: Any) -> Any:
    """Create the AgentScope Toolkit that owns the MCP tool registration."""
    from agentscope.tool import Toolkit

    return Toolkit(mcps=[client])


async def close_mcp(client: Any) -> None:
    """Close a stateful MCP client and tolerate already-closed transports."""
    if not getattr(client, "is_stateful", False):
        return
    if not getattr(client, "is_connected", False):
        return
    await client.close()
