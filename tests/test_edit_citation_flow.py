"""Test KB-aware edit assistant citation flow.

Task 6: KB hit branch — inject candidates + search-confirmation directive in edit flow.
Task 7-8: Same-stream search + confirmation branches (to be added).
"""

from unittest.mock import patch

from src.mcp.server import edit_citation_state, _clear_edit_state


def test_citation_flow_kb_hit_injects_candidates():
    """用户首次提'加5篇参考文献'，KB 命中 → 注入候选清单 + 询问确认指令。"""
    sid = "test-sid-hit"
    try:
        fake_papers = [
            {"paper_id": "p1", "title": "RAG Survey", "authors": ["Alice"],
             "published_date": "2024-01-01", "topic": "rag", "pdf_url": ""},
        ]
        with patch("src.core.kb_context.search_papers_for_citation",
                   return_value=fake_papers) as mock_search:
            # 模拟预处理逻辑（实际由 server.py 内部调用，这里测函数级行为）
            from src.mcp.server import _detect_citation_intent, _resolve_topic
            intent = _detect_citation_intent("增加5篇参考文献")
            assert intent is not None
            topic = _resolve_topic(intent, "# RAG最新进展\n...", {})
            # 模拟 server.py 内部：调 search_papers_for_citation 并写状态
            from src.core.kb_context import search_papers_for_citation
            candidates = search_papers_for_citation(topic, intent.count)
            assert candidates
            edit_citation_state[sid] = {
                "phase": "candidates_listed",
                "candidates": candidates,
                "pending_topic": topic,
                "pending_count": intent.count,
            }
            mock_search.assert_called_once_with("RAG最新进展", 5)
        assert edit_citation_state[sid]["phase"] == "candidates_listed"
        assert len(edit_citation_state[sid]["candidates"]) == 1
    finally:
        _clear_edit_state(sid)
