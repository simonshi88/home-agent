"""Construct AgentScope model adapters without coupling the app to a provider."""

from __future__ import annotations

from typing import Any

from .config import Settings
from .errors import ConfigurationError


def build_chat_model(settings: Settings) -> Any:
    """Build an AgentScope chat model for the configured provider."""
    from agentscope.credential import (
        AnthropicCredential,
        DashScopeCredential,
        DeepSeekCredential,
        OllamaCredential,
        OpenAICredential,
    )
    from agentscope.model import (
        AnthropicChatModel,
        DashScopeChatModel,
        DeepSeekChatModel,
        OllamaChatModel,
        OpenAIChatModel,
    )

    common: dict[str, Any] = {
        "model": settings.model_name,
        "stream": settings.model_stream,
    }

    if settings.model_provider == "anthropic":
        credential = AnthropicCredential(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )
        return AnthropicChatModel(credential=credential, **common)

    if settings.model_provider == "deepseek":
        credential = DeepSeekCredential(
            api_key=settings.api_key,
            base_url=settings.base_url or "https://api.deepseek.com",
        )
        return DeepSeekChatModel(credential=credential, **common)

    if settings.model_provider == "dashscope":
        credential = DashScopeCredential(
            api_key=settings.api_key,
            base_url=settings.base_url
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        return DashScopeChatModel(credential=credential, **common)

    if settings.model_provider == "openai":
        credential = OpenAICredential(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )
        return OpenAIChatModel(credential=credential, **common)

    if settings.model_provider == "ollama":
        credential = OllamaCredential(host=settings.ollama_host)
        return OllamaChatModel(credential=credential, **common)

    raise ConfigurationError(
        f"Unsupported model provider: {settings.model_provider!r}",
    )
