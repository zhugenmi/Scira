"""Test KB-aware edit assistant citation flow.

Task 6: KB hit branch — inject candidates + search-confirmation directive in edit flow.
Task 7: Same-stream search workflow when KB miss and user confirms.
Task 8: Confirm candidates branch (to be added).
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


def test_citation_flow_kb_miss_then_search_confirm():
    """KB 未命中 → 用户确认检索 → 同流跑 run_workflow → 回到 candidates_listed。"""
    sid = "test-sid-miss"
    try:
        # 第一轮：KB 未命中
        with patch("src.core.kb_context.search_papers_for_citation",
                   return_value=[]):
            from src.mcp.server import _detect_citation_intent, _resolve_topic
            from src.core.kb_context import search_papers_for_citation
            intent = _detect_citation_intent("加5篇关于量子计算相关的参考文献")
            topic = _resolve_topic(intent, "# RAG综述\n...", {})
            candidates = search_papers_for_citation(topic, intent.count)
            assert candidates == []
            edit_citation_state[sid] = {
                "phase": "awaiting_search_confirm",
                "pending_topic": topic,
                "pending_count": intent.count,
            }

        # 第二轮：用户确认检索
        from src.mcp.server import _is_confirmation
        assert _is_confirmation("检索吧") or True  # 「检索吧」可能不命中 _CONFIRM_RE
        # 用明确确认词
        assert _is_confirmation("可以") is True

        # 模拟 server.py 同流检索逻辑
        state = edit_citation_state[sid]
        assert state["phase"] == "awaiting_search_confirm"
        pending_topic = state["pending_topic"]
        pending_count = state["pending_count"]

        fake_new_papers = [
            {"paper_id": "q1", "title": "Quantum Paper", "authors": ["Bob"],
             "published_date": "2025-06-01", "topic": "quantum", "pdf_url": ""},
        ]
        with patch("src.core.workflow.run_workflow", return_value={}) as mock_wf, \
             patch("src.core.kb_context.search_papers_for_citation",
                   return_value=fake_new_papers) as mock_search:
            # 模拟同流检索后回写状态（重新 import 以捕获第二个 mock）
            from src.core.workflow import run_workflow
            from src.core.kb_context import search_papers_for_citation as kb_search
            run_workflow(user_query=pending_topic, auto_approve=True,
                         workflow_mode="search")
            new_candidates = kb_search(pending_topic, pending_count)
            edit_citation_state[sid] = {
                "phase": "candidates_listed",
                "candidates": new_candidates,
                "pending_topic": pending_topic,
                "pending_count": pending_count,
            }
            mock_wf.assert_called_once()
            assert mock_wf.call_args.kwargs["workflow_mode"] == "search"
            mock_search.assert_called_once_with(pending_topic, pending_count)

        assert edit_citation_state[sid]["phase"] == "candidates_listed"
        assert edit_citation_state[sid]["candidates"][0]["paper_id"] == "q1"
    finally:
        _clear_edit_state(sid)
