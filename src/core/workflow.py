"""
Scira LangGraph Workflow

Defines the complete research assistant pipeline as a LangGraph DAG.
Includes logging, observability, and token tracking.
"""

from __future__ import annotations

import os
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

def prepare_retrieval(user_query: str, modification: Optional[str] = None) -> Dict[str, Any]:
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
        strategy = agent.generate_search_strategy(topic, key_concepts)
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

# Import logging and token tracking
from src.utils.logger import (
    logger,
    setup_logging,
    get_token_tracker,
    TokenTracker,
)

# Initialize logging
setup_logging(level="INFO", verbose=False)


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


# ==================== Node Functions ====================

@traceable(name="init_state")
def init_state(state: GraphState) -> GraphState:
    """Initialize the state with user query."""
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

    # Default values
    if "auto_approve" not in state:
        state["auto_approve"] = False

    logger.info("State initialized successfully")
    return state


@traceable(name="retrieval_node")
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
        result = agent.run(
            user_query=user_query,
            auto_approve=state.get("auto_approve", False),
            approved_topic=approved_topic,
            approved_keywords=approved_keywords,
        )

        # Update state
        state["search_keywords"] = result.search_strategy.keywords

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

                # 创建领域目录
                category_dir = papers_dir / category
                category_dir.mkdir(parents=True, exist_ok=True)

                # 创建pdfs子目录
                pdfs_dir = category_dir / "pdfs"
                pdfs_dir.mkdir(parents=True, exist_ok=True)

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
                    # 规范化 paper_id 为安全文件名：DOI 含 '/' 会变成嵌套目录，
                    # 统一替换为 '_'，保证 pdf_path 指向扁平 pdfs/ 目录下的文件，
                    # 与 ReaderAgent 实际落盘的文件名一致
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
                        "pdf_path": str(pdfs_dir / f"{safe_pid}.pdf") if p.get("pdf_url") else "",
                    }
                    current_papers.append(paper_info)

                logger.info(f"Processed {len(current_papers)} papers for category: {category}")

                # 保存当前领域的论文到 JSON 文件
                category_file = category_dir / f"{category}.json"
                category_metadata = {
                    "category": category,
                    "topic": user_query,
                    "search_keywords": search_keywords,
                    "retrieved_at": dt.now().isoformat(),
                    "count": len(current_papers),
                    "papers": current_papers
                }
                with open(category_file, "w", encoding="utf-8") as f:
                    json.dump(category_metadata, f, indent=2, ensure_ascii=False)

                logger.info(f"Saved {len(current_papers)} papers to: {category_file}")

                # 更新 all_papers.json - 记录所有领域
                all_papers_file = papers_dir / "all_papers.json"
                all_papers_metadata = {
                    "topic": user_query,
                    "search_keywords": search_keywords,
                    "retrieved_at": dt.now().isoformat(),
                    "total_papers": len(current_papers),
                    "current_category": category,
                    "categories": {}
                }

                # 读取已有的 all_papers.json，保留其他领域的记录
                if all_papers_file.exists():
                    try:
                        with open(all_papers_file, "r", encoding="utf-8") as f:
                            existing_all = json.load(f)
                            # 保留其他类别的引用
                            for cat, cat_path in existing_all.get("categories", {}).items():
                                if cat != category and Path(cat_path).exists():
                                    all_papers_metadata["categories"][cat] = cat_path
                    except:
                        pass

                # 添加当前类别
                all_papers_metadata["categories"][category] = str(category_file)
                all_papers_metadata["total_papers"] = sum(
                    json.load(open(Path(p), "r", encoding="utf-8")).get("count", 0)
                    for p in all_papers_metadata["categories"].values()
                    if Path(p).exists()
                )

                with open(all_papers_file, "w", encoding="utf-8") as f:
                    json.dump(all_papers_metadata, f, indent=2, ensure_ascii=False)

                logger.info(f"Total papers in database: {all_papers_metadata['total_papers']}")
                state["papers_saved_path"] = str(all_papers_file)
                state["current_category"] = category
                state["pdfs_dir"] = str(pdfs_dir)
                logger.info(f"DEBUG: Set pdfs_dir in retrieval_node: {pdfs_dir}")
                state["papers_saved_path"] = str(all_papers_file)

                # workflow_mode 控制是否下载 PDF：
                # - full / search: 检索 + 下载 PDF（search 模式检索后即结束，不生成综述）
                #   两种模式都下载，区别在检索后是否继续走阅读/分析/写作
                workflow_mode = (state.get("workflow_mode") or "full").strip().lower()
                if workflow_mode in ("full", "search"):
                    # 检索到论文后自动下载 PDF（检索和下载不分开）
                    logger.info(f"Downloading PDFs to: {pdfs_dir}")
                    from src.agents.reader import ReaderAgent
                    from config.settings import get_config

                    config = get_config()
                    max_pdf_download = config.max_pdf_download

                    # 根据配置限制下载数量
                    papers_with_pdf = [p for p in state["search_results"] if p.get("pdf_url")]
                    papers_to_download = papers_with_pdf[:max_pdf_download]
                    logger.info(f"Limiting PDF download to {max_pdf_download} (configured), {len(papers_with_pdf)} available")

                    _emit_progress(
                        "retrieval_download",
                        details={
                            "papers_to_download": len(papers_to_download),
                            "papers_downloading": len(papers_to_download),
                            "papers_found": len(state["search_results"]),
                        },
                    )

                    agent = ReaderAgent(max_workers=4)
                    download_result = agent.run(papers_to_download, download_dir=str(pdfs_dir))
                    logger.info(f"PDF download completed: {download_result.completed}/{download_result.total_papers} papers downloaded")

                    # 下载+解析（agent.run 同时完成两步）进行中/完成后推送「论文阅读」状态
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
                    # 非下载模式（none 等）：不下载 PDF
                    logger.info(f"workflow_mode={workflow_mode}, skip PDF download")
                    state["literature_data"] = []
                    state["reading_errors"] = []
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
        pdfs_dir = state.get("pdfs_dir", os.path.join(base_dir, "data/papers/pdfs"))
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

    except Exception as e:
        logger.error(f"Outline generation failed: {e}")
        state["error_messages"].append(f"Outline generation failed: {e}")
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Outline error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting OUTLINE node")
    return state


