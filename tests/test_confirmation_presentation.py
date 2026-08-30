from agent.web.app import _confirmation_presentation


def test_paperless_upload_confirmation_is_tool_specific() -> None:
    assert _confirmation_presentation(("upload_paperless_document",)) == {
        "title": "上传文档到 Paperless？",
        "confirm_label": "确认上传",
        "cancel_label": "取消",
        "severity": "warning",
    }


def test_baby_delete_confirmation_is_dangerous() -> None:
    result = _confirmation_presentation(
        ("mcp__babybuddy__notes_delete_note",),
    )

    assert result["title"] == "删除 Baby Buddy 数据？"
    assert result["confirm_label"] == "确认删除"
    assert result["severity"] == "danger"


def test_unknown_tool_never_pretends_to_be_babybuddy() -> None:
    result = _confirmation_presentation(("future_sensitive_tool",))

    assert result["title"] == "执行此工具操作？"
    assert result["confirm_label"] == "确认执行"
