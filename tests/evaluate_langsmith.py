"""
Scira LangSmith Evaluation Framework

Automated evaluation system for research quality using LangSmith.
Includes:
- Dataset creation with typical research queries
- Custom evaluators (Factuality, Retrieval Quality)
- Evaluation runner
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# LangSmith imports
from langsmith import Client, traceable
from langsmith.evaluation import EvaluationResult, run_evaluator
from langsmith.schemas import Example, Run

# Import config and workflow
from config.settings import get_config, get_llm_client
from src.core.workflow import run_workflow
from src.utils.logger import logger, setup_logging


# Initialize logging
setup_logging(level="INFO", verbose=False)


# ==================== Dataset ====================

# Sample research queries for evaluation
EVAL_DATASET = [
    {
        "query": "What are the latest advances in diffusion models for drug discovery?",
        "expected_topics": ["diffusion models", "drug discovery", "molecular generation"],
        "expected_papers": 10,
    },
    {
        "query": "How do large language models handle context window limitations?",
        "expected_topics": ["LLM", "context window", "attention mechanisms"],
        "expected_papers": 8,
    },
    {
        "query": "What are the state-of-the-art methods for multi-agent reinforcement learning?",
        "expected_topics": ["multi-agent", "reinforcement learning", "MARL"],
        "expected_papers": 10,
    },
    {
        "query": "Compare GPT-4 and Claude-3 on mathematical reasoning tasks",
        "expected_topics": ["GPT-4", "Claude-3", "mathematical reasoning", "benchmark"],
        "expected_papers": 6,
    },
    {
        "query": "What are the latest advances in neural architecture search?",
        "expected_topics": ["neural architecture search", "NAS", "AutoML"],
        "expected_papers": 8,
    },
]


def create_dataset(client: Client, dataset_name: str = "scira-evaluation") -> str:
    """
    Create evaluation dataset in LangSmith.

    Args:
        client: LangSmith client
        dataset_name: Name for the dataset

    Returns:
        Dataset ID
    """
    logger.info(f"Creating dataset: {dataset_name}")

    # Check if dataset exists
    existing = client.list_datasets(dataset_name=dataset_name)
    dataset_list = list(existing)

    if dataset_list:
        dataset = dataset_list[0]
        logger.info(f"Using existing dataset: {dataset.id}")
    else:
        # Create new dataset
        dataset = client.create_dataset(
            dataset_name=dataset_name,
            description="Scira research assistant evaluation dataset",
        )
        logger.info(f"Created new dataset: {dataset.id}")

    # Add examples
    for i, item in enumerate(EVAL_DATASET):
        client.create_example(
            inputs={
                "query": item["query"],
            },
            outputs=None,
            dataset_id=dataset.id,
        )

    logger.info(f"Added {len(EVAL_DATASET)} examples to dataset")
    return dataset.id


# ==================== Custom Evaluators ====================

class FactualityEvaluator:
    """
    Evaluator for factuality - detects hallucination in generated content.

    Uses LLM-as-a-judge approach to evaluate if the generated content
    is grounded in the retrieved literature.
    """

    def __init__(self):
        self.config = get_config()
        self.llm = get_llm_client(self.config)

    @traceable(name="factuality_evaluator")
    def evaluate(
        self,
        prediction: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate factuality of generated content.

        Args:
            prediction: Generated paper content
            reference: Expected reference (optional)
            context: Additional context including retrieved papers

        Returns:
            Evaluation result with score and reasoning
        """
        # Build evaluation prompt
        retrieved_papers = context.get("retrieved_papers", []) if context else []

        papers_summary = "\n".join([
            f"- {p.get('title', 'N/A')}: {p.get('abstract', 'N/A')[:200]}..."
            for p in retrieved_papers[:5]
        ]) if retrieved_papers else "No papers retrieved"

        prompt = f"""You are an expert academic reviewer. Evaluate whether the generated paper content is factually accurate and grounded in the retrieved literature.

Retrieved Papers:
{papers_summary}

Generated Content (first 1000 chars):
{prediction[:1000]}

Evaluate the following aspects:
1. Are claims in the generated content supported by the retrieved papers?
2. Are there any potential hallucinations or unverified claims?
3. Is the citation of papers accurate?

Provide a JSON response:
{{
    "score": 0-10 (10 = fully grounded, 0 = significant hallucinations),
    "reasoning": "Brief explanation of the score",
    "issues": ["issue1", "issue2"] (list of specific issues found, empty if none)
}}
"""

        try:
            response = self.llm.invoke(prompt)
            result_text = response.content

            # Parse JSON response
            import re
            match = re.search(r'\{[\s\S]*\}', result_text)
            if match:
                result = json.loads(match.group())
                return {
                    "score": result.get("score", 5),
                    "reasoning": result.get("reasoning", ""),
                    "issues": result.get("issues", []),
                }

            return {
                "score": 5,
                "reasoning": "Could not parse evaluation result",
                "issues": [],
            }

        except Exception as e:
            logger.error(f"Factuality evaluation error: {e}")
            return {
                "score": 5,
                "reasoning": f"Evaluation error: {str(e)}",
                "issues": [],
            }


