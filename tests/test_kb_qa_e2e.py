"""KB 问答端到端测试。

用真实 LLM + 真实 KB 验证完整流程。需配置 OPENAI_API_KEY，标记 integration 默认跳过。
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _collect_sse_events(gen):
    """同步包装器：消费异步生成器的 SSE 事件字符串，返回解析后的事件列表。

    兼容 Python 3.12+（使用 asyncio.run() 而非已废弃的 get_event_loop()）。
    """
    events = []

    async def _consume():
        async for chunk in gen:
            if chunk.startswith("data: "):
                try:
                    events.append(json.loads(chunk[6:].strip()))
                except json.JSONDecodeError:
                    pass

    asyncio.run(_consume())
    return events


def test_e2e_multi_source_fusion_kb_dataset_question():
    """用「多源数据融合」KB 跑「哪些论文用了公开数据集」。

    前提：data/papers/ 下存在多源数据融合 KB，且有 PDF。
    """
    from src.mcp.server import _answer_question_from_kb_in_chat

    # 先确认 KB 存在
    from src.core.knowledge import list_knowledge_bases
    listing = list_knowledge_bases()
    cats = listing.get("categories", []) or []
    target = None
    for c in cats:
        topic = (c.get("topic") or "").lower()
        if "多源数据融合" in topic or "multi_source" in topic or "multi-source" in topic:
            target = c
            break
    if not target:
        pytest.skip("未找到多源数据融合知识库，跳过 E2E 测试")

    from unittest.mock import patch
    with patch("src.core.memory.memory_manager"):
        gen = _answer_question_from_kb_in_chat(
            "e2e-test-session",
            "多源数据融合",
            "哪些论文用了公开数据集进行实验？请给出数据集名称和量级。",
        )
        events = _collect_sse_events(gen)

    tokens = [e.get("data", {}).get("token", "") for e in events if e.get("type") == "token"]
    joined = "".join(tokens)

    # 不应出现旧的「将以速览模式逐篇阅读」刷屏式开头
    assert "将以速览模式逐篇阅读" not in joined, (
        "仍出现旧的速览模式逐篇阅读推送，路由或编排未生效"
    )
    # 应出现精读进度
    assert "精读" in joined or "lens" in joined.lower()
    # 应有最终整合答案（不能只是进度消息）
    assert len(joined) > 200, f"输出过短，可能只有进度消息：{joined[:200]}"
    # 最终答案里应提到「数据集」相关内容
    assert "数据集" in joined or "dataset" in joined.lower()


def test_e2e_routing_does_not_trigger_batch_read():
    """通过 _handle_tool_call_chat 验证路由层把问题路由到 answer_question_from_kb。

    而不是 batch_read_papers_in_kb。
    """
    from src.mcp.server import _handle_tool_call_chat
    from unittest.mock import patch

    async def _run():
        with patch("src.core.memory.memory_manager"):
            result = await _handle_tool_call_chat(
                "e2e-routing-test",
                "多源数据融合知识库里哪些论文用了公开数据集",
                [],
            )
        # result 是 async generator 或 None
        if result is None:
            pytest.fail("路由返回 None，未匹配到工具调用（应匹配 answer_question_from_kb）")

        events = []
        async for chunk in result:
            if chunk.startswith("data: "):
                try:
                    events.append(json.loads(chunk[6:].strip()))
                except json.JSONDecodeError:
                    pass
        return events

    events = asyncio.run(_run())

    tokens = [e.get("data", {}).get("token", "") for e in events if e.get("type") == "token"]
    joined = "".join(tokens)

    # 不应出现「将以速览模式逐篇阅读」
    assert "将以速览模式逐篇阅读" not in joined, "路由到了 batch_read_papers_in_kb（错误）"
    # 应出现新的编排流程开头
    assert "精读" in joined or "整合分析" in joined