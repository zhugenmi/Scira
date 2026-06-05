"""
Scira Analyzer Agent

Implements literature analysis and synthesis:
- Cluster papers by theme
- Compare methodologies
- Generate global knowledge synthesis
"""

import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_config, get_llm_client, SciraConfig
from src.agents.prompts import (
    ANALYZER_CLUSTER_PROMPT,
    ANALYZER_COMPARE_PROMPT,
    ANALYZER_SYNTHESIZE_PROMPT,
    ANALYZER_SYSTEM,
)


class ClusterMethod(str, Enum):
    """Clustering method."""
    TOPIC = "topic"
    METHOD = "method"
    APPROACH = "approach"
    YEAR = "year"


@dataclass
class PaperCluster:
    """Cluster of related papers."""
    cluster_id: str
    cluster_name: str
    paper_ids: List[str]
    common_theme: str
    common_approach: str
    key_differences: List[str]
    representative_papers: List[Dict[str, Any]]


@dataclass
class GlobalKnowledge:
    """Global knowledge synthesis."""
    research_background: str
    mainstream_methods: List[Dict[str, str]]  # {name, description, pros, cons}
    performance_comparison: str
    research_gaps: List[Dict[str, str]]  # {gap, importance, opportunity}
    future_directions: List[str]
    key_findings: List[str]


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    clusters: List[PaperCluster]
    global_knowledge: GlobalKnowledge
    analysis_metadata: Dict[str, Any]


