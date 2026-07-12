"""answer_question_from_kb 工具注册与路由提示词测试。"""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage


def test_tool_registered_in_get_kb_reading_tools():
    """新工具应出现在 get_kb_reading_tools() 返回列表里。"""
    from src.agents.tools import get_kb_reading_tools
    names = [t.name for t in get_kb_reading_tools()]
    assert "answer_question_from_kb" in names


def test_tool_registered_in_tool_functions():
    from src.agents.tools import get_tool_by_name
    assert get_tool_by_name("answer_question_from_kb") is not None


def test_tool_args_validation():
    """工具函数本身只做参数校验，返回 status=streaming。"""
    from src.agents.tools import answer_question_from_kb
    import json
    result = json.loads(answer_question_from_kb.invoke({"kb_name": "多源数据融合", "question": "哪些用了公开数据集"}))
    assert result["status"] == "streaming"
    assert result["kb_name"] == "多源数据融合"


def test_tool_requires_question():
    """question 为空时应返回 error。"""
    from src.agents.tools import answer_question_from_kb
    import json
    result = json.loads(answer_question_from_kb.invoke({"kb_name": "X", "question": ""}))
    assert "error" in result


def _make_router_ai_msg(tool_name: str, tool_args: dict) -> AIMessage:
    """构造一个带 tool_calls 的 AIMessage mock。"""
    msg = MagicMock(spec=AIMessage)
    msg.content = ""
    msg.tool_calls = [{"name": tool_name, "args": tool_args, "id": "tc1", "type": "tool_call"}]
    return msg


@pytest.mark.integration
@pytest.mark.parametrize("user_msg,expected_tool", [
    ("多源数据融合知识库里哪些论文用了公开数据集", "answer_question_from_kb"),
    ("多源数据融合库中 Sensor Fusion 这篇论文用了什么方法", "answer_question_from_kb"),
    ("多源数据融合知识库哪些论文是 2023 年的", "answer_question_from_kb"),
    # 回归：以下不应被路由到 answer_question_from_kb
    ("用 snap 模式阅读多源数据融合知识库所有论文", "batch_read_papers_in_kb"),
    ("多源数据融合知识库有哪些论文", "list_papers_in_kb"),
    ("根据多源数据融合知识库写国内外研究现状", "generate_section_from_kb"),
])
def test_router_prompt_routes_correctly(user_msg, expected_tool):
    """用真实 LLM 验证 TOOL_ROUTER_SYSTEM 的路由判断。

    标记 integration 因为要调真实 LLM。不需要 fake KB -- LLM 只看 prompt +
    用户消息选工具，不实际执行工具。
    """
    from src.agents.base import BaseAgent
    from src.agents.prompts import TOOL_ROUTER_SYSTEM
    from src.agents.tools import get_kb_reading_tools

    agent = BaseAgent(name="tool_router_test", system_prompt=TOOL_ROUTER_SYSTEM)
    tools = get_kb_reading_tools()
    ai_msg = agent.invoke_with_tools(user_msg, tools)
    tool_calls = getattr(ai_msg, "tool_calls", None) or []
    assert len(tool_calls) >= 1, f"LLM 未调用工具，msg={user_msg}"
    assert tool_calls[0]["name"] == expected_tool, (
        f"msg={user_msg!r} 期望 {expected_tool}，实际 {tool_calls[0]['name']}"
    )