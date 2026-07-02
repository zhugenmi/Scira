# tests/test_kb_context.py
from unittest.mock import patch
from src.core.kb_context import build_kb_directory_summary, search_papers_for_citation, format_citation_candidates


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


def test_search_papers_for_citation_normal():
    fake = [
        {"paper_id": "p1", "title": "Paper A", "authors": ["Alice", "Bob"],
         "published_date": "2024-05-01", "topic": "rag", "pdf_url": "http://x"},
        {"paper_id": "p2", "title": "Paper B", "authors": "Carol; Dan",
         "published_date": "2025-01-01", "topic": "rag", "pdf_url": ""},
    ]
    with patch("src.core.kb_context.search_papers", return_value=fake):
        result = search_papers_for_citation("rag", 5)
    assert len(result) == 2
    assert result[0]["index"] == 1
    assert result[0]["paper_id"] == "p1"
    assert result[1]["authors"] == ["Carol", "Dan"]  # 字符串被拆成 list


def test_search_papers_for_citation_empty():
    with patch("src.core.kb_context.search_papers", return_value=[]):
        assert search_papers_for_citation("nothing", 5) == []


def test_search_papers_for_citation_exception():
    with patch("src.core.kb_context.search_papers", side_effect=RuntimeError("db")):
        assert search_papers_for_citation("x", 5) == []


def test_format_citation_candidates():
    papers = [
        {"index": 1, "paper_id": "p1", "title": "Paper A",
         "authors": ["Alice", "Bob"], "published_date": "2024-05-01"},
        {"index": 2, "paper_id": "p2", "title": "Paper B",
         "authors": ["Carol"], "published_date": "2025-01-01"},
    ]
    s = format_citation_candidates(papers)
    assert "[1]" in s and "Paper A" in s and "Alice" in s
    assert "[2]" in s and "Paper B" in s
    assert "p1" in s and "p2" in s


from src.core.kb_context import format_bibliography_gbt7714


def test_format_bibliography_gbt7714_normal():
    papers = [
        {"index": 1, "paper_id": "p1", "title": "Paper A",
         "authors": ["Alice", "Bob"], "published_date": "2024-05-01",
         "topic": "rag"},
        {"index": 2, "paper_id": "p2", "title": "Paper B",
         "authors": ["Carol", "Dan", "Eve", "Frank"], "published_date": "2025-01-01",
         "topic": "rag"},
    ]
    s = format_bibliography_gbt7714(papers)
    assert "## 参考文献" in s
    assert "[1]" in s and "Paper A" in s and "Alice" in s and "Bob" in s
    assert "[2]" in s and "Paper B" in s
    # 超过 3 作者用「等」
    assert "等" in s
    # 条目间空行
    assert "\n\n[2]" in s


def test_format_bibliography_gbt7714_empty():
    assert format_bibliography_gbt7714([]) == ""