@traceable(name="writing_node")
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

        result = agent.run(
            global_knowledge=state.get("global_knowledge", {}),
            topic=topic,
            literature_clusters=state.get("literature_clusters", []),
            reference_list=reference_list,
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

    except Exception as e:
        logger.error(f"Writing failed: {e}")
        state["error_messages"].append(f"Writing failed: {e}")
        state["current_phase"] = PipelinePhase.ERROR
        logger.exception("Writing error details:")

    state["updated_at"] = datetime.now().isoformat()
    logger.info("<<< Exiting WRITING node")
    return state


@traceable(name="revision_node")
def revision_node(state: GraphState) -> GraphState:
    """Reviewer agent node - review and finalize."""
    logger.info(">>> Entering REVISION node")
    state["current_phase"] = PipelinePhase.REVISION
    _emit_progress("revision")

    try:
        topic = state.get("research_topic", state.get("user_query", ""))
        logger.info(f"Starting revision for: {topic}")

        agent = ReviewerAgent()

        result = agent.run(
            paper_content=state.get("final_paper", ""),
            topic=topic,
            outline=state.get("outline"),
            global_knowledge=state.get("global_knowledge", {}),
            generate_front_matter=True,
        )

        gs_format = agent.to_graphstate_format(result)
        state["revision_feedback"] = gs_format["revision_feedback"]
        state["abstract"] = gs_format["abstract"]
        state["introduction"] = gs_format["introduction"]
        state["conclusion"] = gs_format["conclusion"]

        # 在最终报告末尾追加参考文献目录，确保正文中的 [n] 角标有对应出处
        reference_list = state.get("reference_list") or build_reference_list(state)
        bibliography = format_bibliography(reference_list)
        final_review = gs_format["final_review"] or ""
        if bibliography:
            if "## 参考文献" not in final_review:
                final_review = final_review.rstrip() + "\n\n" + bibliography
            state["reference_list"] = reference_list
        state["final_review"] = final_review

        # Update phase to final
        state["current_phase"] = PipelinePhase.FINAL

        paper_length = len(state.get("final_review", ""))
        logger.info(
            f"Revision completed: Final paper {paper_length} chars | "
            f"Abstract: {len(state.get('abstract', ''))} chars"
        )

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
        **kwargs,
    }

    # Create and run workflow
    app = create_workflow()

    # Run with config
    config = {"recursion_limit": 100}

    # 注册进度回调（线程本地），供各节点 _emit_progress 推送阶段
    _set_progress_callback(progress_callback)
    try:
        # 用 stream 而非 invoke：每个节点结束后都能拿到最新 state，便于
        # 在末尾推送 final 状态；实时阶段更新由节点内 _emit_progress 完成。
        final_state = initial_state
        for chunk in app.stream(initial_state, config):
            # chunk 形如 {node_name: state_after_node}
            if chunk:
                last = list(chunk.values())[-1]
                if isinstance(last, dict):
                    final_state = last
        if final_state is initial_state:
            # 兜底：stream 未产出时回退到 invoke
            final_state = app.invoke(initial_state, config)
    finally:
        _clear_progress_callback()

    return final_state


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
    }

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
