from agent.prompts import SYSTEM_PROMPT


def test_prompt_requires_confirmation_and_truthful_results() -> None:
    assert "等待用户确认" in SYSTEM_PROMPT
    assert "不能说操作完成" not in SYSTEM_PROMPT
    assert "工具返回成功" in SYSTEM_PROMPT
    assert "刚才尿了" in SYSTEM_PROMPT
    assert "不要把澄清问题误当成写入确认" in SYSTEM_PROMPT
