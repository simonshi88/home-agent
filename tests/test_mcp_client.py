from __future__ import annotations

import pytest

pytest.importorskip("agentscope")

from agent.config import Settings  # noqa: E402
from agent.mcp_client import build_mcp_client, build_toolkit  # noqa: E402


def test_build_mcp_client_uses_streamable_http() -> None:
    settings = Settings(api_key="test-key")
    client = build_mcp_client(settings)

    assert client.name == "babybuddy"
    assert client.is_stateful is True
    assert client.mcp_config.type == "http_mcp"
    assert client.mcp_config.url == settings.mcp_url


def test_toolkit_owns_mcp_client() -> None:
    # AgentScope requires stateful MCP clients to be connected before they
    # enter a Toolkit. Stateless HTTP clients are suitable for this assembly
    # unit test; connection lifecycle is covered separately.
    settings = Settings(api_key="test-key", mcp_stateful=False)
    client = build_mcp_client(settings)
    toolkit = build_toolkit(client)

    assert toolkit.tool_groups[0].mcps[0] is client
