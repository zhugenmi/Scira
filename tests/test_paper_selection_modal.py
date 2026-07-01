"""论文检索弹窗与可观测性增强的后端单元测试。"""
from unittest.mock import patch, MagicMock
from typing import Any


def _fake_search_results() -> list[dict[str, Any]]:
    return [
        {"paper_id": "1", "title": "T1", "authors": ["A"], "abstract": "abs",
         "pdf_url": "http://x/a.pdf", "published_date": "2024-01-01", "source": "arxiv"},
        {"paper_id": "2", "title": "T2", "authors": ["B"], "abstract": "abs",
         "pdf_url": "", "published_date": "2023-02-02", "source": "semantic"},
    ]


def test_pending_papers_carry_source_and_has_pdf(tmp_path, monkeypatch):
    """retrieval_node 构建的 pending_download_papers 每条须含 source 与 has_pdf_link。"""
    from src.core import workflow as wf
    from src.core.state import GraphState

    # 准备最小 state：search_results 已填充，category 已确定
    state: GraphState = {
        "user_query": "diffusion",
        "research_topic": "diffusion",
        "auto_approve": True,
        "workflow_mode": "search",
        "human_approvals": {},
        "current_phase": "retrieval",
        "error_messages": [],
        "retry_count": 0,
        "search_results": _fake_search_results(),
        "current_category": "diffusion",
        "pdfs_dir": str(tmp_path),
    }

    captured: list[dict[str, Any]] = []

    def fake_emit(phase, progress=None, message=None, details=None):
        if phase == "paper_download_approval_request":
            captured.append(details or {})

    monkeypatch.setattr(wf, "_emit_progress", fake_emit)

    # 只跑"构建 pending + 推 approval 事件"那段：直接调一个抽出来的 helper
    pending = wf.build_pending_download_papers(state, pdfs_dir=tmp_path)

    assert len(pending) == 1, "仅 1 篇有 pdf_url 应进入 pending"
    p = pending[0]
    assert p["paper_id"] == "1"
    assert p["source"] == "arxiv"
    assert p["has_pdf_link"] is True


def test_approval_event_carries_categories(tmp_path, monkeypatch):
    """approval 事件 details 须含 matched_category 与 existing_categories。"""
    from src.core import workflow as wf

    state = {
        "user_query": "diffusion", "research_topic": "diffusion",
        "auto_approve": True, "workflow_mode": "search",
        "human_approvals": {}, "current_phase": "retrieval",
        "error_messages": [], "retry_count": 0,
        "search_results": _fake_search_results(),
        "current_category": "diffusion",
        "pdfs_dir": str(tmp_path),
    }
    captured: list[dict[str, Any]] = []

    def fake_emit(phase, progress=None, message=None, details=None):
        if phase == "paper_download_approval_request":
            captured.append(details or {})

    monkeypatch.setattr(wf, "_emit_progress", fake_emit)
    monkeypatch.setattr(wf, "list_existing_categories", lambda _papers_dir: ["diffusion", "gnn"])

    wf.attach_approval_categories(state, papers_dir=tmp_path)
    wf.build_pending_download_papers(state, pdfs_dir=tmp_path)  # 确保 pending 已建

    # state 被填充
    assert state["pending_matched_category"] == "diffusion"
    assert state["pending_categories"] == ["diffusion", "gnn"]
