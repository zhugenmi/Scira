"""KBQAAgent 单元测试。"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.kb_qa import KBQAAgent


@pytest.fixture
def fake_papers_readings():
    return [
        {
            "paper_id": "p1",
            "title": "Paper One",
            "markdown": "## 深度精读报告\n### 4.1 数据集\nImageNet-1K, 1.2M images.\n### 4.3 实验设置\nbatch=256",
        },
        {
            "paper_id": "p2",
            "title": "Paper Two",
            "markdown": "## 深度精读报告\n### 4.1 数据集\n_论文未明确提及_",
        },
    ]


def _patch_llm_invoke(mock_response_content: str):
    """构造一个 mock LLM，invoke 返回指定 content。"""
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = mock_response_content
    mock_llm.invoke.return_value = mock_resp
    return mock_llm


def _patch_llm_invoke_raises(exc: Exception):
    """构造一个 mock LLM，invoke 抛出指定异常。"""
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = exc
    return mock_llm


def test_synthesize_parses_valid_json(fake_papers_readings):
    valid_json = json.dumps({
        "synthesis": "Paper One 用了 ImageNet-1K (1.2M images)",
        "incomplete_papers": [
            {"paper_id": "p2", "title": "Paper Two", "missing": "数据集名称未提及"}
        ],
        "search_keywords": ["dataset", "ImageNet", "数据集"],
    }, ensure_ascii=False)
    mock_llm = _patch_llm_invoke(valid_json)

    with patch("src.agents.base.get_llm_client", return_value=mock_llm):
        agent = KBQAAgent()
        result = agent.synthesize("哪些论文用了公开数据集", fake_papers_readings)

    assert "Paper One" in result["synthesis"]
    assert len(result["incomplete_papers"]) == 1
    assert result["incomplete_papers"][0]["paper_id"] == "p2"
    assert "ImageNet" in result["search_keywords"]


def test_synthesize_degrades_on_invalid_json(fake_papers_readings):
    """LLM 返回非 JSON 时降级为 raw 文本 synthesis，incomplete_papers 空。"""
    mock_llm = _patch_llm_invoke("这不是 JSON，只是一段普通文本回答。")

    with patch("src.agents.base.get_llm_client", return_value=mock_llm):
        agent = KBQAAgent()
        result = agent.synthesize("哪些论文用了公开数据集", fake_papers_readings)

    assert "普通文本回答" in result["synthesis"]
    assert result["incomplete_papers"] == []
    assert result["search_keywords"] == []


def test_synthesize_strips_markdown_code_fence(fake_papers_readings):
    """LLM 用 ```json 包裹 JSON 时应正确解析。"""
    fenced = "```json\n" + json.dumps({
        "synthesis": "答案",
        "incomplete_papers": [],
        "search_keywords": ["dataset"],
    }, ensure_ascii=False) + "\n```"
    mock_llm = _patch_llm_invoke(fenced)

    with patch("src.agents.base.get_llm_client", return_value=mock_llm):
        agent = KBQAAgent()
        result = agent.synthesize("问题", fake_papers_readings)

    assert result["synthesis"] == "答案"
    assert result["search_keywords"] == ["dataset"]


def test_final_merge_returns_string():
    """final_merge 应返回纯文本字符串。"""
    mock_llm = _patch_llm_invoke("这是合并后的最终答案。")

    with patch("src.agents.base.get_llm_client", return_value=mock_llm):
        agent = KBQAAgent()
        result = agent.final_merge(
            synthesis="初步答案",
            supplementary=[{"paper_id": "p2", "excerpts": ["dataset: COCO"]}],
            question="哪些论文用了公开数据集",
        )

    assert isinstance(result, str)
    assert "最终答案" in result


def test_synthesize_degrades_on_llm_exception(fake_papers_readings):
    """LLM invoke 抛异常时 synthesize 应返回降级 dict 而不崩溃。"""
    mock_llm = _patch_llm_invoke_raises(RuntimeError("LLM unavailable"))

    with patch("src.agents.base.get_llm_client", return_value=mock_llm):
        agent = KBQAAgent()
        result = agent.synthesize("哪些论文用了公开数据集", fake_papers_readings)

    assert "整合分析失败" in result["synthesis"]
    assert "LLM unavailable" in result["synthesis"]
    assert result["incomplete_papers"] == []
    assert result["search_keywords"] == []


def test_final_merge_returns_synthesis_on_llm_exception():
    """LLM invoke 抛异常时 final_merge 应原样返回 synthesis 而不崩溃。"""
    mock_llm = _patch_llm_invoke_raises(RuntimeError("LLM unavailable"))

    with patch("src.agents.base.get_llm_client", return_value=mock_llm):
        agent = KBQAAgent()
        result = agent.final_merge(
            synthesis="初步答案",
            supplementary=[],
            question="哪些论文用了公开数据集",
        )

    assert result == "初步答案"