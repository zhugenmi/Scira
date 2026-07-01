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


def test_resolve_target_category_new_name_normalizes():
    from src.core.workflow import resolve_target_category
    # 普通新名：归一化（小写 + 下划线）
    assert resolve_target_category("  Drug Discovery!", None, ["diffusion"]) == "drug_discovery"


def test_resolve_target_category_new_name_reuses_existing():
    from src.core.workflow import resolve_target_category
    # 归一化后与已有重名 → 复用
    assert resolve_target_category("Diffusion", None, ["diffusion"]) == "diffusion"


def test_resolve_target_category_target_when_no_new_name():
    from src.core.workflow import resolve_target_category
    # 无 new_name，用 target_category
    assert resolve_target_category(None, "gnn", ["diffusion", "gnn"]) == "gnn"


def test_resolve_target_category_both_none_returns_none():
    from src.core.workflow import resolve_target_category
    # 都 None → 返回 None（调用方走自动匹配）
    assert resolve_target_category(None, None, ["diffusion"]) is None


def test_resolve_target_category_empty_new_name_after_norm():
    from src.core.workflow import resolve_target_category
    # 归一化后为空 → 返回 None（前端拦截，但后端也要兜底）
    assert resolve_target_category("   !!!", None, []) is None


def test_reader_agent_paper_callback_invoked(monkeypatch):
    """ReaderAgent.run 在每篇完成时调用 paper_callback(paper_id, status, error)。"""
    from src.agents.reader import ReaderAgent, ReadingTask

    events: list[tuple[str, str, str | None]] = []

    def fake_process_task(self, task, download_dir=None):
        # 模拟成功
        task.status = "completed"
        task.parsed_content = {"paper_id": task.paper_id, "word_count": 10}
        return task

    monkeypatch.setattr(ReaderAgent, "process_task", fake_process_task)

    agent = ReaderAgent(
        paper_callback=lambda pid, st, err: events.append((pid, st, err))
    )
    papers = [
        {"paper_id": "p1", "title": "T1", "authors": [], "abstract": "", "pdf_url": "http://x/1.pdf"},
        {"paper_id": "p2", "title": "T2", "authors": [], "abstract": "", "pdf_url": "http://x/2.pdf"},
    ]
    agent.run(papers, download_dir="/tmp/whatever")

    # 期望每篇至少有一条 success 事件
    pids = {e[0] for e in events}
    assert pids == {"p1", "p2"}
    assert all(e[1] == "success" for e in events if e[1] == "success")


def test_run_download_and_rest_emits_per_paper_events(monkeypatch, tmp_path):
    """run_download_and_rest 把 paper_callback 转成 _emit_progress('download', details={'per_paper':...})."""
    from src.core import workflow as wf
    from src.agents.reader import ReaderAgent, ReadingResult

    events: list[tuple[str, dict[str, Any]]] = []

    def fake_emit(phase, progress=None, message=None, details=None):
        if phase == "download" and details and details.get("per_paper"):
            events.append((phase, details["per_paper"]))

    monkeypatch.setattr(wf, "_emit_progress", fake_emit)

    # Mock ReaderAgent.run：直接产出 literature_data，并触发回调
    def fake_run(self, papers, max_workers=None, download_dir=None):
        for p in papers:
            if self.paper_callback:
                self.paper_callback(p["paper_id"], "success", None)
        return ReadingResult(
            tasks=[], total_papers=len(papers), completed=len(papers), failed=0,
            literature_data=[{"paper_id": p["paper_id"]} for p in papers],
            reading_summary={"failed_papers": []},
        )

    monkeypatch.setattr(ReaderAgent, "run", fake_run)

    state = {
        "workflow_mode": "search", "current_category": "diffusion",
        "pdfs_dir": str(tmp_path), "literature_data": [], "reading_errors": [],
        "pending_download_papers": [], "download_approval": "pending",
        "human_approvals": {}, "error_messages": [], "retry_count": 0,
        "run_id": None,
    }
    selected = [
        {"paper_id": "p1"}, {"paper_id": "p2"},
    ]
    wf.run_download_and_rest(state, selected, progress_callback=lambda *a, **k: None)

    pids = {e[1]["paper_id"] for e in events}
    assert pids == {"p1", "p2"}
    assert all(e[1]["status"] == "success" for e in events)


def test_run_download_and_rest_short_circuits_on_empty(monkeypatch, tmp_path):
    """全部下载失败（literature_data 为空）时，full 模式不进入 reading_node。"""
    from src.core import workflow as wf
    from src.agents.reader import ReaderAgent, ReadingResult

    reading_called = []

    def fake_reading_node(state):
        reading_called.append(True)
        return state

    monkeypatch.setattr(wf, "reading_node", fake_reading_node)

    def fake_run(self, papers, max_workers=None, download_dir=None):
        for p in papers:
            if self.paper_callback:
                self.paper_callback(p["paper_id"], "failed", "403")
        return ReadingResult(
            tasks=[], total_papers=len(papers), completed=0, failed=len(papers),
            literature_data=[], reading_summary={"failed_papers": [{"paper_id": p["paper_id"], "error": "403"} for p in papers]},
        )

    monkeypatch.setattr(ReaderAgent, "run", fake_run)

    state = {
        "workflow_mode": "full", "current_category": "diffusion",
        "pdfs_dir": str(tmp_path), "literature_data": [], "reading_errors": [],
        "pending_download_papers": [], "download_approval": "pending",
        "human_approvals": {}, "error_messages": [], "retry_count": 0,
        "run_id": None,
    }
    wf.run_download_and_rest(state, [{"paper_id": "p1"}], progress_callback=lambda *a, **k: None)

    assert reading_called == [], "literature_data 为空时不应进入 reading_node"


def test_progress_callback_enqueues_per_paper_events():
    """make_workflow_progress_callback 检测 details['per_paper'] 并 append 到 task['event_queue']。"""
    from src.mcp.server import make_workflow_progress_callback, workflow_tasks

    task_id = "t-evt"
    workflow_tasks[task_id] = {
        "status": "running", "phase": "download", "progress": 0.3,
        "details": {"message": "downloading"},
        "event_queue": __import__("collections").deque(),
    }
    cb = make_workflow_progress_callback(task_id)
    cb("download", 0.3, "downloading", {"per_paper": {"paper_id": "p1", "status": "success", "error": None}})
    cb("download", 0.3, "downloading", {"per_paper": {"paper_id": "p2", "status": "failed", "error": "403"}})
    cb("download", 0.4, "msg", {"papers_downloading": 1})  # 非 per_paper，不应入队

    q = workflow_tasks[task_id]["event_queue"]
    assert len(q) == 2
    assert q[0]["paper_id"] == "p1" and q[0]["status"] == "success"
    assert q[1]["paper_id"] == "p2" and q[1]["status"] == "failed"

