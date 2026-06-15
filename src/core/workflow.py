"""
Scira LangGraph Workflow

Defines the complete research assistant pipeline as a LangGraph DAG.
Includes logging, observability, and token tracking.
"""

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
    user_query = state.get("user_query", "N/A")

    try:
        logger.info(f"Starting paper search for: {user_query}")

        agent = RetrievalAgent()
        result = agent.run(
            user_query=user_query,
            auto_approve=state.get("auto_approve", False),
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

                # 尝试使用用户查询生成分类名
                if user_query:
                    # 将用户查询转换为分类名
                    # 中文：取拼音首字母或直接音译
                    # 英文：使用下划线分隔
                    import re
                    # 检查是否包含中文字符
                    if re.search(r'[一-鿿]', user_query):
                        # 中文查询：翻译为英文或使用拼音
                        # 常见领域映射
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
                        category = None
                        for key, value in query_to_category.items():
                            if key in user_query:
                                category = value
                                break
                        if category is None:
                            # 回退：使用搜索关键词
                            category = search_keywords[0].replace(" ", "_").replace("/", "_")[:30] if search_keywords else "general"
                    else:
                        # 英文查询：直接使用
                        category = user_query.replace(" ", "_").replace("/", "_")[:30].lower()
                else:
                    # 没有用户查询，回退到搜索关键词
                    category = search_keywords[0].replace(" ", "_").replace("/", "_")[:30] if search_keywords else "general"

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
                    paper_info = {
                        "paper_id": paper_id,
                        "title": title,
                        "authors": p.get("authors", []),
                        "published_date": p.get("published_date", ""),
                        "abstract": abstract,
                        "pdf_url": p.get("pdf_url", ""),
                        "topics": keywords,  # 使用提取的关键字填充topics
                        "keywords": keywords,
                        "citations": p.get("citations", 0),
                        "pdf_path": str(pdfs_dir / f"{paper_id}.pdf") if p.get("pdf_url") else "",
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

                # 在retrieval_node中同步下载PDF，避免状态传递丢失问题
                logger.info(f"Downloading PDFs to: {pdfs_dir}")
                from src.agents.reader import ReaderAgent
                from config.settings import get_config

                config = get_config()
                max_pdf_download = config.max_pdf_download

                # 根据配置限制下载数量
                papers_with_pdf = [p for p in state["search_results"] if p.get("pdf_url")]
                papers_to_download = papers_with_pdf[:max_pdf_download]
                logger.info(f"Limiting PDF download to {max_pdf_download} (configured), {len(papers_with_pdf)} available")

                agent = ReaderAgent(max_workers=4)
                download_result = agent.run(papers_to_download, download_dir=str(pdfs_dir))
                logger.info(f"PDF download completed: {download_result.completed}/{download_result.total_papers} papers downloaded")
                state["literature_data"] = download_result.literature_data
                state["reading_errors"] = download_result.reading_summary.get("failed_papers", [])
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

    try:
        topic = state.get("research_topic", state.get("user_query", ""))
        logger.info(f"Starting paper writing for: {topic}")

        agent = WriterAgent()

        result = agent.run(
            global_knowledge=state.get("global_knowledge", {}),
            topic=topic,
            literature_clusters=state.get("literature_clusters", []),
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
        state["final_review"] = gs_format["final_review"]

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
    """
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
    **kwargs,
) -> GraphState:
    """
    Run the complete workflow.

    Args:
        user_query: User's research query
        auto_approve: Skip human approvals
        **kwargs: Additional state fields

    Returns:
        Final state with results
    """
    logger.info(f"Starting workflow | Query: {user_query} | Auto-approve: {auto_approve}")

    # Initialize state
    initial_state: GraphState = {
        "user_query": user_query,
        "research_topic": user_query,  # Will be refined by retrieval
        "auto_approve": auto_approve,
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
    final_state = app.invoke(initial_state, config)

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
