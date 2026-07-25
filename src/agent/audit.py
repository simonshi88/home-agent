"""Append-only, redacted audit logging for tool activity."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _args_metadata(raw_input: str) -> dict[str, Any]:
    digest = hashlib.sha256(raw_input.encode("utf-8")).hexdigest()
    try:
        parsed = json.loads(raw_input)
    except json.JSONDecodeError:
        return {"args_sha256": digest, "args_type": "invalid_json"}
    if isinstance(parsed, dict):
        return {"args_sha256": digest, "arg_keys": sorted(parsed)}
    return {"args_sha256": digest, "args_type": type(parsed).__name__}


class AuditLogger:
    """Write redacted JSONL records without persisting tool values."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def log(self, event: str, **fields: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def tool_call(self, tool_call: Any, decision: str | None = None) -> None:
        fields = {
            "tool_name": tool_call.name,
            "tool_call_id": tool_call.id,
            **_args_metadata(tool_call.input),
        }
        if decision is not None:
            fields["decision"] = decision
        self.log("tool_call", **fields)
