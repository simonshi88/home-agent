"""AgentScope Agent assembly."""

from __future__ import annotations

from typing import Any

from .config import Settings
from .model_factory import build_chat_model
from .prompts import SYSTEM_PROMPT


def build_agent(
    settings: Settings,
    toolkit: Any,
    *,
    system_prompt: str = SYSTEM_PROMPT,
) -> Any:
    """Build one reusable AgentScope Agent for a logical conversation."""
    from agentscope.agent import Agent, ModelConfig, ReActConfig

    return Agent(
        name="agent",
        system_prompt=system_prompt,
        model=build_chat_model(settings),
        toolkit=toolkit,
        model_config=ModelConfig(max_retries=1),
        react_config=ReActConfig(
            max_iters=settings.max_iters,
            stop_on_reject=False,
        ),
    )
