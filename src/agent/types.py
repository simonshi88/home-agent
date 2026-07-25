"""Small application-level types kept independent from AgentScope internals."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeInfo:
    """Runtime information safe to show in diagnostics."""

    provider: str
    model: str
    mcp_url: str
    mcp_tools: tuple[str, ...]
