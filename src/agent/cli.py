"""Interactive CLI for the generic AgentScope agent."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from dotenv import load_dotenv

from .agent import build_agent
from .audit import AuditLogger
from .chat import Conversation
from .config import Settings
from .errors import AgentApplicationError
from .mcp_client import (
    build_mcp_client,
    build_toolkit,
    close_mcp,
    connect_mcp,
    list_mcp_tools,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AgentScope agent")
    parser.add_argument(
        "--once",
        metavar="MESSAGE",
        help="send one message and exit",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration without connecting to the MCP server",
    )
    return parser


def _tool_summary(tool_call: Any) -> str:
    try:
        value = json.loads(tool_call.input)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, json.JSONDecodeError):
        return str(tool_call.input)


async def _confirm(tool_calls: tuple[Any, ...]) -> list[bool]:
    print("\n需要确认的工具调用：")
    for tool_call in tool_calls:
        print(f"工具：{tool_call.name}")
        print(f"参数：{_tool_summary(tool_call)[:1200]}")
    answer = await asyncio.to_thread(
        input,
        "确认执行全部调用？输入 y 确认，其他输入拒绝 [y/N]：",
    )
    confirmed = answer.strip().lower() in {"y", "yes"}
    return [confirmed] * len(tool_calls)


def _emit(event: Any) -> None:
    from agentscope.event import (
        ReplyEndEvent,
        TextBlockDeltaEvent,
        ToolCallStartEvent,
        ToolResultStartEvent,
    )

    if isinstance(event, TextBlockDeltaEvent):
        print(event.delta, end="", flush=True)
    elif isinstance(event, ToolCallStartEvent):
        print(f"\n[调用工具] {event.tool_call_name}", flush=True)
    elif isinstance(event, ToolResultStartEvent):
        print(f"\n[工具结果] {event.tool_call_id}", flush=True)
    elif isinstance(event, ReplyEndEvent):
        print(flush=True)


async def _run(settings: Settings, once: str | None) -> None:
    client = build_mcp_client(settings)
    await connect_mcp(client)
    try:
        tools = await list_mcp_tools(client)
        print(f"已连接 MCP：{settings.mcp_url}")
        print(f"可用工具：{', '.join(tools) if tools else '无'}")

        toolkit = build_toolkit(client)
        agent = build_agent(settings, toolkit)
        conversation = Conversation(
            agent=agent,
            user_name=settings.user_name,
            audit=AuditLogger(settings.audit_path),
        )

        if once is not None:
            await conversation.reply(once, confirm=_confirm, emit=_emit)
            return

        print("输入 :quit 退出，输入 :help 查看命令。")
        while True:
            try:
                text = await asyncio.to_thread(input, "你：")
            except EOFError:
                print()
                return
            text = text.strip()
            if not text:
                continue
            if text in {":quit", ":exit"}:
                return
            if text == ":help":
                print(":help 查看帮助；:quit 退出。")
                continue
            await conversation.reply(text, confirm=_confirm, emit=_emit)
    finally:
        await close_mcp(client)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    load_dotenv()
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.check_config:
            print(
                "配置有效："
                f" provider={settings.model_provider},"
                f" model={settings.model_name},"
                f" mcp={settings.mcp_url}",
            )
            return 0
        asyncio.run(_run(settings, args.once))
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except AgentApplicationError as exc:
        print(f"配置或运行失败：{exc}")
        return 2
    except Exception as exc:  # Keep CLI output useful without exposing secrets.
        print(f"运行失败：{type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