class RetrievalQualityEvaluator:
    """
    Evaluator for retrieval quality - measures recall and relevance.

    Evaluates whether the retrieved papers are relevant to the query
    and cover the expected topics.
    """

    def __init__(self):
        self.config = get_config()

    @traceable(name="retrieval_quality_evaluator")
    def evaluate(
        self,
        query: str,
        retrieved_papers: List[Dict[str, Any]],
        expected_topics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate retrieval quality.

        Args:
            query: Original research query
            retrieved_papers: List of retrieved paper dictionaries
            expected_topics: List of expected topic keywords

        Returns:
            Evaluation result with metrics
        """
        if not retrieved_papers:
            return {
                "recall": 0,
                "relevance_score": 0,
                "coverage": 0,
                "reasoning": "No papers retrieved",
            }

        # Calculate metrics
        num_papers = len(retrieved_papers)

        # Check relevance (simple keyword matching)
        query_terms = query.lower().split()
        relevant_count = 0

        for paper in retrieved_papers:
            title = paper.get("title", "").lower()
            abstract = paper.get("abstract", "").lower()
            paper_text = title + " " + abstract

            # Count how many query terms appear in the paper
            matches = sum(1 for term in query_terms if term in paper_text)
            if matches > 0:
                relevant_count += 1

        relevance_score = relevant_count / num_papers if num_papers > 0 else 0

        # Check topic coverage
        coverage = 0
        if expected_topics:
            topics_covered = 0
            for topic in expected_topics:
                topic_lower = topic.lower()
                for paper in retrieved_papers:
                    paper_text = (
                        paper.get("title", "").lower() + " " +
                        paper.get("abstract", "").lower()
                    )
                    if topic_lower in paper_text:
                        topics_covered += 1
                        break
            coverage = topics_covered / len(expected_topics)

        # Recall (assuming expected papers is a target)
        expected_count = 10  # Default expected
        recall = min(num_papers / expected_count, 1.0)

        reasoning = (
            f"Retrieved {num_papers} papers, "
            f"{relevant_count} relevant to query. "
            f"Relevance score: {relevance_score:.2f}. "
            f"Topic coverage: {coverage:.2f}"
        )

        return {
            "recall": recall,
            "relevance_score": relevance_score,
            "coverage": coverage,
            "num_papers": num_papers,
            "reasoning": reasoning,
        }


# ==================== Evaluation Runner ====================

@traceable(name="run_scira_evaluation")
def run_evaluation(
    dataset_name: str = "scira-evaluation",
    project_name: str = "scira-eval-run",
    evaluators: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run complete evaluation pipeline.

    Args:
        dataset_name: Name of the dataset
        project_name: Name for the evaluation run
        evaluators: List of evaluator names to use

    Returns:
        Evaluation summary
    """
    if evaluators is None:
        evaluators = ["factuality", "retrieval"]

    logger.info(f"Starting evaluation: {project_name}")
    logger.info(f"Using evaluators: {evaluators}")

    # Initialize LangSmith client
    client = Client()

    # Create or get dataset
    dataset_id = create_dataset(client, dataset_name)
    logger.info(f"Dataset ID: {dataset_id}")

    # Get dataset
    dataset = client.read_dataset(dataset_id=dataset_id)
    examples = list(client.list_examples(dataset_id=dataset_id))

    logger.info(f"Running evaluation on {len(examples)} examples")

    # Initialize evaluators
    factuality_eval = FactualityEvaluator() if "factuality" in evaluators else None
    retrieval_eval = RetrievalQualityEvaluator() if "retrieval" in evaluators else None

    # Results storage
    results = []
    factuality_scores = []
    retrieval_scores = []

    # Run evaluation for each example
    for i, example in enumerate(examples):
        query = example.inputs.get("query", "")
        logger.info(f"\n[{i+1}/{len(examples)}] Evaluating: {query}")

        try:
            # Run the workflow
            result = run_workflow(
                user_query=query,
                auto_approve=True,
            )

            # Get retrieved papers
            retrieved_papers = result.get("search_results", [])
            literature_data = result.get("literature_data", [])

            # Evaluate factuality
            factuality_result = None
            if factuality_eval:
                prediction = result.get("final_review", result.get("final_paper", ""))
                factuality_result = factuality_eval.evaluate(
                    prediction=prediction,
                    context={"retrieved_papers": retrieved_papers},
                )
                factuality_scores.append(factuality_result.get("score", 0))
                logger.info(f"Factuality score: {factuality_result.get('score', 0)}/10")

            # Evaluate retrieval quality
            retrieval_result = None
            if retrieval_eval:
                # Get expected topics from our test data
                expected_topics = None
                for item in EVAL_DATASET:
                    if item["query"] == query:
                        expected_topics = item.get("expected_topics")
                        break

                retrieval_result = retrieval_eval.evaluate(
                    query=query,
                    retrieved_papers=retrieved_papers,
                    expected_topics=expected_topics,
                )
                retrieval_scores.append(retrieval_result.get("relevance_score", 0))
                logger.info(f"Retrieval relevance: {retrieval_result.get('relevance_score', 0):.2f}")

            # Store result
            results.append({
                "query": query,
                "factuality": factuality_result,
                "retrieval": retrieval_result,
                "status": "success",
            })

        except Exception as e:
            logger.error(f"Error evaluating {query}: {e}")
            results.append({
                "query": query,
                "error": str(e),
                "status": "failed",
            })

    # Calculate summary
    summary = {
        "dataset": dataset_name,
        "project": project_name,
        "total_examples": len(examples),
        "successful": sum(1 for r in results if r.get("status") == "success"),
        "failed": sum(1 for r in results if r.get("status") == "failed"),
    }

    if factuality_scores:
        summary["avg_factuality_score"] = sum(factuality_scores) / len(factuality_scores)

    if retrieval_scores:
        summary["avg_retrieval_relevance"] = sum(retrieval_scores) / len(retrieval_scores)

    # Print summary
    logger.info("\n" + "=" * 50)
    logger.info("EVALUATION SUMMARY")
    logger.info("=" * 50)
    logger.info(f"Dataset: {summary['dataset']}")
    logger.info(f"Total examples: {summary['total_examples']}")
    logger.info(f"Successful: {summary['successful']}")
    logger.info(f"Failed: {summary['failed']}")

    if "avg_factuality_score" in summary:
        logger.info(f"Avg Factuality Score: {summary['avg_factuality_score']:.2f}/10")

    if "avg_retrieval_relevance" in summary:
        logger.info(f"Avg Retrieval Relevance: {summary['avg_retrieval_relevance']:.2f}")

    logger.info("=" * 50)

    return summary


def run_quick_eval(query: str) -> Dict[str, Any]:
    """
    Run a quick evaluation on a single query.

    Args:
        query: Research query

    Returns:
        Evaluation results
    """
    logger.info(f"Quick evaluation for: {query}")

    # Run workflow
    result = run_workflow(user_query=query, auto_approve=True)

    retrieved_papers = result.get("search_results", [])
    prediction = result.get("final_review", result.get("final_paper", ""))

    # Evaluate
    factuality_eval = FactualityEvaluator()
    factuality_result = factuality_eval.evaluate(
        prediction=prediction,
        context={"retrieved_papers": retrieved_papers},
    )

    retrieval_eval = RetrievalQualityEvaluator()
    retrieval_result = retrieval_eval.evaluate(
        query=query,
        retrieved_papers=retrieved_papers,
    )

    return {
        "query": query,
        "factuality": factuality_result,
        "retrieval": retrieval_result,
    }


# ==================== Main ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scira Evaluation Framework")
    parser.add_argument("--dataset", type=str, default="scira-evaluation", help="Dataset name")
    parser.add_argument("--project", type=str, default="scira-eval-run", help="Project name")
    parser.add_argument("--evaluators", type=str, default="factuality,retrieval", help="Comma-separated evaluators")
    parser.add_argument("--query", type=str, help="Single query for quick eval")

    args = parser.parse_args()

    if args.query:
        # Quick single query evaluation
        result = run_quick_eval(args.query)
        print(json.dumps(result, indent=2))
    else:
        # Full evaluation
        evaluators = args.evaluators.split(",") if args.evaluators else ["factuality", "retrieval"]
        summary = run_evaluation(
            dataset_name=args.dataset,
            project_name=args.project,
            evaluators=evaluators,
        )
        print(json.dumps(summary, indent=2))
