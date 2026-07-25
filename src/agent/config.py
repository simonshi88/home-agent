"""Environment-driven application configuration."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import ConfigurationError


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean, got {value!r}")


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return parsed


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return parsed


def _csv(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = os.getenv(name)
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class WebSettings:
    """Validated settings required only by the LAN web service."""

    host: str
    port: int
    password: str
    session_secret: str
    database_path: str
    confirmation_ttl: int
    allowed_origins: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    """Configuration for one AgentScope runtime."""

    model_provider: str = "anthropic"
    model_name: str = "claude-opus-4-8"
    model_stream: bool = True
    max_iters: int = 20
    api_key: str | None = None
    base_url: str | None = None
    ollama_host: str = "http://localhost:11434"
    mcp_url: str = "http://192.168.5.13:2001/mcp"
    mcp_timeout: float = 30.0
    mcp_stateful: bool = True
    mcp_enable_tools: tuple[str, ...] = ()
    mcp_disable_tools: tuple[str, ...] = ()
    mcp_allowed_hosts: tuple[str, ...] = (
        "192.168.5.13",
        "localhost",
        "127.0.0.1",
    )
    user_name: str = "user"
    audit_path: str = "var/audit/events.jsonl"
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_password: str | None = None
    web_session_secret: str | None = None
    web_database_path: str = "var/agent-web.sqlite3"
    web_confirmation_ttl: int = 300
    web_allowed_origins: tuple[str, ...] = ()
    web_read_tool_allowlist: tuple[str, ...] = ()
    ha_token: str | None = None
    ha_timezone: str = "Asia/Shanghai"

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings without exposing any secret values."""
        provider = os.getenv("AGENTSCOPE_MODEL_PROVIDER", "anthropic").strip().lower()
        supported = {"anthropic", "deepseek", "dashscope", "openai", "ollama"}
        if provider not in supported:
            raise ConfigurationError(
                f"AGENTSCOPE_MODEL_PROVIDER must be one of {sorted(supported)}",
            )

        key_name = {
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
            "openai": "OPENAI_API_KEY",
            "ollama": "OLLAMA_HOST",
        }[provider]
        api_key = os.getenv(key_name)
        if provider != "ollama" and not api_key:
            raise ConfigurationError(
                f"{key_name} is required when provider={provider!r}",
            )

        mcp_url = os.getenv("BABYBUDDY_MCP_URL", cls.mcp_url).strip()
        parsed = urlparse(mcp_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError(
                "BABYBUDDY_MCP_URL must be an http(s) URL with a hostname",
            )

        allowed_hosts = _csv("BABYBUDDY_MCP_ALLOWED_HOSTS", cls.mcp_allowed_hosts)
        if parsed.hostname not in allowed_hosts:
            raise ConfigurationError(
                "BABYBUDDY_MCP_URL host is not in BABYBUDDY_MCP_ALLOWED_HOSTS",
            )

        return cls(
            model_provider=provider,
            model_name=os.getenv("AGENTSCOPE_MODEL_NAME", cls.model_name).strip(),
            model_stream=_bool("AGENTSCOPE_MODEL_STREAM", cls.model_stream),
            max_iters=_int("AGENTSCOPE_MAX_ITERS", cls.max_iters),
            api_key=api_key,
            base_url=os.getenv("ANTHROPIC_BASE_URL")
            if provider == "anthropic"
            else os.getenv("DEEPSEEK_BASE_URL")
            if provider == "deepseek"
            else os.getenv("DASHSCOPE_BASE_URL")
            if provider == "dashscope"
            else os.getenv("OPENAI_BASE_URL")
            if provider == "openai"
            else None,
            ollama_host=os.getenv("OLLAMA_HOST", cls.ollama_host),
            mcp_url=mcp_url,
            mcp_timeout=_float("BABYBUDDY_MCP_TIMEOUT", cls.mcp_timeout),
            mcp_stateful=_bool("BABYBUDDY_MCP_STATEFUL", cls.mcp_stateful),
            mcp_enable_tools=_csv("BABYBUDDY_MCP_ENABLE_TOOLS"),
            mcp_disable_tools=_csv("BABYBUDDY_MCP_DISABLE_TOOLS"),
            mcp_allowed_hosts=allowed_hosts,
            user_name=os.getenv("BABYBUDDY_USER_NAME", cls.user_name),
            audit_path=os.getenv("BABYBUDDY_AUDIT_PATH", cls.audit_path),
            web_host=os.getenv("AGENT_WEB_HOST", cls.web_host).strip(),
            web_port=_int("AGENT_WEB_PORT", cls.web_port),
            web_password=os.getenv("AGENT_WEB_PASSWORD"),
            web_session_secret=os.getenv("AGENT_WEB_SESSION_SECRET"),
            web_database_path=os.getenv(
                "AGENT_WEB_DATABASE_PATH",
                cls.web_database_path,
            ),
            web_confirmation_ttl=_int(
                "AGENT_WEB_CONFIRMATION_TTL",
                cls.web_confirmation_ttl,
            ),
            web_allowed_origins=_csv("AGENT_WEB_ALLOWED_ORIGINS"),
            web_read_tool_allowlist=_csv("AGENT_WEB_READ_TOOL_ALLOWLIST"),
            ha_token=os.getenv("AGENT_HA_TOKEN"),
            ha_timezone=os.getenv("AGENT_HA_TIMEZONE", cls.ha_timezone).strip(),
        )

    def web_settings(self) -> WebSettings:
        """Return web settings, rejecting incomplete or public bind configuration."""
        if not self.web_password:
            raise ConfigurationError("AGENT_WEB_PASSWORD is required for agent-web")
        if not self.web_session_secret or len(self.web_session_secret) < 4:
            raise ConfigurationError(
                "AGENT_WEB_SESSION_SECRET must contain at least 4 characters",
            )
        if self.web_host != "0.0.0.0":
            try:
                address = ipaddress.ip_address(self.web_host)
            except ValueError as exc:
                raise ConfigurationError(
                    "AGENT_WEB_HOST must be 0.0.0.0 or a private/loopback IP address",
                ) from exc
            if not address.is_private and not address.is_loopback:
                raise ConfigurationError(
                    "AGENT_WEB_HOST must be a private or loopback IP address",
                )
        return WebSettings(
            host=self.web_host,
            port=self.web_port,
            password=self.web_password,
            session_secret=self.web_session_secret,
            database_path=self.web_database_path,
            confirmation_ttl=self.web_confirmation_ttl,
            allowed_origins=self.web_allowed_origins,
        )
