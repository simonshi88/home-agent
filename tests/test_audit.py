from __future__ import annotations

import json
from types import SimpleNamespace

from agent.audit import AuditLogger


def test_audit_redacts_tool_arguments(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    logger = AuditLogger(str(path))
    logger.tool_call(
        SimpleNamespace(
            id="call-1",
            name="create_record",
            input='{"name":"private value","count":1}',
        ),
        decision="deny",
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["tool_name"] == "create_record"
    assert record["decision"] == "deny"
    assert record["arg_keys"] == ["count", "name"]
    assert "private value" not in path.read_text(encoding="utf-8")
