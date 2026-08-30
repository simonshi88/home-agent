from __future__ import annotations

import pytest

from agent.config import Settings
from agent.errors import ConfigurationError


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = Settings.from_env()

    assert settings.model_provider == "anthropic"
    assert settings.model_name == "claude-opus-4-8"
    assert settings.mcp_url == "http://192.168.5.13:2001/mcp"
    assert settings.mcp_stateful is True
    assert settings.database_url.endswith("/ExerciseDB")
    assert settings.babybuddy_media_url == "http://baby.home"
    assert settings.paperless_url == "http://paperless.home"
    assert settings.paperless_api_token is None


def test_babybuddy_media_url_must_be_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BABYBUDDY_MEDIA_URL", "file:///tmp/media")

    with pytest.raises(ConfigurationError, match="BABYBUDDY_MEDIA_URL"):
        Settings.from_env()


def test_paperless_url_must_be_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("PAPERLESS_URL", "file:///documents")

    with pytest.raises(ConfigurationError, match="PAPERLESS_URL"):
        Settings.from_env()


def test_database_url_must_be_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///exercise.db")

    with pytest.raises(ConfigurationError, match="PostgreSQL"):
        Settings.from_env()


def test_provider_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        Settings.from_env()


def test_mcp_host_is_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BABYBUDDY_MCP_URL", "http://example.invalid/mcp")

    with pytest.raises(ConfigurationError, match="ALLOWED_HOSTS"):
        Settings.from_env()


def test_provider_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTSCOPE_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("AGENTSCOPE_MODEL_NAME", "qwen2.5")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")

    settings = Settings.from_env()

    assert settings.model_provider == "ollama"
    assert settings.model_name == "qwen2.5"
    assert settings.api_key == settings.ollama_host


def test_web_settings_require_password_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = Settings.from_env()

    with pytest.raises(ConfigurationError, match="AGENT_WEB_PASSWORD"):
        settings.web_settings()

    monkeypatch.setenv("AGENT_WEB_PASSWORD", "family-password")
    monkeypatch.setenv("AGENT_WEB_SESSION_SECRET", "123")
    with pytest.raises(ConfigurationError, match="AGENT_WEB_SESSION_SECRET"):
        Settings.from_env().web_settings()

    monkeypatch.setenv("AGENT_WEB_SESSION_SECRET", "1234")
    assert Settings.from_env().web_settings().session_secret == "1234"
