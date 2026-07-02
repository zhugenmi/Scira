# tests/test_kb_context.py
from unittest.mock import patch
from src.core.kb_context import build_kb_directory_summary


def test_build_kb_directory_summary_normal():
    fake = {
        "categories": [
            {"name": "rag", "topic": "RAG最新进展", "count": 5, "papers": []},
            {"name": "diffusion", "topic": "扩散模型", "count": 8, "papers": []},
        ],
        "total_papers": 13,
        "total_categories": 2,
    }
    with patch("src.core.kb_context.list_knowledge_bases", return_value=fake):
        s = build_kb_directory_summary()
    assert "2 个分类" in s
    assert "13 篇论文" in s
    assert "RAG最新进展" in s
    assert "扩散模型" in s


def test_build_kb_directory_summary_empty():
    with patch("src.core.kb_context.list_knowledge_bases",
               return_value={"categories": [], "total_papers": 0, "total_categories": 0}):
        s = build_kb_directory_summary()
    assert s == ""


def test_build_kb_directory_summary_exception_returns_empty():
    with patch("src.core.kb_context.list_knowledge_bases", side_effect=RuntimeError("boom")):
        s = build_kb_directory_summary()
    assert s == ""
