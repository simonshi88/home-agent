"""AgentScope MCP client construction and lifecycle helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
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


def build_mcp_clients(settings: Settings) -> tuple[Any, ...]:
    """Create configured MCP clients. Exercise data intentionally is not MCP."""
    return (build_mcp_client(settings),)


def _is_inner_cancellation() -> bool:
    """Report whether a caught CancelledError came from an inner cancel scope.

    The MCP SDK runs its transport in an anyio task group and unwinds by
    cancelling the *current* task when the HTTP request fails (for example a
    502 from a reverse proxy). ``Task.cancelling()`` is therefore always
    positive here and cannot tell the two cases apart. ``Task.uncancel()``
    can: it returns the remaining cancellation count, so a zero result means
    no outer scope is still waiting for this task to stop.
    """
    task = asyncio.current_task()
    return task is not None and task.uncancel() == 0


async def connect_mcp(client: Any) -> None:
    """Connect a stateful client; stateless clients need no handshake here."""
    try:
        await client.connect()
    except asyncio.CancelledError:
        # A failed transport surfaces as CancelledError, which is a
        # BaseException and would otherwise escape as an unhandled 500.
        if not _is_inner_cancellation():
            raise
        raise MCPConnectionError(
            f"Unable to connect to the {client.name!r} MCP server",
        ) from None
    except Exception as exc:  # AgentScope transports expose provider errors.
        raise MCPConnectionError(
            f"Unable to connect to the {client.name!r} MCP server",
        ) from exc


async def connect_available_mcp(
    clients: Sequence[Any],
) -> tuple[tuple[Any, ...], tuple[str, ...]]:
    """Connect each client independently, tolerating individual outages.

    Returns the clients that connected and the names of the ones that did not,
    so one unreachable MCP server cannot take down every conversation. Raises
    only when no configured server is reachable at all.
    """
    connected: list[Any] = []
    unavailable: list[str] = []
    for client in clients:
        try:
            await connect_mcp(client)
        except MCPConnectionError:
            unavailable.append(str(client.name))
        else:
            connected.append(client)
    if not connected:
        raise MCPConnectionError(
            f"No MCP server is reachable: {', '.join(unavailable)}",
        )
    return tuple(connected), tuple(unavailable)


async def list_mcp_tools(client: Any) -> tuple[str, ...]:
    """Return the exposed MCP tool names without exposing tool arguments."""
    try:
        tools = await client.list_raw_tools()
    except asyncio.CancelledError:
        if not _is_inner_cancellation():
            raise
        raise MCPConnectionError(
            f"Unable to discover {client.name!r} MCP tools",
        ) from None
    except Exception as exc:
        raise MCPConnectionError(
            f"Unable to discover {client.name!r} MCP tools",
        ) from exc
    return tuple(tool.name for tool in tools)


def build_baby_toolkit(clients: Sequence[Any]) -> Any:
    """Create the Baby specialist Toolkit; no other domain tools belong here."""
    from agentscope.tool import Toolkit

    return Toolkit(mcps=list(clients))


async def close_mcp(client: Any) -> None:
    """Close a stateful MCP client and tolerate already-closed transports."""
    if not getattr(client, "is_stateful", False):
        return
    if not getattr(client, "is_connected", False):
        return
    await client.close()


async def close_all_mcp(clients: Sequence[Any]) -> None:
    """Close every client, tolerating transports that already tore themselves down."""
    for client in clients:
        try:
            await close_mcp(client)
        except asyncio.CancelledError:
            if not _is_inner_cancellation():
                raise
        except Exception:  # Cleanup must not mask the original failure.
            pass
