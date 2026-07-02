"""
Scira LangGraph Workflow

Defines the complete research assistant pipeline as a LangGraph DAG.
Includes logging, observability, and token tracking.
"""

from __future__ import annotations

import os
import json
from typing import Dict, List, Optional, Any, TypedDict, Annotated
from dataclasses import dataclass
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from langchain_core.messages import BaseMessage, HumanMessage
from langsmith import traceable

# Import agents
from src.agents.retrieval import RetrievalAgent
from src.agents.reader import ReaderAgent
from src.agents.analyzer import AnalyzerAgent, analyze_literature
from src.agents.writer import WriterAgent
from src.agents.reviewer import ReviewerAgent


# ==================== Retrieval Approval Helpers ====================

def prepare_retrieval(
    user_query: str,
    modification: Optional[str] = None,
    year_range: Optional[tuple] = None,
    min_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    只执行检索的「准备」阶段：分析查询 + 生成检索策略，不执行搜索/下载。

    用于在真正检索前把检索条件回送给用户确认。modification 非空时，将其作为
    用户补充意见拼接到查询里重新分析，实现「拒绝 + 修改建议 → 重试」。

    Returns:
        检索条件字典，结构与 RETRIEVAL_APPROVAL_PROMPT 的字段对齐。
    """
    from src.utils.logger import logger

    query = user_query.strip()
    if modification and modification.strip():
        query = f"{query}\n用户补充意见：{modification.strip()}"

    agent = RetrievalAgent()
    try:
        analysis = agent.analyze_query(query)
    except Exception as e:
        logger.warning(f"prepare_retrieval analyze_query failed: {e}")
        analysis = {"normalized_topic": user_query, "key_concepts": [],
                    "research_direction": "exploratory", "background_context": ""}

    topic = analysis.get("normalized_topic", user_query)
    if "translated_query" in analysis:
        topic = analysis.get("translated_query", topic)
    key_concepts = analysis.get("key_concepts", []) or []

    try:
        strategy = agent.generate_search_strategy(
            topic, key_concepts,
            year_range=year_range,
            min_count=min_count,
        )
    except Exception as e:
        logger.warning(f"prepare_retrieval generate_search_strategy failed: {e}")
        from src.agents.retrieval import SearchStrategy
        strategy = SearchStrategy(
            keywords=key_concepts or [topic],
            boolean_query=f'"{topic}"',
            categories=[],
            date_range=("", ""),
            max_results=20,
            rationale="fallback",
        )

    return {
        "user_query": user_query,
        "modification": modification or "",
        "normalized_topic": topic,
        "key_concepts": key_concepts,
        "research_direction": analysis.get("research_direction", "exploratory"),
        "background_context": analysis.get("background_context", ""),
        "boolean_query": strategy.boolean_query,
        "keywords": strategy.keywords,
        "categories": strategy.categories,
        "date_range": list(strategy.date_range),
        "max_results": strategy.max_results,
        "rationale": strategy.rationale,
    }


def build_reference_list(state: GraphState) -> List[Dict[str, Any]]:
    """
    从已阅读的论文（literature_data）构建带编号的参考文献列表；
    若 literature_data 为空则回退到检索结果（search_results），保证报告总能基于
    实际检索到/知识库中的论文来引用，而非 LLM 凭空捏造。
    """
    refs: List[Dict[str, Any]] = []
    seen = set()

    def _add(p: Dict[str, Any]):
        pid = (p.get("paper_id") or p.get("id") or "").strip()
        title = (p.get("title") or "").strip()
        if not pid and not title:
            return
        key = pid or title.lower()
        if key in seen:
            return
        seen.add(key)
        authors = p.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        year = ""
        date_str = p.get("published_date") or p.get("published") or ""
        if date_str:
            import re as _re
            m = _re.search(r"\d{4}", str(date_str))
            if m:
                year = m.group(0)
        refs.append({
            "paper_id": pid,
            "title": title,
            "authors": authors,
            "year": year,
            "source": p.get("source", ""),
        })

    for p in state.get("literature_data", []) or []:
        _add(p)
    if not refs:
        for p in state.get("search_results", []) or []:
            _add(p)

    return refs


def format_bibliography(reference_list: List[Dict[str, Any]]) -> str:
    """
    将编号参考文献列表格式化为 GB/T 7714-2015 风格的参考文献目录。

    期刊/会议论文格式：作者. 题名[J/EB/OL]. 出处, 年份.
    作者超过 3 位时用「等」省略。所有条目均来自检索/知识库，绝不由 LLM 生成。

    条目之间用空行分隔：markdown 中单个 \\n 会被渲染成空格（软换行），
    导致参考文献挤成一段；用 \\n\\n 让每条独立成段，保证一行一篇。
    """
    if not reference_list:
        return ""
    entries = ["## 参考文献\n"]
    for i, r in enumerate(reference_list, 1):
        authors = r.get("authors") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        if not authors:
            author_str = "佚名"
        elif len(authors) <= 3:
            author_str = ", ".join(authors)
        else:
            author_str = ", ".join(authors[:3]) + ", 等"
        year = r.get("year", "")
        title = (r.get("title") or "Untitled").rstrip(".。")
        source = (r.get("source") or "").lower()
        # 文献类型标识：预印本/开放获取用 [EB/OL]，其余默认 [J]
        doc_type = "[EB/OL]" if source in {"arxiv", "biorxiv", "medrxiv"} else "[J]"
        year_part = f", {year}" if year else ""
        entries.append(f"[{i}] {author_str}. {title}{doc_type}{year_part}.")
    # 每条之间空一行，保证 markdown 渲染为独立段落
    return "\n\n".join(entries) + "\n"




# Import state
from src.core.state import GraphState, PipelinePhase, ApprovalStatus

# Import logging and token tracking. setup_logging is idempotent and already
# runs at logger.py import time (honors LOG_LEVEL / LOG_VERBOSE env); the
# explicit call here is kept as a documentation anchor.
from src.utils.logger import (
    logger,
    setup_logging,
    get_token_tracker,
    reset_token_tracker,
    TokenTracker,
)
from src.utils.context import new_run_id, set_run_id, get_current_run_id
from src.utils.metrics import get_registry

setup_logging()

_metrics = get_registry()


# ==================== Helper Functions ====================

# ==================== Progress Callback (SSE 状态同步) ====================
#
# 问题：LangGraph 节点在内部把 current_phase 写入 state，但 server 层的
# workflow_tasks[task_id]["phase"] 不会被更新，导致 SSE 一直停留在首个 phase。
# 方案：用线程本地注册表保存当前线程的 progress_callback，节点入口/子阶段
# 调用 _emit_progress 即可把阶段推给 server（server 据此更新 workflow_tasks，
# SSE 轮询时把新阶段推给前端）。run_workflow 在调用前后 set/clear。
import threading

_progress_local = threading.local()

# 阶段 → (progress, 默认文案)。文案与前端期望状态对齐。
_PHASE_INFO: Dict[str, "tuple[float, str]"] = {
    "init": (0.02, "已启动研究工作流，正在准备..."),
    "retrieval": (0.10, "论文检索中..."),
    "retrieval_download": (0.20, "论文下载中..."),
    "reading": (0.35, "论文阅读中..."),
    "analysis": (0.50, "文献分析中..."),
    "outline": (0.65, "生成论文大纲中..."),
    "writing": (0.80, "生成论文中..."),
    "revision": (0.95, "论文审查中..."),
    "final": (1.00, "研究完成！"),
}


def _set_progress_callback(cb):
    _progress_local.callback = cb


def _clear_progress_callback():
    _progress_local.callback = None


def _emit_progress(phase: str, progress: Optional[float] = None,
                   message: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
    """向当前线程注册的 progress_callback 推送一次阶段更新。"""
    cb = getattr(_progress_local, "callback", None)
    if not cb:
        return
    default_progress, default_msg = _PHASE_INFO.get(phase, (None, ""))
    try:
        cb(
            phase,
            progress if progress is not None else default_progress,
            message or default_msg,
            details,
        )
    except Exception as e:
        logger.debug(f"progress callback error: {e}")


def extract_keywords_from_text(title: str, abstract: str, search_keywords: List[str]) -> List[str]:
    """
    从论文标题和摘要中提取关键词。

    Args:
        title: 论文标题
        abstract: 论文摘要
        search_keywords: 搜索关键词（作为回退）

    Returns:
        关键词列表
    """
    import re

    keywords = []

    # 1. 首先使用搜索关键词
    if search_keywords:
        keywords.extend(search_keywords[:3])

    # 2. 从标题中提取有意义的词
    if title:
        # 移除常见前缀
        clean_title = re.sub(r'^(Paper|Article|Thesis|Report):\s*', '', title, flags=re.IGNORECASE)
        # 提取包含大写字母或数字的词组（通常是技术术语）
        title_words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', clean_title)
        # 过滤掉常见词
        stop_words = {'The', 'A', 'An', 'This', 'These', 'Those', 'Using', 'Based', 'For', 'With', 'From', 'On', 'In', 'To', 'Of', 'And', 'Or'}
        title_words = [w for w in title_words if w not in stop_words and len(w) > 2]
        keywords.extend(title_words[:2])

    # 3. 去重并返回
    seen = set()
    unique_keywords = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            unique_keywords.append(kw)

    return unique_keywords[:5] if unique_keywords else search_keywords[:3] if search_keywords else ["general"]


# ==================== Token Tracking ====================

def track_token_usage(state: GraphState, input_tokens: int = 0, output_tokens: int = 0):
    """Track token usage in state."""
    if input_tokens > 0 or output_tokens > 0:
        # Get or create token tracker
        model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o")
        tracker = get_token_tracker(model_name)
        tracker.add_usage(input_tokens, output_tokens)

        # Update state with token info
        if "token_usage" not in state:
            state["token_usage"] = {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "request_count": 0,
                "estimated_cost_usd": 0.0,
            }

        state["token_usage"]["total_input_tokens"] += input_tokens
        state["token_usage"]["total_output_tokens"] += output_tokens
        state["token_usage"]["request_count"] = state["token_usage"].get("request_count", 0) + 1

        # Calculate cost
        summary = tracker.get_summary()
        state["token_usage"]["estimated_cost_usd"] = summary["estimated_cost_usd"]

        logger.debug(
            f"Token usage: +{input_tokens} input, +{output_tokens} output | "
            f"Total: {summary['total_tokens']} | Cost: ${summary['estimated_cost_usd']:.4f}"
        )


def sync_token_usage_to_state(state: GraphState) -> None:
    """
    Flush the global TokenTracker's accumulated usage into GraphState.

    Agents feed the global tracker via BaseAgent._record_token_usage on every
    LLM call. The tracker is process-global (not per-workflow), so this sync
    must be called at least once at the end of the workflow to materialize the
    totals into state — otherwise state["token_usage"] stays at the zero values
    written by init_state and the final summary log / eval script report $0.

    Safe to call multiple times; each call overwrites state with the latest
    tracker totals.
    """
    try:
        model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o")
        tracker = get_token_tracker(model_name)
        summary = tracker.get_summary()
        state["token_usage"] = {
            "total_input_tokens": summary["total_input_tokens"],
            "total_output_tokens": summary["total_output_tokens"],
            "request_count": summary["request_count"],
            "estimated_cost_usd": summary["estimated_cost_usd"],
        }
    except Exception as e:
        logger.debug(f"sync_token_usage_to_state failed: {e}")


# ==================== Node Functions ====================

@traceable(name="init_state")
def _match_existing_category(
    papers_dir: "Path",
    user_query: str,
    approved_topic: str,
    search_keywords: List[str],
) -> Optional[str]:
    """
    检查本次检索是否命中知识库中已有的类别，命中则复用该类别目录（追加去重）。

    匹配规则（任一命中即视为同一主题）：
    1. approved_topic 归一化后 == 某已有类别名（最稳，英文规范化主题）
    2. 本次查询/关键词 与该类别 topic 的关键词集合 Jaccard >= 0.4
    3. user_query 中文映射出的标准类别名 == 某已有类别名
    """
    import json as _json
    all_papers_file = papers_dir / "all_papers.json"
    if not all_papers_file.exists():
        return None
    try:
        with open(all_papers_file, "r", encoding="utf-8") as f:
            index = _json.load(f)
    except Exception:
        return None

    categories = index.get("categories", {}) or {}
    if not categories:
        return None

    def _norm_tokens(text: str) -> set:
        if not text:
            return set()
        import re as _re
        # 拆成词，去标点，小写
        toks = set(_re.sub(r"[^\w一-鿿]", " ", text.lower()).split())
        toks.discard("")
        return toks

    # 候选文本：approved_topic 优先，其次 user_query，再拼关键词
    cand_texts = [approved_topic, user_query]
    if search_keywords:
        cand_texts.extend(search_keywords)
    cand_tokens = set()
    for t in cand_texts:
        cand_tokens |= _norm_tokens(t)

    approved_norm = _norm_tokens(approved_topic)

    for cat_name, entry in categories.items():
        cat_topic = entry.get("topic", "") if isinstance(entry, dict) else ""
        # 规则1：approved_topic 归一化 == 类别名
        if approved_topic and _norm_tokens(approved_topic) and (
            approved_topic.strip().lower().replace(" ", "_") == cat_name.lower()
            or cat_name.lower() in approved_norm
        ):
            logger.info(f"匹配到已有类别 '{cat_name}'（approved_topic 命中），将追加去重")
            return cat_name
        # 规则2：topic 关键词 Jaccard
        cat_tokens = _norm_tokens(cat_topic) | _norm_tokens(cat_name)
        if cand_tokens and cat_tokens:
            inter = len(cand_tokens & cat_tokens)
            union = len(cand_tokens | cat_tokens)
            if union and inter / union >= 0.4:
                logger.info(f"匹配到已有类别 '{cat_name}'（关键词 Jaccard={inter/union:.2f}），将追加去重")
                return cat_name

    return None


def build_pending_download_papers(
    state: GraphState, pdfs_dir: "Path"
) -> List[Dict[str, Any]]:
    """
    从 search_results 构建待下载论文清单：仅保留有 pdf_url 的，去重已下载，透传 source/has_pdf_link。
    抽出来便于单元测试；retrieval_node 内部调用此函数。
    """
    from src.agents.reader import sanitize_paper_id_for_filename as _safe_pid
    from config.settings import get_config

    config = get_config()
    max_pdf_download = config.max_pdf_download
    papers_with_pdf = [p for p in state["search_results"] if p.get("pdf_url")]

    pending: List[Dict[str, Any]] = []
    seen_ids = set()
    for p in papers_with_pdf[:max_pdf_download]:
        pid = p.get("paper_id", "")
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        safe = _safe_pid(pid)
        if (pdfs_dir / safe / f"{safe}.pdf").exists():
            continue
        pending.append({
            "paper_id": pid,
            "title": p.get("title", ""),
            "authors": p.get("authors", []),
            "published_date": p.get("published_date", ""),
            "abstract": (p.get("abstract", "") or "")[:300],
            "pdf_url": p.get("pdf_url", ""),
            "source": p.get("source", "unknown"),
            "has_pdf_link": bool(p.get("pdf_url")),
        })
    return pending


def list_existing_categories(papers_dir: "Path") -> List[str]:
    """列出 data/papers/ 下所有已有知识库（子目录名），供前端下拉。"""
    if not papers_dir.exists():
        return []
    return sorted(
        d.name for d in papers_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


def attach_approval_categories(state: GraphState, papers_dir: "Path") -> None:
    """把自动匹配的类别 + 已有类别列表写进 state，供 approval 事件透传到前端。"""
    state["pending_matched_category"] = state.get("current_category") or ""
    state["pending_categories"] = list_existing_categories(papers_dir)


def resolve_target_category(
    new_category_name: Optional[str],
    target_category: Optional[str],
    existing_categories: List[str],
) -> Optional[str]:
    """
    决定本次下载入库到哪个知识库：
    - new_category_name 非空 → 归一化（小写 + 非字母数字汉字转下划线），重名复用，归一化后为空返回 None
    - 否则用 target_category（若不在 existing 里也接受，调用方当新建）
    - 都 None → None（调用方走 state['current_category']）
    """
    import re as _re

    if new_category_name and new_category_name.strip():
        norm = _re.sub(r"[^\w一-鿿\-]", "_", new_category_name.strip().lower())[:80]
        norm = norm.strip("_") or None
        if not norm:
            return None
        # 与已有重名（大小写无关）→ 复用现有
        for ex in existing_categories or []:
            if ex.lower() == norm:
                return ex
        return norm

    if target_category and target_category.strip():
        return target_category.strip()

    return None


def init_state(state: GraphState) -> GraphState:
    """Initialize the state with user query."""
    # 生成 run_id 并同步到 contextvars，使后续所有日志行带同一 run_id
    run_id = state.get("run_id") or new_run_id()
    set_run_id(run_id)
    state["run_id"] = run_id

    logger.info("=" * 50)
    logger.info("Starting Scira Workflow")
    logger.info(f"User query: {state.get('user_query', 'N/A')}")
    logger.info("=" * 50)

    _emit_progress("init")
    state["current_phase"] = PipelinePhase.INIT
    state["error_messages"] = []
    state["retry_count"] = 0
    state["created_at"] = datetime.now().isoformat()
    state["updated_at"] = datetime.now().isoformat()
    state["token_usage"] = {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "request_count": 0,
        "estimated_cost_usd": 0.0,
    }
    # Reset the global token tracker so repeated workflow runs in the same
    # process don't accumulate across runs.
    reset_token_tracker()

    # Default values
    if "auto_approve" not in state:
        state["auto_approve"] = False

    logger.info("State initialized successfully")
    return state


@traceable(name="retrieval_node")
@_metrics.time("workflow_phase_duration_seconds", labels={"phase": "retrieval"})
def retrieval_node(state: GraphState) -> GraphState:
    """Retrieval agent node - search for papers."""
    logger.info(">>> Entering RETRIEVAL node")
    state["current_phase"] = PipelinePhase.RETRIEVAL
    _emit_progress("retrieval")
    user_query = state.get("user_query", "N/A")

    try:
        logger.info(f"Starting paper search for: {user_query}")

        agent = RetrievalAgent()
        # 若携带审批通过的检索条件，则直接复用，避免对中文查询二次翻译得到空主题
        approved_topic = state.get("approved_topic")
        approved_keywords = state.get("approved_keywords")

        # 用户检索约束（来自 IntentAgent → Orchestrator → state）
        state_year_range = state.get("year_range")
        year_range = None
        if isinstance(state_year_range, (list, tuple)) and len(state_year_range) == 2:
            try:
                year_range = (int(state_year_range[0]), int(state_year_range[1]))
            except (TypeError, ValueError):
                year_range = None
        state_min_count = state.get("min_count")
        min_count = None
        if isinstance(state_min_count, int) and state_min_count > 0:
            min_count = state_min_count

        result = agent.run(
            user_query=user_query,
            auto_approve=state.get("auto_approve", False),
            approved_topic=approved_topic,
            approved_keywords=approved_keywords,
            year_range=year_range,
            min_count=min_count,
        )

        # Update state
        state["search_keywords"] = result.search_strategy.keywords
        state["domain"] = result.search_strategy.domain

        # Handle both dict and object formats from MCP API
        state["search_results"] = []
        for p in result.papers:
            if isinstance(p, dict):
                # MCP API returns dict
                state["search_results"].append({
                    "paper_id": p.get("paper_id", p.get("id", "")),
                    "title": p.get("title", ""),
                    "authors": p.get("authors", []),
                    "abstract": p.get("abstract", ""),
                    "pdf_url": p.get("pdf_url", p.get("url", "")),
                    "published_date": p.get("published_date", p.get("published", "")),
                })
            else:
                # Object format (fallback)
                state["search_results"].append({
                    "paper_id": p.paper_id,
                    "title": p.title,
                    "authors": p.authors,
                    "abstract": p.abstract,
                    "pdf_url": p.pdf_url,
                    "published_date": p.published_date,
                })

        state["selected_papers"] = result.selected_paper_ids

        # 若用户指定了 min_count 且实际不足，写提示供前端 SEARCH_SUMMARY 读取
        if min_count is not None and len(result.papers) < min_count:
            hint = f"实际检索到 {len(result.papers)} 篇（用户要求≥{min_count} 篇）"
            logger.warning(f"Retrieval shortfall: {hint}")
            state["retrieval_shortfall_hint"] = hint
        else:
            state["retrieval_shortfall_hint"] = None

        # Check if retrieval was successful
        num_papers = len(result.papers)
        logger.info(
            f"Retrieved {num_papers} papers | "
            f"Selected {len(result.selected_paper_ids)} for reading"
        )
        logger.debug(f"Search keywords: {result.search_strategy.keywords}")

        # Save retrieved papers to data/papers directory (organized by topic/field)
        if num_papers > 0:
            try:
                import os
                from datetime import datetime as dt
                import json
                from pathlib import Path
                import re

                # Create papers directory
                papers_dir = Path("data/papers")
                papers_dir.mkdir(parents=True, exist_ok=True)

                # 使用用户查询生成分类名，而非搜索关键词
                user_query = state.get("user_query", "")
                search_keywords = result.search_strategy.keywords
                # 优先用审批通过的规范化主题作为分类名来源（英文，更稳定）
                approved_topic_for_cat = (state.get("approved_topic") or "").strip()

                def _to_category(text: str) -> str:
                    import re as _re
                    cat = _re.sub(r'[^\w一-鿿\-]', '_', text.strip())[:30]
                    return cat.strip('_').lower() or ""

                category = ""
                # 1) 审批通过的英文主题
                if approved_topic_for_cat:
                    category = _to_category(approved_topic_for_cat)
                # 2) 英文用户查询
                if not category and user_query and not re.search(r'[一-鿿]', user_query):
                    category = _to_category(user_query)
                # 3) 中文用户查询 → 领域映射 / 关键词
                if not category and user_query and re.search(r'[一-鿿]', user_query):
                    query_to_category = {
                        "强化学习": "reinforcement_learning",
                        "机器学习": "machine_learning",
                        "深度学习": "deep_learning",
                        "自然语言处理": "nlp",
                        "计算机视觉": "computer_vision",
                        "目标检测": "object_detection",
                        "图像分割": "image_segmentation",
                        "生成对抗网络": "gan",
                        " transformer": "transformer",
                        "大语言模型": "llm",
                        "多模态": "multimodal",
                        "元学习": "meta_learning",
                        "迁移学习": "transfer_learning",
                        "联邦学习": "federated_learning",
                        "因果推理": "causal_inference",
                        # 知识表示与推理相关（注意：知识图谱与图神经网络是不同领域，勿混淆）
                        "知识图谱": "knowledge_graph",
                        "知识表示": "knowledge_representation",
                        "本体": "ontology",
                        "图神经网络": "graph_neural_networks",
                        "图卷积": "graph_neural_networks",
                        "推荐系统": "recommender_system",
                        "时序": "time_series",
                        "异常检测": "anomaly_detection",
                        "联邦学习": "federated_learning",
                    }
                    for key, value in query_to_category.items():
                        if key in user_query:
                            category = value
                            break
                # 4) 关键词
                if not category and search_keywords:
                    category = _to_category(search_keywords[0])
                # 5) 兜底
                if not category:
                    category = "general"
                    logger.warning("category empty, fallback to 'general'")

                # 6) 匹配已有类别：若本次检索主题命中知识库中的类别，则复用以追加去重
                matched = _match_existing_category(
                    papers_dir, user_query, approved_topic_for_cat, search_keywords
                )
                if matched:
                    category = matched

                # 创建领域目录
                category_dir = papers_dir / category
                category_dir.mkdir(parents=True, exist_ok=True)

                # 每篇论文落到独立子目录 <category>/<safe_pid>/<safe_pid>.pdf，
                # 与精读结果文档（snap/lens/sphere_*.json）同目录共存。pdfs_dir 语义
                # 为「类别基目录」，ReaderAgent 内部会再建 <safe_pid>/ 子目录。
                pdfs_dir = category_dir

                # 只保存本次检索到的论文，不与已有论文混合
                current_papers = []
                for p in state["search_results"]:
                    paper_id = p.get("paper_id", "")
                    if not paper_id:
                        continue

                    # 从标题/摘要中提取关键字作为topics
                    title = p.get("title", "")
                    abstract = p.get("abstract", "")
                    keywords = p.get("keywords", [])

                    # 如果没有keywords，从标题和摘要中提取
                    if not keywords:
                        keywords = extract_keywords_from_text(title, abstract, search_keywords)

                    # 创建论文信息
                    # 规范化 paper_id 为安全文件名：DOI 含 '/' 会变成嵌套目录，统一替换为 '_'
                    from src.agents.reader import sanitize_paper_id_for_filename
                    safe_pid = sanitize_paper_id_for_filename(paper_id)
                    paper_info = {
                        "paper_id": paper_id,
                        "title": title,
                        "authors": p.get("authors", []),
                        "published_date": p.get("published_date", ""),
                        "abstract": abstract,
                        "pdf_url": p.get("pdf_url", ""),
                        "keywords": keywords,
                        "citations": p.get("citations", 0),
                        "pdf_path": str(pdfs_dir / safe_pid / f"{safe_pid}.pdf") if p.get("pdf_url") else "",
                    }
                    current_papers.append(paper_info)

                logger.info(f"Processed {len(current_papers)} papers for category: {category}")

                # 保存当前领域的论文到 JSON 文件
                # 追加去重：若该类别已有论文，合并后按 paper_id/小写 title 去重（新覆盖旧）
                category_file = category_dir / f"{category}.json"
                existing_papers = []
                existing_topic = user_query
                existing_keywords: list = []
                if category_file.exists():
                    try:
                        with open(category_file, "r", encoding="utf-8") as f:
                            existing_data = json.load(f)
                        existing_papers = existing_data.get("papers", []) or []
                        # 保留旧 topic（避免被新查询词覆盖，与索引语义一致）
                        if existing_data.get("topic"):
                            existing_topic = existing_data["topic"]
                        existing_keywords = existing_data.get("search_keywords", []) or []
                    except Exception as e:
                        logger.warning(f"Failed to read existing category file {category_file}: {e}")

                # 合并去重：以 paper_id 为主键，其次小写 title
                merged_by_key: Dict[str, Dict[str, Any]] = {}

                def _dedup_key(p: Dict[str, Any]) -> str:
                    pid = (p.get("paper_id") or "").strip()
                    if pid:
                        return f"id:{pid}"
                    return f"title:{(p.get('title') or '').strip().lower()}"

                for p in existing_papers:
                    merged_by_key[_dedup_key(p)] = p
                new_count = 0
                for p in current_papers:
                    k = _dedup_key(p)
                    if k not in merged_by_key:
                        new_count += 1
                    merged_by_key[k] = p  # 新覆盖旧

                merged_papers = list(merged_by_key.values())
                merged_keywords = list(dict.fromkeys(list(existing_keywords) + list(search_keywords)))

                category_metadata = {
                    "category": category,
                    "topic": existing_topic,
                    "search_keywords": merged_keywords,
                    "retrieved_at": dt.now().isoformat(),
                    "count": len(merged_papers),
                    "papers": merged_papers,
                }
                with open(category_file, "w", encoding="utf-8") as f:
                    json.dump(category_metadata, f, indent=2, ensure_ascii=False)

                logger.info(
                    f"Saved papers to: {category_file} | "
                    f"existing={len(existing_papers)} new={new_count} merged={len(merged_papers)}"
                )

                # 更新 all_papers.json —— 纯知识库索引(各类别的描述来自其自身文件,不被覆盖)
                all_papers_file = papers_dir / "all_papers.json"
                category_entries = {}

                # 保留已存在的其他类别
                if all_papers_file.exists():
                    try:
                        with open(all_papers_file, "r", encoding="utf-8") as f:
                            existing_all = json.load(f)
                            for cat, entry in existing_all.get("categories", {}).items():
                                if cat == category:
                                    continue
                                cat_path = entry.get("path") if isinstance(entry, dict) else entry
                                if cat_path and Path(cat_path).exists():
                                    category_entries[cat] = cat_path
                    except Exception:
                        pass

                # 加入/更新当前类别
                category_entries[category] = str(category_file)

                # 从各分类文件读取 topic/count,内联到索引
                categories_index = {}
                total_papers = 0
                for cat, cat_path in category_entries.items():
                    try:
                        with open(Path(cat_path), "r", encoding="utf-8") as f:
                            cat_data = json.load(f)
                        count = int(cat_data.get("count", 0) or 0)
                        total_papers += count
                        categories_index[cat] = {
                            "path": cat_path,
                            "topic": cat_data.get("topic", ""),
                            "count": count,
                        }
                    except Exception as e:
                        logger.warning(f"Failed to read category file {cat_path}: {e}")

                all_papers_metadata = {
                    "total_papers": total_papers,
                    "updated_at": dt.now().isoformat(),
                    "categories": categories_index,
                }

                with open(all_papers_file, "w", encoding="utf-8") as f:
                    json.dump(all_papers_metadata, f, indent=2, ensure_ascii=False)

                logger.info(f"Total papers in database: {all_papers_metadata['total_papers']}")
                state["papers_saved_path"] = str(all_papers_file)
                state["current_category"] = category
                state["pdfs_dir"] = str(pdfs_dir)
                logger.info(f"DEBUG: Set pdfs_dir in retrieval_node: {pdfs_dir}")
                state["papers_saved_path"] = str(all_papers_file)

                # workflow_mode 控制是否需要下载 PDF：
                # - full / search: 检索完成后，把候选论文清单（过滤掉已下载的）暂存到 pending_download_papers，
                #   通过 paper_download_approval_request 事件让用户确认下载哪些，再由 /api/workflow/approve-download
                #   触发真正的下载。检索与下载解耦。
                workflow_mode = (state.get("workflow_mode") or "full").strip().lower()
                if workflow_mode in ("full", "search"):
                    pending = build_pending_download_papers(state, pdfs_dir)
                    # 统计被跳过的已下载篇数（用于 details.already_downloaded）
                    from src.agents.reader import sanitize_paper_id_for_filename as _safe_pid
                    from config.settings import get_config
                    _papers_with_pdf = [p for p in state["search_results"] if p.get("pdf_url")]
                    _seen = set()
                    _skipped = 0
                    for p in _papers_with_pdf[:get_config().max_pdf_download]:
                        pid = p.get("paper_id", "")
                        if pid in _seen:
                            continue
                        _seen.add(pid)
                        if (pdfs_dir / _safe_pid(pid) / f"{_safe_pid(pid)}.pdf").exists():
                            _skipped += 1

                    logger.info(
                        f"Download candidates: {len(pending)} (skipped {_skipped} already-downloaded, "
                        f"{len(_papers_with_pdf)} had pdf_url, cap={get_config().max_pdf_download})"
                    )

                    state["pending_download_papers"] = pending
                    state["download_approval"] = "pending"
                    state["literature_data"] = []
                    state["reading_errors"] = []

                    attach_approval_categories(state, papers_dir)

                    _emit_progress(
                        "paper_download_approval_request",
                        details={
                            "pending_download_papers": pending,
                            "papers_found": len(state["search_results"]),
                            "already_downloaded": _skipped,
                            "matched_category": state["pending_matched_category"],
                            "existing_categories": state["pending_categories"],
                        },
                    )
                else:
                    # 非下载模式（none 等）：不下载 PDF
                    logger.info(f"workflow_mode={workflow_mode}, skip PDF download")
                    state["literature_data"] = []
                    state["reading_errors"] = []
                    state["pending_download_papers"] = []
            except Exception as e:
                logger.warning(f"Failed to save papers metadata: {e}")

        # Mark retrieval status in state
        state["retrieval_successful"] = num_papers > 0

        if not state["retrieval_successful"]:
            logger.warning("No papers found! Retrieval failed or returned empty results.")

        if result.errors:
            state["error_messages"].extend(result.errors)
            for err in result.errors:
                logger.warning(f"Retrieval warning: {err}")

    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        state["error_messages"].append(f"Retrieval failed: {e}")
        state["retrieval_successful"] = False
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Retrieval error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting RETRIEVAL node")
    return state


@traceable(name="reading_node")
@_metrics.time("workflow_phase_duration_seconds", labels={"phase": "reading"})
def reading_node(state: GraphState) -> GraphState:
    """Reader agent node - parse downloaded PDFs (downloaded in retrieval_node)."""
    logger.info(">>> Entering READING node")
    state["current_phase"] = PipelinePhase.READING
    _emit_progress("reading")

    try:
        # 如果已经在retrieval_node中下载并解析过了，直接使用之前的结果
        if state.get("literature_data"):
            logger.info("Using pre-downloaded literature data from retrieval_node")
            logger.info(
                f"Reading completed: {len(state.get('literature_data', []))} papers parsed"
            )
            return state

        # 如果没有预先下载的数据，回退到旧的逻辑（保留兼容性）
        papers_to_read = state.get("search_results", [])
        logger.info(f"Starting to read {len(papers_to_read)} papers (fallback mode)")

        import os
        base_dir = os.path.abspath(".")
        pdfs_dir = state.get("pdfs_dir", os.path.join(base_dir, "data/papers/general"))
        if not os.path.isabs(pdfs_dir):
            pdfs_dir = os.path.join(base_dir, pdfs_dir)
        logger.info(f"PDF directory: {pdfs_dir}")

        from src.agents.reader import ReaderAgent
        agent = ReaderAgent(max_workers=4)
        result = agent.run(papers_to_read, download_dir=pdfs_dir)

        state["literature_data"] = result.literature_data
        state["reading_errors"] = result.reading_summary.get("failed_papers", [])

        logger.info(
            f"Reading completed: {result.completed}/{result.total_papers} papers parsed | "
            f"Total words: {result.reading_summary.get('total_words', 0)}"
        )

        if state.get("reading_errors"):
            logger.warning(f"Failed to read {len(state['reading_errors'])} papers")

    except Exception as e:
        logger.error(f"Reading failed: {e}")
        state["error_messages"].append(f"Reading failed: {e}")
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Reading error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting READING node")
    return state


@traceable(name="analysis_node")
@_metrics.time("workflow_phase_duration_seconds", labels={"phase": "analysis"})
def analysis_node(state: GraphState) -> GraphState:
    """Analyzer agent node - cluster and synthesize."""
    logger.info(">>> Entering ANALYSIS node")
    state["current_phase"] = PipelinePhase.ANALYSIS
    _emit_progress("analysis")

    try:
        literature_data = state.get("literature_data", [])
        logger.info(f"Starting analysis of {len(literature_data)} papers")

        result = analyze_literature(literature_data=literature_data, cluster_method="topic")

        state["literature_clusters"] = result.get("literature_clusters", [])
        state["global_knowledge"] = result.get("global_knowledge", {})

        num_clusters = len(state.get("literature_clusters", []))
        knowledge = state.get("global_knowledge", {})

        logger.info(
            f"Analysis completed: {num_clusters} clusters identified | "
            f"Key findings: {len(knowledge.get('key_findings', []))}"
        )

        if knowledge.get("future_directions"):
            logger.debug(f"Future directions: {knowledge['future_directions'][:3]}")

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        state["error_messages"].append(f"Analysis failed: {e}")
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Analysis error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting ANALYSIS node")
    return state


@traceable(name="outline_node")
@_metrics.time("workflow_phase_duration_seconds", labels={"phase": "outline"})
def outline_node(state: GraphState) -> GraphState:
    """Writer agent node - generate outline."""
    logger.info(">>> Entering OUTLINE node")
    state["current_phase"] = PipelinePhase.OUTLINE
    _emit_progress("outline")

    try:
        topic = state.get("research_topic", state.get("user_query", ""))
        logger.info(f"Generating outline for: {topic}")

        agent = WriterAgent()

        outline = agent.generate_outline(
            global_knowledge=state.get("global_knowledge", {}),
            topic=topic,
        )

        state["outline"] = {
            "title": outline.title,
            "abstract_requirements": outline.abstract_requirements,
            "sections": [
                {
                    "section_id": s.section_id,
                    "title": s.title,
                    "subsections": s.subsections,
                    "key_points": s.key_points,
                }
                for s in outline.sections
            ],
            "total_estimated_words": outline.total_estimated_words,
        }

        num_sections = len(outline.sections)
        logger.info(
            f"Outline generated: {num_sections} sections | "
            f"Estimated words: {outline.total_estimated_words}"
        )
        logger.debug(f"Outline title: {outline.title}")

        _emit_progress("outline_result", details={"outline_result": state["outline"]})

    except Exception as e:
        logger.error(f"Outline generation failed: {e}")
        state["error_messages"].append(f"Outline generation failed: {e}")
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Outline error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting OUTLINE node")
    return state


@traceable(name="writing_node")
@_metrics.time("workflow_phase_duration_seconds", labels={"phase": "writing"})
def writing_node(state: GraphState) -> GraphState:
    """Writer agent node - write sections."""
    logger.info(">>> Entering WRITING node")
    state["current_phase"] = PipelinePhase.WRITING
    _emit_progress("writing")

    try:
        topic = state.get("research_topic", state.get("user_query", ""))
        logger.info(f"Starting paper writing for: {topic}")

        # 构建编号参考文献列表，供写作时角标引用 [n]
        reference_list = build_reference_list(state)
        state["reference_list"] = reference_list
        logger.info(f"Built reference list: {len(reference_list)} papers")

        agent = WriterAgent()

        def _on_token(section_id: str, section_title: str, token: str):
            _emit_progress("writing_token", details={"writing_token": {"token": token, "section_id": section_id, "section_title": section_title}})

        result = agent.run(
            global_knowledge=state.get("global_knowledge", {}),
            topic=topic,
            literature_clusters=state.get("literature_clusters", []),
            reference_list=reference_list,
            stream_callback=_on_token,
        )

        gs_format = agent.to_graphstate_format(result)
        state["chapter_drafts"] = gs_format["chapter_drafts"]
        state["final_paper"] = gs_format["final_paper"]

        logger.info(
            f"Writing completed: {result.completed_sections}/{len(result.sections)} sections | "
            f"Total words: {result.total_words}"
        )

        if result.failed_sections > 0:
            logger.warning(f"Failed to write {result.failed_sections} sections")

        _emit_progress("writing_done", details={"writing_done": {"paper_content": state.get("final_paper", "")}})

    except Exception as e:
        logger.error(f"Writing failed: {e}")
        state["error_messages"].append(f"Writing failed: {e}")
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Writing error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting WRITING node")
    return state


@traceable(name="revision_node")
@_metrics.time("workflow_phase_duration_seconds", labels={"phase": "revision"})
def revision_node(state: GraphState) -> GraphState:
    """Reviewer agent node - review and finalize."""
    logger.info(">>> Entering REVISION node")
    state["current_phase"] = PipelinePhase.REVISION
    _emit_progress("revision")

    try:
        topic = state.get("research_topic", state.get("user_query", ""))
        logger.info(f"Starting revision for: {topic}")

        # 先准备好编号参考文献清单：既用于引言/结论的 [n] 角标引用，也用于文末追加目录
        reference_list = state.get("reference_list") or build_reference_list(state)
        state["reference_list"] = reference_list
        logger.info(f"Revision reference list: {len(reference_list)} papers")

        agent = ReviewerAgent()

        result = agent.run(
            paper_content=state.get("final_paper", ""),
            topic=topic,
            outline=state.get("outline"),
            global_knowledge=state.get("global_knowledge", {}),
            generate_front_matter=True,
            reference_list=reference_list,
        )

        gs_format = agent.to_graphstate_format(result)
        state["revision_feedback"] = gs_format["revision_feedback"]
        state["abstract"] = gs_format["abstract"]
        state["introduction"] = gs_format["introduction"]
        state["conclusion"] = gs_format["conclusion"]

        # 在最终报告末尾追加参考文献目录，确保正文中的 [n] 角标有对应出处
        bibliography = format_bibliography(reference_list)
        final_review = gs_format["final_review"] or ""
        if bibliography:
            if "## 参考文献" not in final_review:
                final_review = final_review.rstrip() + "\n\n" + bibliography
        state["final_review"] = final_review

        _emit_progress("review_result", details={"review_result": {
            "revision_feedback": state.get("revision_feedback", ""),
            "final_review": state.get("final_review", ""),
        }})

        # Update phase to final
        state["current_phase"] = PipelinePhase.FINAL

        paper_length = len(state.get("final_review", ""))
        logger.info(
            f"Revision completed: Final paper {paper_length} chars | "
            f"Abstract: {len(state.get('abstract', ''))} chars"
        )

        # Flush accumulated token usage from the global tracker into state
        # before logging the summary, so the final report reflects real usage.
        sync_token_usage_to_state(state)

        # Log token usage summary
        token_usage = state.get("token_usage", {})
        if token_usage:
            cost = token_usage.get("estimated_cost_usd", 0)
            tokens = token_usage.get("total_input_tokens", 0) + token_usage.get("total_output_tokens", 0)
            logger.info(
                f"Token Usage Summary: {tokens} tokens | "
                f"Estimated cost: ${cost:.4f} | "
                f"Requests: {token_usage.get('request_count', 0)}"
            )

        # Save final report to data/outputs/
        try:
            from pathlib import Path
            from datetime import datetime as dt
            import re

            # 直接在outputs/目录下生成文件，不建子目录
            output_dir = Path("data/outputs")
            output_dir.mkdir(parents=True, exist_ok=True)

            # 清理topic名称，创建安全的文件名
            safe_topic = re.sub(r'[^\w一-鿿\-\s]', '_', topic)[:50]
            safe_topic = safe_topic.replace(" ", "")  # 移除空格

            # 生成时间戳
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")

            # 保存Markdown格式的报告 - 直接在outputs/目录
            md_file = output_dir / f"{safe_topic}_{timestamp}.md"
            with open(md_file, "w", encoding="utf-8") as f:
                # 添加标题和元信息（不再单独写摘要，final_review已包含）
                f.write(f"# {topic}\n\n")
                f.write(f"**生成时间**: {dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("---\n\n")
                # 写入正文（final_review 已包含摘要、引言、正文、结论）
                f.write(state.get("final_review", ""))

            logger.info(f"Final report saved to: {md_file}")
            state["report_path"] = str(md_file)

        except Exception as e:
            logger.warning(f"Failed to save final report: {e}")

    except Exception as e:
        logger.error(f"Revision failed: {e}")
        state["error_messages"].append(f"Revision failed: {e}")
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Revision error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting REVISION node")
    logger.info("=" * 50)
    logger.info("Workflow Complete!")
    logger.info("=" * 50)
    return state


# ==================== Conditional Edges ====================

def check_retrieval_result(state: GraphState) -> str:
    """
    Check retrieval result and decide next step.

    Returns:
        - "success": Papers found, proceed normally
        - "no_papers": No papers found, will warn user and continue
        - "failed": Retrieval failed with error
        - "done": search 模式检索+下载完成后即结束，不进入阅读/分析/写作
    """
    # search 模式：检索 + 下载完成后直接结束，不生成综述
    mode = (state.get("workflow_mode") or "full").strip().lower()
    if mode == "search":
        logger.info("workflow_mode=search, end workflow after retrieval+download")
        return "done"

    # 检索后若有待确认下载的论文，暂停图执行，等用户确认下载
    if state.get("pending_download_papers"):
        logger.info("Pending download approval, pausing graph")
        return "done"

    # Check if retrieval was successful
    if state.get("retrieval_successful", True):
        return "success"

    # Check for errors
    if state.get("current_phase") == PipelinePhase.ERROR:
        logger.warning("Retrieval had errors, proceeding with caution")
        return "no_papers"

    # No papers found
    logger.warning("No papers found in retrieval")
    return "no_papers"


def should_approve_retrieval(state: GraphState) -> str:
    """Check if human approval needed for retrieval."""
    # 检索后若有待确认下载的论文，暂停图执行，等 /api/workflow/approve-download 触发后续下载
    if state.get("pending_download_papers"):
        return "done"

    # search 模式：检索 + 下载完成后直接结束
    mode = (state.get("workflow_mode") or "full").strip().lower()
    if mode == "search":
        return "done"

    if state.get("auto_approve", False):
        return "approved"

    # Check approval status
    approval = state.get("retrieval_approval")
    if approval == ApprovalStatus.APPROVED:
        return "approved"
    elif approval == ApprovalStatus.REJECTED:
        return "retry"

    return "needs_approval"


def should_approve_outline(state: GraphState) -> str:
    """Check if human approval needed for outline."""
    # 默认自动通过，无需人工审批
    if state.get("auto_approve", True):
        return "approved"

    approval = state.get("outline_approval")
    if approval == ApprovalStatus.APPROVED:
        return "approved"
    elif approval == ApprovalStatus.REJECTED:
        return "retry"

    return "approved"  # 默认批准


# ==================== Build Graph ====================

def create_workflow() -> StateGraph:
    """
    Create the complete Scira workflow graph.

    Returns:
        Compiled LangGraph workflow
    """

    logger.info("Creating LangGraph workflow...")

    # Create graph
    workflow = StateGraph(GraphState)

    # Add nodes
    workflow.add_node("init", init_state)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("reading", reading_node)
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("outline", outline_node)
    workflow.add_node("writing", writing_node)
    workflow.add_node("revision", revision_node)

    # Set entry point
    workflow.set_entry_point("init")

    # Add edges
    workflow.add_edge("init", "retrieval")

    # Retrieval result check - warn if no papers found
    workflow.add_conditional_edges(
        "retrieval",
        check_retrieval_result,
        {
            "success": "reading",
            "no_papers": "reading",  # Still proceed but will use fallback
            "failed": "reading",    # Still proceed but will use fallback
            "done": END,            # 部分模式（search_only/search_download）检索后结束
        }
    )

    # Retrieval -> Reading (after approval)
    workflow.add_conditional_edges(
        "retrieval",
        should_approve_retrieval,
        {
            "approved": "reading",
            "retry": "retrieval",  # Retry with new keywords
            "needs_approval": END,  # Wait for human (in real app, would pause)
            "done": END,            # 部分模式检索后结束
        }
    )

    workflow.add_edge("reading", "analysis")
    workflow.add_edge("analysis", "outline")

    # Outline -> Writing (after approval)
    workflow.add_conditional_edges(
        "outline",
        should_approve_outline,
        {
            "approved": "writing",
            "retry": "outline",
            "needs_approval": END,
        }
    )

    workflow.add_edge("writing", "revision")
    workflow.add_edge("revision", END)

    logger.info("LangGraph workflow created successfully")
    return workflow.compile()


# ==================== Run Functions ====================

def run_workflow(
    user_query: str,
    auto_approve: bool = False,
    progress_callback=None,
    workflow_mode: str = "full",
    **kwargs,
) -> GraphState:
    """
    Run the workflow.

    Args:
        user_query: User's research query
        auto_approve: Skip human approvals
        progress_callback: 可选回调 cb(phase, progress, message, details)，
            节点进入/子阶段切换时被调用，用于把阶段同步到 SSE。
        workflow_mode: 工作流模式
            - "full": 完整流程（检索→阅读→分析→写作→审查）
            - "search_only": 仅检索论文（不下载 PDF、不生成报告）
            - "search_download": 检索 + 下载 PDF（不生成报告）
        **kwargs: Additional state fields

    Returns:
        Final state with results
    """
    workflow_mode = (workflow_mode or "full").strip().lower()
    # 生成 run_id 并 set contextvar，使本工作流所有日志/metrics 可关联
    run_id = new_run_id()
    set_run_id(run_id)
    logger.info(
        f"Starting workflow | Query: {user_query} | Auto-approve: {auto_approve} | Mode: {workflow_mode}"
    )

    # Initialize state
    initial_state: GraphState = {
        "user_query": user_query,
        "research_topic": user_query,  # Will be refined by retrieval
        "auto_approve": auto_approve,
        "workflow_mode": workflow_mode,
        "human_approvals": {},
        "current_phase": PipelinePhase.INIT,
        "error_messages": [],
        "retry_count": 0,
        "run_id": run_id,
        **kwargs,
    }

    # Create and run workflow
    app = create_workflow()

    # Run with config
    config = {"recursion_limit": 100}

    _metrics.counter("workflow_started_total").inc()
    _metrics.gauge("workflow_active").inc()
    # 注册进度回调（线程本地），供各节点 _emit_progress 推送阶段
    _set_progress_callback(progress_callback)
    try:
        # 直接用 invoke 拿最终 state。
        # 注意：不能再用 app.stream(...) 的「chunk={node: state}」假设——
        # 当前 langgraph 默认 stream_mode="values"，每个 chunk 是完整 state dict 本身，
        # 旧代码 list(chunk.values())[-1] 取到的是某字段的值（非 dict），导致 final_state
        # 始终停留在 initial_state，retrieval_node 写入的 pdfs_dir/current_category 等丢失，
        # run_download_and_rest 因此回退到 general 目录下载 PDF。实时阶段更新由各节点内
        # _emit_progress 经线程本地回调推送，不依赖 stream。
        final_state = app.invoke(initial_state, config)
    except Exception:
        _metrics.counter("errors_total").inc({"component": "workflow"})
        _metrics.counter("workflow_completed_total").inc(labels={"status": "failed"})
        raise
    finally:
        _clear_progress_callback()
        _metrics.gauge("workflow_active").dec()

    # Flush token usage regardless of which exit path the graph took
    # (search mode ends after retrieval; full mode pauses at download approval).
    sync_token_usage_to_state(final_state)
    _metrics.counter("workflow_completed_total").inc(labels={"status": "success"})
    return final_state


def run_download_and_rest(
    state: GraphState,
    selected_papers: List[Dict[str, Any]],
    progress_callback=None,
) -> GraphState:
    """
    用户在下载确认卡片上勾选论文并提交后，由 /api/workflow/approve-download 调用。

    流程：
    1. 对 selected_papers 执行 PDF 下载 + 解析（ReaderAgent.run），填充 literature_data
    2. search 模式：到此处结束（不生成综述）
    3. full 模式：依次执行 reading → analysis → outline → writing → revision 节点
    """
    logger.info(f">>> run_download_and_rest: {len(selected_papers)} papers to download")
    # 恢复 run_id 上下文（state 来自前一次 run_workflow 的暂停点）
    rid = state.get("run_id")
    if rid:
        set_run_id(rid)
    _set_progress_callback(progress_callback)
    try:
        pdfs_dir = state.get("pdfs_dir")
        if not pdfs_dir:
            # 兜底：从 current_category 重建（类别基目录，ReaderAgent 内部再建 per-paper 子目录）
            from pathlib import Path as _P
            cat = state.get("current_category", "general")
            pdfs_dir = str(_P("data/papers") / cat)
            state["pdfs_dir"] = pdfs_dir

        if selected_papers:
            from src.agents.reader import ReaderAgent

            _total_to_download = len(selected_papers)
            _completed_count = {"n": 0}

            _emit_progress(
                "retrieval_download",
                details={
                    "papers_to_download": _total_to_download,
                    "papers_downloading": 0,
                    "current_downloading": "",
                },
            )

            def _paper_cb(paper_id: str, status: str, error: Optional[str] = None, title: Optional[str] = None):
                if status == "downloading":
                    _emit_progress(
                        "download",
                        details={
                            "per_paper": {"paper_id": paper_id, "status": status, "error": error},
                            "current_downloading": title or paper_id,
                        },
                    )
                else:  # success / failed
                    _completed_count["n"] += 1
                    _emit_progress(
                        "download",
                        details={
                            "per_paper": {"paper_id": paper_id, "status": status, "error": error},
                            "papers_downloading": _completed_count["n"],
                            "current_downloading": "",
                        },
                    )

            agent = ReaderAgent(max_workers=4, paper_callback=_paper_cb)
            download_result = agent.run(selected_papers, download_dir=str(pdfs_dir))
            logger.info(
                f"PDF download completed: {download_result.completed}/{download_result.total_papers}"
            )
            _emit_progress(
                "reading",
                details={
                    "papers_reading": download_result.completed,
                    "total_papers": download_result.total_papers,
                },
            )
            state["literature_data"] = download_result.literature_data
            state["reading_errors"] = download_result.reading_summary.get("failed_papers", [])
        else:
            state["literature_data"] = []
            state["reading_errors"] = []

        state["download_approval"] = ApprovalStatus.APPROVED
        state["pending_download_papers"] = []

        workflow_mode = (state.get("workflow_mode") or "full").strip().lower()
        if workflow_mode == "search":
            # search 模式：下载完成即结束，不生成综述
            logger.info("workflow_mode=search, done after download")
            sync_token_usage_to_state(state)
            return state

        # 空材料短路：全部下载失败时不进入后续节点
        if not state.get("literature_data"):
            logger.warning("No literature_data after download, short-circuit before reading_node")
            sync_token_usage_to_state(state)
            return state

        # full 模式：手动串联后续节点
        state = reading_node(state)
        state = analysis_node(state)
        state = outline_node(state)
        state = writing_node(state)
        state = revision_node(state)
        sync_token_usage_to_state(state)
        return state
    finally:
        _clear_progress_callback()


# ==================== Knowledge Base → Writing ====================

def _load_reading_summary(papers_dir: "Path", category: str, paper_id: str) -> Optional[Dict[str, Any]]:
    """
    读取一篇论文的精读结果文档（不读 PDF 原文）。

    优先级：lens_zh.json > snap_zh.json > sphere_zh.json。
    返回 {markdown, mode, word_count, sections_count} 或 None（无任何精读结果）。
    """
    from src.agents.reader import sanitize_paper_id_for_filename as _safe_pid
    safe = _safe_pid(paper_id)
    paper_dir = papers_dir / category / safe
    if not paper_dir.is_dir():
        return None
    for mode in ("lens", "snap", "sphere"):
        f = paper_dir / f"{mode}_zh.json"
        if f.exists():
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                md = data.get("markdown", "") or ""
                meta = {}
                if data.get("json"):
                    try:
                        import json as _json
                        meta = _json.loads(data["json"]) if isinstance(data["json"], str) else data["json"]
                    except Exception:
                        meta = {}
                return {
                    "markdown": md,
                    "mode": mode,
                    "word_count": int(meta.get("word_count", 0) or 0),
                    "sections_count": int(meta.get("sections_count", 0) or 0),
                }
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")
    return None


def synthesize_from_reading_summaries(
    literature_data: List[Dict[str, Any]],
    topic: str,
) -> Dict[str, Any]:
    """
    用一次 LLM 调用，基于精读结果文档合成 global_knowledge 与 literature_clusters。

    与 analyze_literature 的区别：输入是精读 markdown（已结构化分析）而非 PDF 解析的
    section_names/word_count，因此合成质量更高，且无需检索/PDF。每条 cluster 内的 papers
    携带 reading_summary，供下游 WriterAgent 在写作时引用具体内容。

    失败时回退到结构化拼装（按 paper_id 分簇），保证总有结果。
    """
    from src.agents.base import BaseAgent
    from src.agents.prompts import WRITER_SYSTEM
    from langchain_core.messages import HumanMessage, SystemMessage

    # 精读摘要条目（截断超长 markdown，避免 token 爆炸）
    SUMMARY_CHAR_CAP = 6000
    entries = []
    for p in literature_data:
        ec = p.get("extracted_content") or {}
        md = (ec.get("reading_summary") or "").strip()
        if not md:
            continue
        if len(md) > SUMMARY_CHAR_CAP:
            md = md[:SUMMARY_CHAR_CAP] + "\n…（已截断）"
        authors = p.get("authors") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        author_str = ", ".join(authors[:3]) + (" 等" if len(authors) > 3 else "") if authors else "佚名"
        entries.append({
            "paper_id": p.get("paper_id", ""),
            "title": p.get("title", ""),
            "authors": author_str,
            "year": (p.get("published_date") or "")[:4],
            "reading_summary": md,
        })

    if not entries:
        # 无精读内容：返回最小可用结构
        return {
            "global_knowledge": {
                "research_background": f"基于 {len(literature_data)} 篇知识库论文生成综述。",
                "mainstream_methods": [],
                "performance_comparison": [],
                "research_gaps": [],
                "future_directions": [],
                "key_findings": [],
            },
            "literature_clusters": [
                {
                    "cluster_id": "kb_papers",
                    "theme": topic,
                    "papers": [{"paper_id": p.get("paper_id"), "title": p.get("title")} for p in literature_data],
                }
            ],
        }

    papers_block = json.dumps(entries, ensure_ascii=False, indent=2)

    prompt = f"""你是文献分析助手。基于下列多篇论文的「精读结果文档」（已含一句话总结、核心贡献、方法、实验、局限等），请合成：

1. global_knowledge：跨论文的综合知识，字段：
   - research_background（研究背景，200-400字）
   - mainstream_methods（主流方法列表，每项含方法名+简述+代表论文 paper_id）
   - performance_comparison（性能对比要点列表）
   - research_gaps（研究空白/挑战列表）
   - future_directions（未来方向列表）
   - key_findings（关键发现列表）
2. literature_clusters：按主题/方法把论文分簇（1-5 个簇），每簇：
   - cluster_id, theme（簇主题）
   - papers：[{{"paper_id","title","authors","year","contribution":"该论文在该簇中的作用"}}]

研究主题：{topic}

论文精读结果（JSON）：
{papers_block}

只返回 JSON 对象，键为 global_knowledge 与 literature_clusters，不要 Markdown 代码块。"""

    try:
        from config.settings import get_config, get_llm_client
        from src.utils.logger import record_token_usage
        cfg = get_config()
        llm = get_llm_client(cfg)
        resp = llm.invoke([SystemMessage(content="你是文献分析助手，只返回 JSON。"), HumanMessage(content=prompt)])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        # 记录 token 到全局 tracker（后续 sync_token_usage_to_state 会刷进 state）
        record_token_usage(resp, cfg.model.model_name or "gpt-4o")
        # 提取 JSON
        import re as _re
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m:
            raise ValueError("no JSON in response")
        parsed = json.loads(m.group())
        # 兜底字段
        gk = parsed.get("global_knowledge") or {}
        for k in ("research_background", "mainstream_methods", "performance_comparison",
                  "research_gaps", "future_directions", "key_findings"):
            gk.setdefault(k, [] if k != "research_background" else "")
        parsed["global_knowledge"] = gk
        parsed.setdefault("literature_clusters", [])
        return parsed
    except Exception as e:
        logger.warning(f"synthesize_from_reading_summaries LLM failed: {e}")
        # 回退：单簇 + 最小 global_knowledge
        return {
            "global_knowledge": {
                "research_background": f"基于 {len(entries)} 篇知识库论文生成综述。",
                "mainstream_methods": [],
                "performance_comparison": [],
                "research_gaps": [],
                "future_directions": [],
                "key_findings": [],
            },
            "literature_clusters": [
                {
                    "cluster_id": "kb_papers",
                    "theme": topic,
                    "papers": entries,
                }
            ],
        }


def run_workflow_from_knowledge_bases(
    categories: List[str],
    topic: str,
    progress_callback=None,
    session_id: Optional[str] = None,
    **kwargs,
) -> GraphState:
    """
    从已有知识库生成综述：跳过检索/下载/精读，直接读精读结果文档，
    合成 global_knowledge/literature_clusters 后跑 outline→writing→revision。

    Args:
        categories: 选中的知识库目录名列表（data/papers/<name>）
        topic: 用户本次想生成的综述主题/聚焦方向
        progress_callback: 同 run_workflow 的 cb(phase, progress, message, details)
        session_id: 会话 ID（仅用于日志关联，非必需）
    """
    from pathlib import Path

    run_id = new_run_id()
    set_run_id(run_id)
    logger.info(f"Starting KB-based workflow | categories={categories} | topic={topic}")

    papers_dir = Path("data/papers")
    state: GraphState = {
        "user_query": topic,
        "research_topic": topic,
        "auto_approve": True,
        "workflow_mode": "full",
        "source_categories": list(categories or []),
        "human_approvals": {},
        "current_phase": PipelinePhase.INIT,
        "error_messages": [],
        "retry_count": 0,
        "run_id": run_id,
        "search_results": [],
        "literature_data": [],
        "reading_errors": [],
        "token_usage": {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "request_count": 0,
            "estimated_cost_usd": 0.0,
        },
    }
    reset_token_tracker()
    _set_progress_callback(progress_callback)
    try:
        _emit_progress("init")
        _emit_progress("reading", message="正在加载知识库精读结果...")

        literature_data: List[Dict[str, Any]] = []
        skipped: List[str] = []
        for cat in categories or []:
            cat_file = papers_dir / cat / f"{cat}.json"
            if not cat_file.exists():
                logger.warning(f"KB category file not found: {cat_file}")
                skipped.append(cat)
                continue
            try:
                with open(cat_file, "r", encoding="utf-8") as f:
                    cat_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read {cat_file}: {e}")
                skipped.append(cat)
                continue

            for p in cat_data.get("papers", []) or []:
                pid = p.get("paper_id", "")
                if not pid:
                    continue
                rs = _load_reading_summary(papers_dir, cat, pid)
                if rs is None:
                    # 无精读结果：仍纳入但 reading_summary 为空（writer 仅凭元数据弱引用）
                    rs = {"markdown": "", "mode": None, "word_count": 0, "sections_count": 0}
                authors = p.get("authors", [])
                if isinstance(authors, str):
                    authors = [a.strip() for a in authors.split(";") if a.strip()]
                literature_data.append({
                    "paper_id": pid,
                    "title": p.get("title", ""),
                    "authors": authors,
                    "abstract": p.get("abstract", ""),
                    "published_date": p.get("published_date", ""),
                    "pdf_url": p.get("pdf_url", ""),
                    "source": p.get("source", cat),
                    "extracted_content": {
                        "reading_summary": rs["markdown"],
                        "section_names": [],
                        "word_count": rs["word_count"],
                        "reference_count": 0,
                        "reading_mode": rs["mode"],
                    },
                    "reading_status": "completed" if rs["markdown"] else "skipped",
                })

        state["literature_data"] = literature_data
        state["current_category"] = categories[0] if categories else "general"
        state["pdfs_dir"] = str(papers_dir / (categories[0] if categories else "general"))

        logger.info(
            f"KB-based workflow loaded {len(literature_data)} papers "
            f"({sum(1 for p in literature_data if p['extracted_content']['reading_summary'])} with reading summary) "
            f"from {len(categories)} categories, skipped={skipped}"
        )

        if not literature_data:
            state["error_messages"].append("所选知识库中没有可用论文")
            sync_token_usage_to_state(state)
            return state

        # analysis：用精读结果合成
        _emit_progress("analysis", message="正在分析精读结果...")
        synth = synthesize_from_reading_summaries(literature_data, topic)
        state["literature_clusters"] = synth.get("literature_clusters", [])
        state["global_knowledge"] = synth.get("global_knowledge", {})

        # 编号参考文献清单（基于 literature_data，绝不 LLM 生成）
        state["reference_list"] = build_reference_list(state)
        logger.info(f"KB-based reference list: {len(state['reference_list'])} papers")

        # outline → writing → revision（既有节点）
        state = outline_node(state)
        # writing_node 内部会调 build_reference_list，但我们已设 reference_list，会被覆盖为同值
        state = writing_node(state)
        state = revision_node(state)
        sync_token_usage_to_state(state)
        return state
    finally:
        _clear_progress_callback()


def run_workflow_stream(
    user_query: str,
    auto_approve: bool = False,
):
    """
    Run workflow with streaming output.

    Yields:
        State updates as workflow progresses
    """
    initial_state: GraphState = {
        "user_query": user_query,
        "research_topic": user_query,
        "auto_approve": auto_approve,
        "human_approvals": {},
        "current_phase": PipelinePhase.INIT,
        "error_messages": [],
        "retry_count": 0,
        "run_id": new_run_id(),
    }
    set_run_id(initial_state["run_id"])

    app = create_workflow()
    config = {"recursion_limit": 100}

    for state in app.stream(initial_state, config):
        yield state


# ==================== Main Entry ====================

if __name__ == "__main__":
    # Example usage
    result = run_workflow(
        user_query="What are the latest advances in diffusion models for drug discovery?",
        auto_approve=True,
    )

    print("=" * 50)
    print("WORKFLOW COMPLETE")
    print("=" * 50)
    print(f"Phase: {result.get('current_phase')}")
    print(f"Errors: {result.get('error_messages', [])}")

    if result.get("final_review"):
        print(f"\nPaper length: {len(result['final_review'])} chars")
        print(f"\nFirst 500 chars:\n{result['final_review'][:500]}...")
