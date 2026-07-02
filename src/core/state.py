"""
Scira GraphState Definition

Global state structure for LangGraph workflow.
Defines all data flowing through the research assistant pipeline.
"""

from typing import TypedDict, List, Dict, Optional, Any
from enum import Enum


class PipelinePhase(str, Enum):
    """Pipeline execution phases."""
    INIT = "init"
    TREND_ANALYSIS = "trend_analysis"
    RETRIEVAL = "retrieval"
    READING = "reading"
    ANALYSIS = "analysis"
    OUTLINE = "outline"
    WRITING = "writing"
    REVISION = "revision"
    FINAL = "final"
    ERROR = "error"


class ApprovalStatus(str, Enum):
    """Human approval status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class LiteratureEntry(TypedDict, total=False):
    """Single literature paper entry."""
    paper_id: str
    title: str
    authors: List[str]
    abstract: str
    published_date: Optional[str]
    categories: List[str]
    pdf_url: str
    # Extracted content (after reading)
    extracted_content: Optional[Dict[str, Any]]
    # Reading status
    reading_status: str


class ChapterDraft(TypedDict, total=False):
    """Chapter draft structure."""
    title: str
    content: str
    word_count: int
    references: List[str]
    status: str  # draft, revised, final


class GraphState(TypedDict):
    """
    Global state for Scira LangGraph workflow.

    This state is passed through all nodes in the pipeline.
    Fields are added/modified as data flows through each stage.
    """

    # ===================
    # Input Stage
    # ===================
    user_query: str  # Original user research query
    research_topic: str  # Normalized/expanded research topic
    auto_approve: bool  # Whether to skip human approvals
    # 工作流执行模式：full(完整) / search_only(仅检索) / search_download(检索+下载)
    workflow_mode: str

    # ===================
    # Trend Analysis Stage
    # ===================
    trends_data: Optional[Dict[str, Any]]  # Industry latest trends and dynamics

    # ===================
    # Retrieval Stage
    # ===================
    search_keywords: Optional[List[str]]  # Generated search keywords
    search_filters: Optional[Dict[str, Any]]  # Boolean logic, date range, etc.
    search_results: Optional[List[Dict[str, Any]]]  # Raw arXiv search results
    selected_papers: Optional[List[str]]  # Paper IDs selected for reading

    # 领域分类（7-class enum 之一），由 retrieval_node 从 SearchStrategy 写入。
    # 用于检索源路由；下游节点暂不消费，但需声明否则 LangGraph 会丢弃。
    domain: Optional[str]

    # 用户检索约束（由 IntentAgent 抽取，retrieval_node 消费）。
    # year_range: (start_year, end_year) 闭区间；min_count: 用户要求"不少于 N 篇"。
    # 未指定时为 None。声明在 GraphState 否则 LangGraph 会在节点返回时丢弃。
    year_range: Optional[List[int]]  # [start_year, end_year]
    min_count: Optional[int]
    # 检索结果不足时给前端的提示（如"实际找到 8 篇（用户要求≥20）"）
    retrieval_shortfall_hint: Optional[str]

    # 来源知识库（KB-based 写作入口用）：当从已有知识库生成综述时，记录所选类别名。
    # retrieval_node 不写；run_workflow_from_knowledge_bases 写入。
    source_categories: Optional[List[str]]

    # Human approval: Retrieval conditions
    retrieval_approval: Optional[str]  # ApprovalStatus value

    # Download approval: candidate papers awaiting user confirmation before PDF download
    pending_download_papers: Optional[List[Dict[str, Any]]]  # [{paper_id,title,authors,year,abstract,pdf_url}]
    download_approval: Optional[str]  # ApprovalStatus value for download step

    pending_categories: Optional[List[str]]      # 已有知识库列表（retrieval 填充，供前端下拉）
    pending_matched_category: Optional[str]      # retrieval 自动匹配的类别名（供前端默认选中）

    # 检索落盘元数据。LangGraph 1.x 仅保留 GraphState 中声明的键，
    # 未声明的 key 会在节点返回 state 时被丢弃，导致后续节点拿不到。
    # 这些字段由 retrieval_node 写入，供 run_download_and_rest / reading_node 等读取。
    retrieval_successful: Optional[bool]  # 检索是否成功
    current_category: Optional[str]  # 本次检索命中的领域目录名（如 knowledge_graph）
    pdfs_dir: Optional[str]  # PDF 落盘目录绝对/相对路径
    papers_saved_path: Optional[str]  # papers 索引文件路径

    # ===================
    # Reading Stage
    # ===================
    literature_data: Optional[List[LiteratureEntry]]  # Parsed paper data
    reading_errors: Optional[List[str]]  # Errors during PDF parsing

    # ===================
    # Analysis Stage
    # ===================
    literature_clusters: Optional[List[Dict[str, Any]]]  # Thematic clusters of papers
    global_knowledge: Optional[Dict[str, Any]]  # Global knowledge synthesis
        # Contains: background, methods, challenges, future_directions

    # ===================
    # Outline Stage
    # ===================
    outline: Optional[Dict[str, Any]]  # Paper outline structure
        # Contains: title, sections[], abstract, introduction, conclusion

    # Human approval: Outline
    outline_approval: Optional[str]  # ApprovalStatus value

    # ===================
    # Writing Stage
    # ===================
    chapter_drafts: Optional[Dict[str, ChapterDraft]]  # {chapter_name: draft}
    # Map-reduce sends papers for parallel writing, results accumulate here
    writing_progress: Optional[Dict[str, Any]]  # Writing task tracking

    # ===================
    # Revision Stage
    # ===================
    final_paper: Optional[str]  # Complete paper without abstract/intro/conclusion
    revision_feedback: Optional[Dict[str, Any]]  # Reviewer suggestions
        # Contains: logic_issues, language_issues, formatting_issues

    # ===================
    # Final Generation (首尾章节后置生成)
    # ===================
    abstract: Optional[str]  # Auto-generated abstract
    introduction: Optional[str]  # Auto-generated introduction
    conclusion: Optional[str]  # Auto-generated conclusion

    final_review: Optional[str]  # Final revised paper (complete)

    # 编号参考文献清单（写作/修订节点跨节点共享）
    reference_list: Optional[List[Dict[str, Any]]]
    # 生成报告落盘路径
    report_path: Optional[str]
    # Token 用量统计（跨节点累加）
    token_usage: Optional[Dict[str, Any]]

    # ===================
    # Control Flow
    # ===================
    current_phase: PipelinePhase  # Current execution phase

    # All human approval checkpoints
    human_approvals: Dict[str, str]  # {checkpoint_name: ApprovalStatus}

    # Error handling
    error_messages: List[str]
    retry_count: int

    # Metadata
    created_at: Optional[str]
    updated_at: Optional[str]
    # 工作流运行 ID，用于跨节点日志关联（与 contextvars run_id 同步）
    run_id: Optional[str]


# Type aliases for easier usage
SearchResult = Dict[str, Any]
AnalysisResult = Dict[str, Any]
RevisionFeedback = Dict[str, Any]