class AnalyzerAgent:
    """
    Analyzer Agent for literature analysis.

    Responsibilities:
    1. Cluster papers by theme/methodology
    2. Compare different approaches
    3. Identify research trends and gaps
    4. Generate global knowledge synthesis
    """

    def __init__(self, config: Optional[SciraConfig] = None):
        """Initialize Analyzer Agent."""
        self.config = config or get_config()
        self.llm = get_llm_client(self.config)

    def prepare_paper_summary(self, literature_data: List[Dict]) -> List[Dict]:
        """
        Prepare paper summaries for analysis.

        Args:
            literature_data: List of parsed paper data

        Returns:
            Summarized papers for LLM analysis
        """
        summaries = []

        for paper in literature_data:
            content = paper.get("extracted_content", {})

            summary = {
                "paper_id": paper.get("paper_id"),
                "title": paper.get("title"),
                "authors": paper.get("authors", [])[:3],  # Limit authors
                "abstract": paper.get("abstract", "")[:500],  # Limit abstract length

                # Extracted content
                "sections": content.get("section_names", []),
                "word_count": content.get("word_count", 0),
                "reference_count": content.get("reference_count", 0),
            }
            summaries.append(summary)

        return summaries

    def cluster_papers(
        self,
        papers: List[Dict],
        method: ClusterMethod = ClusterMethod.TOPIC,
    ) -> List[PaperCluster]:
        """
        Cluster papers by theme or methodology.

        Args:
            papers: Paper summaries
            method: Clustering method

        Returns:
            List of paper clusters
        """
        # Use LLM to do intelligent clustering
        papers_json = json.dumps(papers, indent=2, ensure_ascii=False)

        # Use the template prompt
        prompt = ANALYZER_CLUSTER_PROMPT.format(papers=papers_json)

        messages = [
            SystemMessage(content=ANALYZER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        response = self.llm.invoke(messages)
        return self._parse_clusters(response.content, papers)

    def _parse_clusters(self, response: str, papers: List[Dict]) -> List[PaperCluster]:
        """Parse clustering response."""
        import re

        # Extract JSON
        match = re.search(r'\{[\s\S]*\}', response)
        if not match:
            return []

        try:
            data = json.loads(match.group())
            clusters_data = data.get("clusters", [])

            # Create PaperCluster objects
            clusters = []
            for i, c in enumerate(clusters_data):
                cluster = PaperCluster(
                    cluster_id=c.get("cluster_id", f"cluster_{i+1}"),
                    cluster_name=c.get("cluster_name", "Unknown"),
                    paper_ids=c.get("paper_ids", []),
                    common_theme=c.get("common_theme", ""),
                    common_approach=c.get("common_approach", ""),
                    key_differences=c.get("key_differences", []),
                    representative_papers=[],  # Will be filled later
                )
                clusters.append(cluster)

            return clusters

        except json.JSONDecodeError:
            return []

    def compare_methods(
        self,
        clusters: List[PaperCluster],
        papers: List[Dict],
    ) -> List[Dict[str, str]]:
        """
        Compare methods across clusters.

        Args:
            clusters: Paper clusters
            papers: Paper data

        Returns:
            List of method comparisons
        """
        # Build paper lookup
        paper_lookup = {p.get("paper_id"): p for p in papers}

        # Create summary for comparison
        cluster_summaries = []
        for cluster in clusters:
            papers_in_cluster = [
                paper_lookup.get(pid) for pid in cluster.paper_ids
                if pid in paper_lookup
            ]

            cluster_summaries.append({
                "cluster": cluster.cluster_name,
                "approach": cluster.common_approach,
                "paper_count": len(papers_in_cluster),
                "titles": [p.get("title", "") for p in papers_in_cluster[:3]],
            })

        comparison_json = json.dumps(cluster_summaries, indent=2, ensure_ascii=False)

        # Use the template prompt
        prompt = ANALYZER_COMPARE_PROMPT.format(papers=comparison_json)

        messages = [
            SystemMessage(content=ANALYZER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        response = self.llm.invoke(messages)
        return self._parse_method_comparison(response.content)

    def _parse_method_comparison(self, response: str) -> List[Dict[str, str]]:
        """Parse method comparison response."""
        import re

        match = re.search(r'\{[\s\S]*\}', response)
        if not match:
            return []

        try:
            data = json.loads(match.group())
            return data.get("method_comparisons", [])
        except json.JSONDecodeError:
            return []

    def generate_global_knowledge(
        self,
        papers: List[Dict],
        clusters: List[PaperCluster],
    ) -> GlobalKnowledge:
        """
        Generate global knowledge synthesis.

        Args:
            papers: Paper data
            clusters: Paper clusters

        Returns:
            GlobalKnowledge object
        """
        # Prepare analysis input
        papers_json = json.dumps(papers[:10], indent=2, ensure_ascii=False)  # Limit to 10 for context
        clusters_json = json.dumps([{"name": c.cluster_name, "theme": c.common_theme} for c in clusters], indent=2)

        # Use the template prompt
        prompt = ANALYZER_SYNTHESIZE_PROMPT.format(
            clusters=f"Papers:\n{papers_json}\n\nClusters:\n{clusters_json}"
        )

        messages = [
            SystemMessage(content=ANALYZER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        response = self.llm.invoke(messages)
        return self._parse_global_knowledge(response.content)

    def _parse_global_knowledge(self, response: str) -> GlobalKnowledge:
        """Parse global knowledge response."""
        import re

        match = re.search(r'\{[\s\S]*\}', response)
        if not match:
            return GlobalKnowledge(
                research_background="",
                mainstream_methods=[],
                performance_comparison="",
                research_gaps=[],
                future_directions=[],
                key_findings=[],
            )

        try:
            data = json.loads(match.group())
            return GlobalKnowledge(
                research_background=data.get("research_background", ""),
                mainstream_methods=data.get("mainstream_methods", []),
                performance_comparison=data.get("performance_comparison", ""),
                research_gaps=data.get("research_gaps", []),
                future_directions=data.get("future_directions", []),
                key_findings=data.get("key_findings", []),
            )
        except json.JSONDecodeError:
            return GlobalKnowledge(
                research_background="",
                mainstream_methods=[],
                performance_comparison="",
                research_gaps=[],
                future_directions=[],
                key_findings=[],
            )

    def run(
        self,
        literature_data: List[Dict],
        cluster_method: ClusterMethod = ClusterMethod.TOPIC,
    ) -> AnalysisResult:
        """
        Run complete analysis workflow.

        Args:
            literature_data: Literature data from reading stage
            cluster_method: Clustering method

        Returns:
            AnalysisResult
        """
        # Prepare paper summaries
        papers = self.prepare_paper_summary(literature_data)

        # Cluster papers
        clusters = self.cluster_papers(papers, cluster_method)

        # Compare methods
        method_comparisons = self.compare_methods(clusters, papers)

        # Add method comparisons to clusters (as a separate structure)
        # This is stored in analysis_metadata

        # Generate global knowledge
        global_knowledge = self.generate_global_knowledge(papers, clusters)

        # Build metadata
        metadata = {
            "cluster_method": cluster_method.value,
            "total_papers_analyzed": len(papers),
            "total_clusters": len(clusters),
            "method_comparisons": method_comparisons,
            "analysis_timestamp": datetime.now().isoformat(),
        }

        return AnalysisResult(
            clusters=clusters,
            global_knowledge=global_knowledge,
            analysis_metadata=metadata,
        )

    def to_graphstate_format(self, result: AnalysisResult) -> Dict[str, Any]:
        """
        Convert to GraphState format.

        Args:
            result: AnalysisResult

        Returns:
            Dict with literature_clusters and global_knowledge
        """
        # Convert clusters
        clusters = []
        for cluster in result.clusters:
            clusters.append({
                "cluster_id": cluster.cluster_id,
                "cluster_name": cluster.cluster_name,
                "paper_ids": cluster.paper_ids,
                "common_theme": cluster.common_theme,
                "common_approach": cluster.common_approach,
                "key_differences": cluster.key_differences,
            })

        # Convert global knowledge
        knowledge = {
            "research_background": result.global_knowledge.research_background,
            "mainstream_methods": result.global_knowledge.mainstream_methods,
            "performance_comparison": result.global_knowledge.performance_comparison,
            "research_gaps": result.global_knowledge.research_gaps,
            "future_directions": result.global_knowledge.future_directions,
            "key_findings": result.global_knowledge.key_findings,
        }

        return {
            "literature_clusters": clusters,
            "global_knowledge": knowledge,
            "analysis_metadata": result.analysis_metadata,
        }


# Convenience function
def analyze_literature(
    literature_data: List[Dict],
    cluster_method: str = "topic",
) -> Dict[str, Any]:
    """
    Quick literature analysis function.

    Args:
        literature_data: Literature data from reading stage
        cluster_method: Clustering method (topic, method, approach, year)

    Returns:
        Analysis result in GraphState format
    """
    from datetime import datetime

    agent = AnalyzerAgent()
    method = ClusterMethod(cluster_method)
    result = agent.run(literature_data, method)
    return agent.to_graphstate_format(result)


# Import datetime for the metadata
from datetime import datetime
