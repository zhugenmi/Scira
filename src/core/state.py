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

    # Human approval: Retrieval conditions
    retrieval_approval: Optional[str]  # ApprovalStatus value

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


# Type aliases for easier usage
SearchResult = Dict[str, Any]
AnalysisResult = Dict[str, Any]
RevisionFeedback = Dict[str, Any]
