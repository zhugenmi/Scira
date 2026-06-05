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

                # Create papers directory
                papers_dir = Path("data/papers")
                papers_dir.mkdir(parents=True, exist_ok=True)

                # Check for existing papers and deduplicate
                existing_papers = {}
                all_papers_file = papers_dir / "all_papers.json"
                if all_papers_file.exists():
                    try:
                        with open(all_papers_file, "r", encoding="utf-8") as f:
                            existing_data = json.load(f)
                            for p in existing_data.get("papers", []):
                                existing_papers[p.get("paper_id", "")] = p
                            logger.info(f"Found {len(existing_papers)} existing papers for deduplication")
                    except:
                        pass

                # Process new papers - deduplicate
                new_papers = []
                skipped_count = 0
                for p in state["search_results"]:
                    paper_id = p.get("paper_id", "")
                    if paper_id in existing_papers:
                        skipped_count += 1
                        logger.debug(f"Skipping duplicate paper: {paper_id}")
                        continue
                    new_papers.append(p)

                if skipped_count > 0:
                    logger.info(f"Skipped {skipped_count} duplicate papers")

                # Merge: keep existing + add new
                all_papers_metadata = {
                    "topic": user_query,
                    "search_keywords": result.search_strategy.keywords,
                    "retrieved_at": dt.now().isoformat(),
                    "total_papers": len(existing_papers) + len(new_papers),
                    "by_topic": {},
                    "papers": list(existing_papers.values())
                }

                # If there are new papers, classify and save them
                if new_papers:
                    # Classify new papers by their topics/keywords
                    topic_groups = {}
                    for p in new_papers:
                        paper_topics = p.get("topics", [])
                        if not paper_topics:
                            paper_topics = result.search_strategy.keywords[:3]

                        primary_topic = paper_topics[0] if paper_topics else "general"
                        primary_topic = primary_topic.replace(" ", "_").replace("/", "_")[:30]

                        if primary_topic not in topic_groups:
                            topic_groups[primary_topic] = []
                        topic_groups[primary_topic].append(p)

                    # Save new papers organized by topic
                    for topic, papers_list in topic_groups.items():
                        topic_dir = papers_dir / topic
                        topic_dir.mkdir(parents=True, exist_ok=True)

                        topic_papers = []
                        for p in papers_list:
                            paper_info = {
                                "paper_id": p.get("paper_id", ""),
                                "title": p.get("title", ""),
                                "authors": p.get("authors", []),
                                "published_date": p.get("published_date", ""),
                                "abstract": p.get("abstract", ""),
                                "pdf_url": p.get("pdf_url", ""),
                                "topics": [primary_topic],  # 使用计算出的主题分类
                                "citations": p.get("citations", 0),
                            }
                            topic_papers.append(paper_info)
                            all_papers_metadata["papers"].append(paper_info)

                        # Save topic-specific file (overwrite with all papers in topic)
                        topic_file = topic_dir / f"{topic}.json"
                        topic_metadata = {
                            "category": topic,
                            "topic": user_query,
                            "updated_at": dt.now().isoformat(),
                            "count": len(topic_papers),
                            "papers": topic_papers
                        }
                        with open(topic_file, "w", encoding="utf-8") as f:
                            json.dump(topic_metadata, f, indent=2, ensure_ascii=False)

                        all_papers_metadata["by_topic"][topic] = str(topic_file)
                        logger.info(f"Saved {len(topic_papers)} papers to: {topic_file}")

                # Save all papers combined (overwrite)
                with open(all_papers_file, "w", encoding="utf-8") as f:
                    json.dump(all_papers_metadata, f, indent=2, ensure_ascii=False)

                logger.info(f"Total papers in database: {len(all_papers_metadata['papers'])}")
                state["papers_saved_path"] = str(all_papers_file)

                logger.info(f"All papers metadata saved to: {all_papers_file}")
                state["papers_saved_path"] = str(all_papers_file)
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
    """Reader agent node - download and parse papers."""
    logger.info(">>> Entering READING node")
    state["current_phase"] = PipelinePhase.READING

    try:
        papers_to_read = state.get("search_results", [])
        logger.info(f"Starting to read {len(papers_to_read)} papers")

        # papers_to_read is already a list of dicts from MCP API search
        # No need to convert to ArxivPaper - ReaderAgent handles dicts directly

        agent = ReaderAgent(max_workers=4)
        logger.debug(f"ReaderAgent initialized with {agent.max_workers} workers")

        result = agent.run(papers_to_read)

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
    if state.get("auto_approve", False):
        return "approved"

    approval = state.get("outline_approval")
    if approval == ApprovalStatus.APPROVED:
        return "approved"
    elif approval == ApprovalStatus.REJECTED:
        return "retry"

    return "needs_approval"


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
