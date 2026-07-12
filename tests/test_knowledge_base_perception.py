"""知识库感知 + KB-based 写作 测试。"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.knowledge import list_knowledge_bases, format_knowledge_base_listing


def _make_category(papers_dir: Path, name: str, topic: str, papers: list):
    cat_dir = papers_dir / name
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / f"{name}.json").write_text(
        json.dumps({"category": name, "topic": topic, "count": len(papers), "papers": papers}, ensure_ascii=False),
        encoding="utf-8",
    )
    return cat_dir / f"{name}.json"


def test_list_knowledge_bases_reads_index_and_papers(tmp_path, monkeypatch):
    """list_knowledge_bases 应读 all_papers.json 索引 + 各分类 JSON 论文清单。"""
    from src.core import knowledge as kmod

    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    _make_category(papers_dir, "rl", "强化学习", [
        {"paper_id": "1", "title": "Paper A", "authors": ["Alice"], "published_date": "2020-01-01"},
        {"paper_id": "2", "title": "Paper B", "authors": ["Bob"], "published_date": "2021-02-02"},
    ])
    _make_category(papers_dir, "gnn", "图神经网络", [
        {"paper_id": "3", "title": "Paper C", "authors": ["Carol"], "published_date": "2022-03-03"},
    ])
    (papers_dir / "all_papers.json").write_text(json.dumps({
        "total_papers": 3,
        "categories": {
            "rl": {"path": str(papers_dir / "rl" / "rl.json"), "topic": "强化学习", "count": 2},
            "gnn": {"path": str(papers_dir / "gnn" / "gnn.json"), "topic": "图神经网络", "count": 1},
        },
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(kmod, "PAPERS_DIR", papers_dir)

    result = list_knowledge_bases()

    assert result["total_categories"] == 2
    assert result["total_papers"] == 3
    names = [c["name"] for c in result["categories"]]
    assert names == ["gnn", "rl"]  # 排序后
    rl = next(c for c in result["categories"] if c["name"] == "rl")
    assert rl["topic"] == "强化学习"
    assert rl["count"] == 2
    assert len(rl["papers"]) == 2
    assert rl["papers"][0]["title"] == "Paper A"


def test_list_knowledge_bases_empty_when_no_dir(tmp_path, monkeypatch):
    from src.core import knowledge as kmod
    monkeypatch.setattr(kmod, "PAPERS_DIR", tmp_path / "nonexistent")
    result = list_knowledge_bases()
    assert result["total_categories"] == 0
    assert result["categories"] == []


def test_list_knowledge_bases_falls_back_to_dir_scan(tmp_path, monkeypatch):
    """无 all_papers.json 索引时，应扫目录兜底。"""
    from src.core import knowledge as kmod
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    _make_category(papers_dir, "rag", "RAG", [
        {"paper_id": "x", "title": "Y", "authors": [], "published_date": ""}
    ])
    monkeypatch.setattr(kmod, "PAPERS_DIR", papers_dir)

    result = list_knowledge_bases()
    assert result["total_categories"] == 1
    assert result["categories"][0]["name"] == "rag"
    assert result["categories"][0]["count"] == 1


def test_format_knowledge_base_listing_plain_text():
    listing = {
        "total_papers": 2,
        "total_categories": 1,
        "categories": [{
            "name": "rl", "topic": "强化学习", "count": 2,
            "papers": [
                {"paper_id": "1", "title": "Paper A", "authors": ["Alice"], "published_date": "2020"},
                {"paper_id": "2", "title": "Paper B", "authors": ["Bob", "Carol", "Dave", "Eve"], "published_date": "2021"},
            ],
        }],
    }
    text = format_knowledge_base_listing(listing)
    # 不含 markdown 语法
    assert "##" not in text
    assert "**" not in text
    assert "系统中共有 1 个知识库" in text
    assert "强化学习" in text
    assert "Paper A" in text
    # 超过 3 位作者应省略
    assert "等" in text


def test_format_knowledge_base_listing_empty():
    text = format_knowledge_base_listing({"categories": [], "total_papers": 0, "total_categories": 0})
    assert "还没有任何知识库" in text


# ==================== Intent (LIST_KB) ====================

def test_intent_keyword_fallback_list_kb():
    """关键词兜底：含'知识库'+'有哪些'应识别为 list_kb。"""
    from src.agents.intent import IntentAgent, IntentType, WorkflowMode
    agent = IntentAgent()
    # 强制 LLM 失败走兜底
    with patch.object(agent, "invoke", side_effect=Exception("llm down")):
        result = agent.analyze("系统中有哪些知识库？")
    assert result.intent == IntentType.LIST_KB
    assert result.workflow_mode == WorkflowMode.NONE


def test_intent_keyword_fallback_list_kb_variant():
    from src.agents.intent import IntentAgent, IntentType
    agent = IntentAgent()
    with patch.object(agent, "invoke", side_effect=Exception("llm down")):
        result = agent.analyze("知识库列表给我看看")
    assert result.intent == IntentType.LIST_KB


def test_intent_keyword_fallback_not_list_kb_for_normal_query():
    """含'知识库'但不含枚举词时不应误判为 list_kb（应走默认 full）。"""
    from src.agents.intent import IntentAgent, IntentType
    agent = IntentAgent()
    with patch.object(agent, "invoke", side_effect=Exception("llm down")):
        result = agent.analyze("帮我检索知识图谱相关论文")
    assert result.intent != IntentType.LIST_KB


# ==================== Orchestrator LIST_KB 分支 ====================

def test_orchestrator_list_kb_action(monkeypatch):
    """Orchestrator 收到 LIST_KB 意图时应调 list_knowledge_bases 并返回 list_kb action。"""
    from src.agents.orchestrator import OrchestratorAgent, IntentType
    from src.agents.intent import IntentResult
    from src.agents.intent import WorkflowMode

    agent = OrchestratorAgent()
    # 绕过 LLM 意图识别，直接注入 LIST_KB 结果
    agent.intent_agent = type("Stub", (), {"analyze": lambda self, **kw: IntentResult(
        intent=IntentType.LIST_KB, workflow_mode=WorkflowMode.NONE,
        confidence=0.9, reasoning="stub", extracted_topic=None,
    )})()

    monkeypatch.setattr(
        "src.core.knowledge.list_knowledge_bases",
        lambda: {"categories": [{"name": "rl", "topic": "强化学习", "count": 1, "papers": []}],
                 "total_papers": 1, "total_categories": 1},
    )

    result = agent.process_message("系统中有哪些知识库？", session_id="s1")
    assert result["action"] == "list_kb"
    assert "强化学习" in result["response"]
    assert result.get("kb_listing") is not None
    assert not result.get("requires_workflow", False)


# ==================== KB-based workflow ====================

def test_load_reading_summary_prefers_lens(tmp_path, monkeypatch):
    from src.core import workflow as wfmod

    papers_dir = tmp_path / "papers"
    cat = "rl"
    pid = "1234"
    paper_dir = papers_dir / cat / pid
    paper_dir.mkdir(parents=True)
    # 同时写 lens 和 snap，应优先 lens
    (paper_dir / "lens_zh.json").write_text(json.dumps({
        "markdown": "# 深度精读\nlens content",
        "json": json.dumps({"mode": "lens", "paper_id": pid, "word_count": 100, "sections_count": 5}),
    }, ensure_ascii=False), encoding="utf-8")
    (paper_dir / "snap_zh.json").write_text(json.dumps({
        "markdown": "snap content",
        "json": json.dumps({"mode": "snap", "paper_id": pid, "word_count": 50, "sections_count": 2}),
    }, ensure_ascii=False), encoding="utf-8")

    # mock sanitize_paper_id_for_filename to identity
    monkeypatch.setattr(
        "src.agents.reader.sanitize_paper_id_for_filename", lambda x: x
    )
    result = wfmod._load_reading_summary(papers_dir, cat, pid)
    assert result is not None
    assert "lens content" in result["markdown"]
    assert result["mode"] == "lens"
    assert result["word_count"] == 100


def test_load_reading_summary_returns_none_when_no_reading(tmp_path, monkeypatch):
    from src.core import workflow as wfmod
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "rl" / "1234"
    paper_dir.mkdir(parents=True)
    monkeypatch.setattr("src.agents.reader.sanitize_paper_id_for_filename", lambda x: x)
    result = wfmod._load_reading_summary(papers_dir, "rl", "1234")
    assert result is None


def test_run_workflow_from_knowledge_bases_loads_papers(tmp_path, monkeypatch):
    """端到端：选 1 个 KB → 加载精读 → 构建 literature_data → reference_list。
    跳过 LLM 调用（analysis/outline/writing/revision 全 mock）。"""
    from src.core import workflow as wfmod

    # 1) 造数据：1 个分类 + 1 篇论文 + lens 精读
    papers_dir = tmp_path / "papers"
    cat = "rl"
    pid = "1234"
    paper_dir = papers_dir / cat / pid
    paper_dir.mkdir(parents=True)
    (paper_dir / "lens_zh.json").write_text(json.dumps({
        "markdown": "# 精读\n该论文提出 XXX 方法。",
        "json": json.dumps({"mode": "lens", "paper_id": pid, "word_count": 200, "sections_count": 5}),
    }, ensure_ascii=False), encoding="utf-8")
    (papers_dir / cat / f"{cat}.json").write_text(json.dumps({
        "category": cat, "topic": "强化学习", "count": 1,
        "papers": [{"paper_id": pid, "title": "Paper A", "authors": ["Alice"],
                    "abstract": "abs", "published_date": "2020", "pdf_url": "http://x"}],
    }, ensure_ascii=False), encoding="utf-8")

    # 2) monkeypatch 路径与 LLM 依赖
    monkeypatch.setattr(wfmod, "_match_existing_category", lambda *a, **k: None)
    monkeypatch.setattr("src.agents.reader.sanitize_paper_id_for_filename", lambda x: x)

    # 3) mock synthesize（不调 LLM）
    monkeypatch.setattr(wfmod, "synthesize_from_reading_summaries", lambda ld, t: {
        "global_knowledge": {"research_background": "bg"},
        "literature_clusters": [{"cluster_id": "c1", "theme": t, "papers": ld}],
    })

    # 4) mock 后续节点
    captured = {}

    def fake_outline(state):
        state["outline"] = {"title": "T", "sections": []}
        captured["literature_data"] = state.get("literature_data", [])
        captured["reference_list"] = state.get("reference_list", [])
        return state

    def fake_writing(state):
        state["final_paper"] = "body"
        state["chapter_drafts"] = {}
        return state

    def fake_revision(state):
        state["final_review"] = "final"
        state["abstract"] = "abs"
        return state

    monkeypatch.setattr(wfmod, "outline_node", fake_outline)
    monkeypatch.setattr(wfmod, "writing_node", fake_writing)
    monkeypatch.setattr(wfmod, "revision_node", fake_revision)
    monkeypatch.setattr(wfmod, "sync_token_usage_to_state", lambda s: None)

    # 切换工作目录使 data/papers 解析到 tmp_path
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    # 把造好的 papers 目录移到 data/ 下
    (tmp_path / "papers").rename(tmp_path / "data" / "papers")

    state = wfmod.run_workflow_from_knowledge_bases(
        categories=[cat], topic="强化学习综述", progress_callback=None,
    )

    # 验证 literature_data 已加载精读内容
    ld = captured["literature_data"]
    assert len(ld) == 1
    assert ld[0]["paper_id"] == pid
    assert ld[0]["extracted_content"]["reading_summary"] == "# 精读\n该论文提出 XXX 方法。"

    # 验证 reference_list 来自 literature_data
    rl = captured["reference_list"]
    assert len(rl) == 1
    assert rl[0]["paper_id"] == pid

    # 验证 source_categories 标记
    assert state.get("source_categories") == [cat]
    assert state.get("final_review") == "final"


def test_run_workflow_from_knowledge_bases_empty_category_short_circuits(tmp_path, monkeypatch):
    """所选分类无任何论文时应短路返回，不进入后续节点。"""
    from src.core import workflow as wfmod

    papers_dir = tmp_path / "data" / "papers" / "empty"
    papers_dir.mkdir(parents=True)
    (papers_dir / "empty.json").write_text(json.dumps({
        "category": "empty", "topic": "空", "count": 0, "papers": [],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(wfmod, "_match_existing_category", lambda *a, **k: None)
    monkeypatch.setattr("src.agents.reader.sanitize_paper_id_for_filename", lambda x: x)
    monkeypatch.setattr(wfmod, "sync_token_usage_to_state", lambda s: None)

    # 若误进入后续节点，会因 outline_node 真实调用而失败 —— 这里不应被调用
    called = {"outline": False}
    def fail_outline(state):
        called["outline"] = True
        return state
    monkeypatch.setattr(wfmod, "outline_node", fail_outline)

    monkeypatch.chdir(tmp_path)
    state = wfmod.run_workflow_from_knowledge_bases(
        categories=["empty"], topic="空", progress_callback=None,
    )
    assert not called["outline"]
    assert "所选知识库中没有可用论文" in state.get("error_messages", [])


def test_run_workflow_from_knowledge_bases_sorts_papers_oldest_first(tmp_path, monkeypatch):
    """KB 写作应按 published_date 升序遍历(旧->新),不论 JSON 文件里的存储顺序。
    综述按时间脉络从早期工作写到最新进展。"""
    from src.core import workflow as wfmod

    papers_dir = tmp_path / "data" / "papers" / "rl"
    papers_dir.mkdir(parents=True)
    # 故意打乱顺序:2022 -> 2020 -> 2021,期望遍历顺序为 2020 -> 2021 -> 2022
    (papers_dir / "rl.json").write_text(json.dumps({
        "category": "rl", "topic": "强化学习", "count": 3,
        "papers": [
            {"paper_id": "p2022", "title": "New", "authors": [],
             "abstract": "", "published_date": "2022-06-01", "pdf_url": ""},
            {"paper_id": "p2020", "title": "Old", "authors": [],
             "abstract": "", "published_date": "2020-01-01", "pdf_url": ""},
            {"paper_id": "p2021", "title": "Mid", "authors": [],
             "abstract": "", "published_date": "2021-03-15", "pdf_url": ""},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(wfmod, "_match_existing_category", lambda *a, **k: None)
    monkeypatch.setattr("src.agents.reader.sanitize_paper_id_for_filename", lambda x: x)
    monkeypatch.setattr(wfmod, "synthesize_from_reading_summaries", lambda ld, t: {
        "global_knowledge": {"research_background": "bg"},
        "literature_clusters": [{"cluster_id": "c1", "theme": t, "papers": ld}],
    })

    captured = {}
    def fake_outline(state):
        captured["order"] = [p["paper_id"] for p in state.get("literature_data", [])]
        state["outline"] = {"title": "T", "sections": []}
        return state
    monkeypatch.setattr(wfmod, "outline_node", fake_outline)
    monkeypatch.setattr(wfmod, "writing_node", lambda s: {**s, "final_paper": "x", "chapter_drafts": {}})
    monkeypatch.setattr(wfmod, "revision_node", lambda s: {**s, "final_review": "f", "abstract": "a"})
    monkeypatch.setattr(wfmod, "sync_token_usage_to_state", lambda s: None)
    monkeypatch.chdir(tmp_path)

    wfmod.run_workflow_from_knowledge_bases(categories=["rl"], topic="RL综述")

    assert captured["order"] == ["p2020", "p2021", "p2022"], \
        f"应当旧->新遍历,实际顺序: {captured['order']}"


def test_run_workflow_from_knowledge_bases_undated_papers_go_last(tmp_path, monkeypatch):
    """无 published_date 或日期解析失败的论文放最后,避免污染时间脉络。"""
    from src.core import workflow as wfmod

    papers_dir = tmp_path / "data" / "papers" / "rl"
    papers_dir.mkdir(parents=True)
    (papers_dir / "rl.json").write_text(json.dumps({
        "category": "rl", "topic": "强化学习", "count": 3,
        "papers": [
            {"paper_id": "no_date", "title": "Unknown", "authors": [],
             "abstract": "", "published_date": "", "pdf_url": ""},
            {"paper_id": "bad_date", "title": "Bad", "authors": [],
             "abstract": "", "published_date": "not-a-date", "pdf_url": ""},
            {"paper_id": "p2021", "title": "Mid", "authors": [],
             "abstract": "", "published_date": "2021-03-15", "pdf_url": ""},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(wfmod, "_match_existing_category", lambda *a, **k: None)
    monkeypatch.setattr("src.agents.reader.sanitize_paper_id_for_filename", lambda x: x)
    monkeypatch.setattr(wfmod, "synthesize_from_reading_summaries", lambda ld, t: {
        "global_knowledge": {"research_background": "bg"},
        "literature_clusters": [{"cluster_id": "c1", "theme": t, "papers": ld}],
    })

    captured = {}
    def fake_outline(state):
        captured["order"] = [p["paper_id"] for p in state.get("literature_data", [])]
        state["outline"] = {"title": "T", "sections": []}
        return state
    monkeypatch.setattr(wfmod, "outline_node", fake_outline)
    monkeypatch.setattr(wfmod, "writing_node", lambda s: {**s, "final_paper": "x", "chapter_drafts": {}})
    monkeypatch.setattr(wfmod, "revision_node", lambda s: {**s, "final_review": "f", "abstract": "a"})
    monkeypatch.setattr(wfmod, "sync_token_usage_to_state", lambda s: None)
    monkeypatch.chdir(tmp_path)

    wfmod.run_workflow_from_knowledge_bases(categories=["rl"], topic="RL综述")

    # 有日期的论文先遍历,无/坏日期的论文放最后(stable sort 保持 no_date 在 bad_date 前)
    assert captured["order"] == ["p2021", "no_date", "bad_date"], \
        f"无日期论文应放最后,实际顺序: {captured['order']}"
