"""Browser-safe mapping for AgentScope's event stream."""

from __future__ import annotations


def stream_event(event: object) -> dict[str, object] | None:
    """Map AgentScope blocks, tools and HITL events to the web protocol."""
    event_type = type(event).__name__
    common = {
        "reply_id": str(getattr(event, "reply_id", "")),
        "block_id": str(getattr(event, "block_id", "")),
    }
    lifecycle = {
        "TextBlockStartEvent": "text_start",
        "TextBlockEndEvent": "text_end",
        "ThinkingBlockStartEvent": "thinking_start",
        "ThinkingBlockEndEvent": "thinking_end",
        "DataBlockEndEvent": "data_end",
    }
    if event_type in lifecycle:
        return {"type": lifecycle[event_type], **common}
    deltas = {
        "TextBlockDeltaEvent": "text_delta",
        "ThinkingBlockDeltaEvent": "thinking_delta",
    }
    if event_type in deltas:
        return {
            "type": deltas[event_type],
            **common,
            "delta": str(getattr(event, "delta", "")),
        }
    if event_type in {"DataBlockStartEvent", "DataBlockDeltaEvent"}:
        payload = {
            "type": "data_start" if event_type.endswith("StartEvent") else "data_delta",
            **common,
            "media_type": str(getattr(event, "media_type", "")),
        }
        if event_type == "DataBlockDeltaEvent":
            payload["data"] = str(getattr(event, "data", ""))
        return payload
    if event_type == "ToolCallStartEvent":
        return {
            "type": "tool_start",
            "tool_call_id": str(getattr(event, "tool_call_id", "")),
            "tool_name": str(getattr(event, "tool_call_name", "tool")),
        }
    if event_type in {"ToolCallDeltaEvent", "ToolResultTextDeltaEvent"}:
        return {
            "type": (
                "tool_args_delta"
                if event_type == "ToolCallDeltaEvent"
                else "tool_result_delta"
            ),
            "tool_call_id": str(getattr(event, "tool_call_id", "")),
            "delta": str(getattr(event, "delta", "")),
        }
    if event_type == "ToolResultStartEvent":
        return {
            "type": "tool_result_start",
            "tool_call_id": str(getattr(event, "tool_call_id", "")),
        }
    if event_type == "ToolResultEndEvent":
        state = getattr(event, "state", "success")
        return {
            "type": "tool_result_end",
            "tool_call_id": str(getattr(event, "tool_call_id", "")),
            "state": str(getattr(state, "value", state)).lower(),
        }
    if event_type in {"RequireUserConfirmEvent", "RequireExternalExecutionEvent"}:
        return {
            "type": "human_required",
            "kind": "confirmation"
            if event_type == "RequireUserConfirmEvent"
            else "external_execution",
            "tool_call_ids": [
                str(getattr(call, "id", ""))
                for call in getattr(event, "tool_calls", [])
            ],
        }
    if event_type == "HintBlockEvent":
        return {
            "type": "hint",
            **common,
            "source": getattr(event, "source", None),
            "hint": str(getattr(event, "hint", "")),
        }
    return None
