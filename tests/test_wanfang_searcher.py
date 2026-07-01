"""Tests for WanfangSearcher. All HTTP mocked — no real network."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Make paper_search_mcp discoverable as a top-level package
_MCP_DIR = Path(__file__).resolve().parents[1] / "src" / "mcp"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from src.mcp.paper_search_mcp.academic_platforms.wanfang import WanfangSearcher


def _fake_wanfang_response(docs: list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"numFound": len(docs), "documents": docs}
    resp.raise_for_status.return_value = None
    return resp


def test_wanfang_search_parses_documents_to_papers():
    searcher = WanfangSearcher(app_key="k", app_code="c")
    docs = [
        {
            "docId": "wf123",
            "title": "深度学习在医学影像中的应用",
            "authors": [{"name": "张三"}, {"name": "李四"}],
            "abstract": "本文综述了深度学习在医学影像分析中的进展。",
            "year": "2024",
            "doi": "10.1234/wf.123",
        },
    ]
    with patch("src.mcp.paper_search_mcp.academic_platforms.wanfang.requests.post") as mock_post:
        mock_post.return_value = _fake_wanfang_response(docs)
        papers = searcher.search("深度学习 医学", max_results=5)

    assert len(papers) == 1
    p = papers[0]
    assert p.paper_id == "wf123"
    assert p.title == "深度学习在医学影像中的应用"
    assert p.authors == ["张三", "李四"]
    assert p.abstract.startswith("本文综述")
    assert p.source == "wanfang"
    assert p.doi == "10.1234/wf.123"


def test_wanfang_search_empty_response():
    searcher = WanfangSearcher(app_key="k", app_code="c")
    with patch("src.mcp.paper_search_mcp.academic_platforms.wanfang.requests.post") as mock_post:
        mock_post.return_value = _fake_wanfang_response([])
        papers = searcher.search("nonexistent topic", max_results=5)
    assert papers == []


def test_wanfang_search_http_error_returns_empty():
    """Network/HTTP errors should not crash — return [] and let caller skip."""
    searcher = WanfangSearcher(app_key="k", app_code="c")
    with patch("src.mcp.paper_search_mcp.academic_platforms.wanfang.requests.post") as mock_post:
        mock_post.side_effect = Exception("timeout")
        papers = searcher.search("anything", max_results=5)
    assert papers == []


def test_wanfang_search_missing_fields_handled():
    """Docs missing optional fields should still parse."""
    searcher = WanfangSearcher(app_key="k", app_code="c")
    docs = [{"docId": "wf456", "title": "标题"}]  # no authors/abstract/year/doi
    with patch("src.mcp.paper_search_mcp.academic_platforms.wanfang.requests.post") as mock_post:
        mock_post.return_value = _fake_wanfang_response(docs)
        papers = searcher.search("query", max_results=5)
    assert len(papers) == 1
    assert papers[0].paper_id == "wf456"
    assert papers[0].authors == []
    assert papers[0].abstract == ""


def test_wanfang_download_pdf_not_supported():
    """v1: wanfang is metadata-only; download must raise NotImplementedError."""
    searcher = WanfangSearcher(app_key="k", app_code="c")
    with pytest.raises(NotImplementedError):
        searcher.download_pdf("wf123", "/tmp")
