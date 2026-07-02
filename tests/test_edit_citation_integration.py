"""Integration test scaffolding for edit-citation SSE path.

This is intentionally a placeholder test. The real SSE path requires a running
FastAPI TestClient + mock LLM + mock external retrieval, which is deferred until
the server/test infrastructure supports it. This test documents the coverage gap
and serves as a baseline to confirm the test infrastructure works.
"""

import json
from unittest.mock import MagicMock, patch

from src.mcp.server import edit_citation_state, _clear_edit_state


def _fake_llm_stream(chunks):
    """Return a mock stream that yields MagicMock chunks with .content."""

    def _stream(messages):
        for c in chunks:
            m = MagicMock()
            m.content = c
            yield m

    return _stream


def test_integration_scaffolding_placeholder():
    """Placeholder — confirms test infrastructure works.

    Full SSE-path integration tests (KB hit / KB miss / search failure) require
    FastAPI TestClient + mock orchestrator + mock retrieval, which is deferred.
    The manual verification checklist at tests/manual_edit_citation_checklist.md
    covers the three end-to-end scenarios.
    """
    sid = "int-placeholder"

    try:
        fake_papers = [
            {
                "paper_id": "p1",
                "title": "RAG",
                "authors": ["A"],
                "published_date": "2024-01-01",
                "topic": "rag",
                "pdf_url": "",
            }
        ]

        with patch(
            "src.core.kb_context.search_papers_for_citation",
            return_value=fake_papers,
        ), patch(
            "src.core.kb_context.build_kb_directory_summary",
            return_value="系统知识库：1 个分类 / 1 篇。",
        ), patch(
            "src.agents.orchestrator.create_orchestrator"
        ) as mock_orch:

            mock_orch.return_value.llm.stream = _fake_llm_stream(["我列出了候选，请确认"])

            # Verify the patches are active (placeholder assertion)
            from src.core.kb_context import search_papers_for_citation
            from src.core.kb_context import build_kb_directory_summary

            candidates = search_papers_for_citation("RAG", 5)
            assert candidates == fake_papers

            summary = build_kb_directory_summary()
            assert "1 个分类" in summary

            edit_citation_state[sid] = {
                "phase": "candidates_listed",
                "candidates": candidates,
                "pending_topic": "RAG",
                "pending_count": 5,
            }

            assert edit_citation_state[sid]["phase"] == "candidates_listed"
            assert len(edit_citation_state[sid]["candidates"]) == 1

    finally:
        _clear_edit_state(sid)
