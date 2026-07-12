"""_answer_question_from_kb_in_chat 编排层测试。

用 mock LLM + fake KB 验证 4 阶段流程串联正确。
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_kb_with_lens_cache(tmp_path, monkeypatch):
    """构造 fake KB，2 篇论文，每篇有预生成的 lens 精读缓存（避免真跑 LLM 精读）。"""
    from src.mcp import server as srv
    from src.core import knowledge as kmod

    cat_name = "test_kb"
    cat_dir = tmp_path / "data" / "papers" / cat_name
    p1_dir = cat_dir / "p1"
    p1_dir.mkdir(parents=True)
    (p1_dir / "p1.pdf").write_bytes(b"%PDF-1.4 fake")
    (p1_dir / "lens_zh.json").write_text(json.dumps({
        "markdown": "## 深度精读报告\n### 4.1 数据集\nImageNet-1K, 1.2M images.\n",
        "json": "{}",
        "from_cache": False,
    }, ensure_ascii=False), encoding="utf-8")

    p2_dir = cat_dir / "p2"
    p2_dir.mkdir()
    (p2_dir / "p2.pdf").write_bytes(b"%PDF-1.4 fake with dataset COCO inside")
    (p2_dir / "lens_zh.json").write_text(json.dumps({
        "markdown": "## 深度精读报告\n### 4.1 数据集\n_论文未明确提及_\n",
        "json": "{}",
        "from_cache": False,
    }, ensure_ascii=False), encoding="utf-8")

    papers = [
        {"paper_id": "p1", "title": "Paper One", "pdf_path": f"data/papers/{cat_name}/p1/p1.pdf"},
        {"paper_id": "p2", "title": "Paper Two", "pdf_path": f"data/papers/{cat_name}/p2/p2.pdf"},
    ]
    (cat_dir / f"{cat_name}.json").write_text(
        json.dumps({"category": cat_name, "topic": "测试库", "papers": papers}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "data" / "papers" / "all_papers.json").write_text(
        json.dumps({"total_papers": 2, "categories": {
            cat_name: {"path": str(cat_dir / f"{cat_name}.json"), "topic": "测试库", "count": 2}
        }}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(srv, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(kmod, "PAPERS_DIR", tmp_path / "data" / "papers")
    return tmp_path


async def _collect_events(gen):
    """消费 async generator，收集所有 SSE 事件。"""
    events = []
    async for chunk in gen:
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:].strip()))
    return events


@pytest.mark.asyncio
async def test_kb_not_found_returns_error(tmp_path, monkeypatch):
    """KB 不存在时应返回错误消息，不进入精读流程。"""
    from src.mcp import server as srv
    from src.core import knowledge as kmod
    monkeypatch.setattr(srv, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(kmod, "PAPERS_DIR", tmp_path / "empty")

    from src.mcp.server import _answer_question_from_kb_in_chat

    with patch("src.core.memory.memory_manager"):
        events = await _collect_events(
            _answer_question_from_kb_in_chat("sess1", "不存在的库", "问题")
        )

    tokens = [e.get("data", {}).get("token", "") for e in events if e.get("type") == "token"]
    joined = "".join(tokens)
    assert "未找到" in joined or "不存在" in joined


@pytest.mark.asyncio
async def test_orchestration_full_flow(fake_kb_with_lens_cache):
    """完整 4 阶段流程：精读(命中缓存) -> 整合 -> 补读 -> 合并。"""
    from src.mcp.server import _answer_question_from_kb_in_chat

    mock_agent = MagicMock()
    mock_agent.synthesize.return_value = {
        "synthesis": "Paper One 用了 ImageNet-1K",
        "incomplete_papers": [
            {"paper_id": "p2", "title": "Paper Two", "missing": "数据集未提及"}
        ],
        "search_keywords": ["dataset", "COCO", "数据集"],
    }
    mock_agent.final_merge.return_value = "最终答案：Paper One 用 ImageNet，Paper Two 用 COCO。"

    # mock KBQAAgent at source module since server.py does
    # "from src.agents.kb_qa import KBQAAgent" inside the function body
    with patch("src.agents.kb_qa.KBQAAgent", return_value=mock_agent), \
         patch("src.core.memory.memory_manager"):
        events = await _collect_events(
            _answer_question_from_kb_in_chat("sess1", "测试库", "哪些用了公开数据集")
        )

    tokens = [e.get("data", {}).get("token", "") for e in events if e.get("type") == "token"]
    joined = "".join(tokens)

    # 应有精读进度
    assert "精读" in joined or "lens" in joined.lower()
    # 应有补读提示（因为有 incomplete_papers）
    assert "补读" in joined
    # 应有最终答案
    assert "最终答案" in joined

    # KBQAAgent.synthesize 应被调用一次
    assert mock_agent.synthesize.call_count == 1
    # final_merge 应被调用一次（因为有 incomplete_papers）
    assert mock_agent.final_merge.call_count == 1


@pytest.mark.asyncio
async def test_orchestration_skips_final_merge_when_no_incomplete(fake_kb_with_lens_cache):
    """incomplete_papers 为空时跳过补读和 final_merge，直接用 synthesis。"""
    from src.mcp.server import _answer_question_from_kb_in_chat

    mock_agent = MagicMock()
    mock_agent.synthesize.return_value = {
        "synthesis": "所有论文都提到了数据集。",
        "incomplete_papers": [],
        "search_keywords": [],
    }
    mock_agent.final_merge.return_value = "不应被调用"

    with patch("src.agents.kb_qa.KBQAAgent", return_value=mock_agent), \
         patch("src.core.memory.memory_manager"):
        events = await _collect_events(
            _answer_question_from_kb_in_chat("sess1", "测试库", "哪些用了公开数据集")
        )

    # final_merge 不应被调用
    assert mock_agent.final_merge.call_count == 0

    tokens = [e.get("data", {}).get("token", "") for e in events if e.get("type") == "token"]
    joined = "".join(tokens)
    assert "所有论文都提到了数据集" in joined