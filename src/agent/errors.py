"""Application-specific errors."""


class AgentApplicationError(RuntimeError):
    """Base error for the application."""


class ConfigurationError(AgentApplicationError):
    """Raised when required configuration is missing or invalid."""


class MCPConnectionError(AgentApplicationError):
    """Raised when the configured MCP endpoint cannot be reached."""
