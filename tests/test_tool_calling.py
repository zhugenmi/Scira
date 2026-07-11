"""tool-calling 路由与 KB 查询工具单元测试。

覆盖：
- list_papers_in_kb 的 KB 名匹配（精确/子串/未匹配 suggestions）
- invoke_with_tools 的 tool_call 分发与降级
- _find_kb_by_name 复用同款匹配逻辑
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.core.knowledge import list_knowledge_bases


def _make_category(papers_dir: Path, name: str, topic: str, papers: list):
    cat_dir = papers_dir / name
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / f"{name}.json").write_text(
        json.dumps(
            {"category": name, "topic": topic, "count": len(papers), "papers": papers},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return cat_dir / f"{name}.json"


@pytest.fixture
def fake_papers_dir(tmp_path, monkeypatch):
    """构造临时 papers 目录，含 2 个 KB。"""
    from src.core import knowledge as kmod

    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    _make_category(papers_dir, "knowledge_graph", "知识图谱", [
        {"paper_id": "kg1", "title": "KG Embedding", "authors": ["Alice"], "published_date": "2022-01-01"},
        {"paper_id": "kg2", "title": "KG Curation", "authors": ["Bob"], "published_date": "2023-02-02"},
    ])
    _make_category(papers_dir, "multi_source_fusion", "多源数据融合", [
        {"paper_id": "ms1", "title": "Sensor Fusion", "authors": ["Carol"], "published_date": "2024-03-03"},
        {"paper_id": "ms2", "title": "UAV Fault Detection", "authors": ["Dave"], "published_date": "2025-04-04"},
        {"paper_id": "ms3", "title": "Data Fusion Framework", "authors": ["Eve"], "published_date": "2026-05-05"},
    ])
    (papers_dir / "all_papers.json").write_text(json.dumps({
        "total_papers": 5,
        "categories": {
            "knowledge_graph": {"path": str(papers_dir / "knowledge_graph" / "knowledge_graph.json"), "topic": "知识图谱", "count": 2},
            "multi_source_fusion": {"path": str(papers_dir / "multi_source_fusion" / "multi_source_fusion.json"), "topic": "多源数据融合", "count": 3},
        },
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(kmod, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr("src.mcp.server.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.mcp.server.PROJECT_ROOT", tmp_path)
    return papers_dir


# ==================== list_papers_in_kb 工具 ====================

def test_list_papers_in_kb_chinese_topic_match(fake_papers_dir):
    """中文 topic 名应精确匹配到对应 KB。"""
    from src.agents.tools import list_papers_in_kb

    result = json.loads(list_papers_in_kb.invoke({"kb_name": "多源数据融合"}))
    assert result["matched"] is True
    assert result["count"] == 3
    assert result["topic"] == "多源数据融合"
    titles = [p["title"] for p in result["papers"]]
    assert "Sensor Fusion" in titles


def test_list_papers_in_kb_english_dir_name_match(fake_papers_dir):
    """英文目录名也应匹配。"""
    from src.agents.tools import list_papers_in_kb

    result = json.loads(list_papers_in_kb.invoke({"kb_name": "knowledge_graph"}))
    assert result["matched"] is True
    assert result["count"] == 2


def test_list_papers_in_kb_substring_match(fake_papers_dir):
    """子串匹配：'多源' 应匹配到 '多源数据融合'。"""
    from src.agents.tools import list_papers_in_kb

    result = json.loads(list_papers_in_kb.invoke({"kb_name": "多源"}))
    assert result["matched"] is True
    assert result["topic"] == "多源数据融合"


def test_list_papers_in_kb_no_match_returns_suggestions(fake_papers_dir):
    """未匹配时应返回 suggestions 列出所有可用 KB。"""
    from src.agents.tools import list_papers_in_kb

    result = json.loads(list_papers_in_kb.invoke({"kb_name": "不存在的库"}))
    assert result["matched"] is False
    assert "suggestions" in result
    suggestion_topics = [s["topic"] for s in result["suggestions"]]
    assert "多源数据融合" in suggestion_topics
    assert "知识图谱" in suggestion_topics


def test_list_papers_in_kb_empty_name(fake_papers_dir):
    """空 KB 名应返回错误。"""
    from src.agents.tools import list_papers_in_kb

    result = json.loads(list_papers_in_kb.invoke({"kb_name": ""}))
    assert result["matched"] is False
    assert "error" in result


# ==================== _find_kb_by_name ====================

def test_find_kb_by_name_returns_target(fake_papers_dir):
    """_find_kb_by_name 应返回分类字典（含 papers 列表）。"""
    from src.mcp.server import _find_kb_by_name

    target = _find_kb_by_name("多源数据融合")
    assert target is not None
    assert target.get("count") == 3
    assert len(target.get("papers") or []) == 3


def test_find_kb_by_name_returns_full_paper_fields(tmp_path, monkeypatch):
    """_find_kb_by_name 应读 category JSON 返回完整 paper 字段（含 pdf_path），

    而非 list_knowledge_bases() 的 stripped 版本。批量精读依赖 pdf_path 定位 PDF。
    """
    from src.core import knowledge as kmod
    from src.mcp.server import _find_kb_by_name

    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    _make_category(papers_dir, "test_kb", "测试库", [
        {
            "paper_id": "p1",
            "title": "Paper One",
            "authors": ["Alice"],
            "published_date": "2024-01-01",
            "pdf_path": "data/papers/test_kb/p1/p1.pdf",
            "abstract": "abs",
            "pdf_url": "http://example.com/p1.pdf",
        },
    ])
    (papers_dir / "all_papers.json").write_text(json.dumps({
        "total_papers": 1,
        "categories": {
            "test_kb": {"path": str(papers_dir / "test_kb" / "test_kb.json"), "topic": "测试库", "count": 1},
        },
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(kmod, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr("src.mcp.server.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.mcp.server.PROJECT_ROOT", tmp_path)

    target = _find_kb_by_name("测试库")
    assert target is not None
    papers = target.get("papers") or []
    assert len(papers) == 1
    # 关键：pdf_path 必须保留（list_knowledge_bases 会剥离）
    assert papers[0].get("pdf_path") == "data/papers/test_kb/p1/p1.pdf"
    assert papers[0].get("abstract") == "abs"


def test_find_kb_by_name_no_match_returns_none(fake_papers_dir):
    from src.mcp.server import _find_kb_by_name

    assert _find_kb_by_name("不存在的库") is None
    assert _find_kb_by_name("") is None
    assert _find_kb_by_name(None) is None


# ==================== invoke_with_tools ====================

class _FakeLLM:
    """模拟 LangChain chat model：支持 bind_tools 与 invoke。"""
    def __init__(self, response: AIMessage):
        self._response = response
        self.bind_tools_called = False

    def bind_tools(self, tools):
        self.bind_tools_called = True
        return self

    def invoke(self, messages, **kwargs):
        return self._response


def test_invoke_with_tools_returns_tool_calls(monkeypatch):
    """LLM 返回 tool_calls 时，invoke_with_tools 应原样透传。"""
    from src.agents.base import BaseAgent

    fake_tool_call = {
        "name": "list_papers_in_kb",
        "args": {"kb_name": "多源数据融合"},
        "id": "tc1",
        "type": "tool_call",
    }
    fake_resp = AIMessage(content="", tool_calls=[fake_tool_call])
    fake_llm = _FakeLLM(fake_resp)

    agent = BaseAgent(name="test", system_prompt="test")
    agent.llm = fake_llm

    result = agent.invoke_with_tools("列举多源数据融合的论文", tools=[])
    assert result is fake_resp
    assert result.tool_calls[0]["name"] == "list_papers_in_kb"
    assert fake_llm.bind_tools_called is True


def test_invoke_with_tools_no_tool_calls_returns_text(monkeypatch):
    """LLM 直接返回文本（无 tool_calls）时，调用方据此 fallthrough。"""
    from src.agents.base import BaseAgent

    fake_resp = AIMessage(content="你好，我是助手", tool_calls=[])
    fake_llm = _FakeLLM(fake_resp)

    agent = BaseAgent(name="test", system_prompt="test")
    agent.llm = fake_llm

    result = agent.invoke_with_tools("你好", tools=[])
    assert result.content == "你好，我是助手"
    assert not result.tool_calls


def test_invoke_with_tools_degrades_on_unsupported_bind(monkeypatch):
    """provider 不支持 bind_tools 时应降级到普通 invoke，不抛异常。"""
    from src.agents.base import BaseAgent

    class _NoBindLLM:
        def invoke(self, messages, **kwargs):
            return AIMessage(content="降级回复", tool_calls=[])

        def bind_tools(self, tools):
            raise NotImplementedError("provider 不支持 tool calling")

    agent = BaseAgent(name="test", system_prompt="test")
    agent.llm = _NoBindLLM()

    result = agent.invoke_with_tools("你好", tools=[])
    assert result.content == "降级回复"
    assert not result.tool_calls


# ==================== 工具注册表 ====================

def test_get_kb_reading_tools_returns_four():
    """工具注册表应返回 4 个工具。"""
    from src.agents.tools import get_kb_reading_tools

    tools = get_kb_reading_tools()
    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == {"list_knowledge_bases", "list_papers_in_kb", "read_paper", "batch_read_papers_in_kb"}
