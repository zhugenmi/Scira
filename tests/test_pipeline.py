"""
Scira Retrieval & Reading Pipeline Tests

Tests for:
1. RetrievalAgent - Query analysis, search strategy, paper selection
2. ReaderAgent - PDF download, parallel parsing
3. AnalyzerAgent - Clustering, knowledge synthesis
"""

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.retrieval import (
    RetrievalAgent,
    SearchStrategy,
    SearchStrategyGenerator,
    RetrievalResult,
)
from src.agents.reader import (
    ReaderAgent,
    ReadingTask,
    ReadingResult,
    create_reading_tasks,
    reading_node,
    aggregate_reading_results,
)
from src.agents.analyzer import (
    AnalyzerAgent,
    ClusterMethod,
    PaperCluster,
    GlobalKnowledge,
    AnalysisResult,
    analyze_literature,
)


# Test config
TEST_DATA_DIR = Path(__file__).parent.parent / "data" / "test"
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)


class TestRetrievalAgent:
    """Test Retrieval Agent functionality."""

    def test_agent_initialization(self):
        """Test RetrievalAgent can be initialized."""
        agent = RetrievalAgent()
        assert agent is not None
        assert agent.arxiv_client is not None
        assert agent.strategy_generator is not None

    def test_search_strategy_generator_keywords(self):
        """Test search keywords generation."""
        generator = SearchStrategyGenerator()

        keywords = generator.generate_keywords("diffusion model")
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        assert "diffusion model" in keywords

    def test_search_strategy_generator_categories(self):
        """Test category suggestion."""
        generator = SearchStrategyGenerator()

        # Test for AI-related topic
        cats = generator.suggest_categories("machine learning")
        assert isinstance(cats, list)
        assert len(cats) > 0
        assert any(cat in cats for cat in ["cs.AI", "cs.LG", "stat.ML"])

    def test_search_strategy_creation(self):
        """Test SearchStrategy creation via RetrievalAgent."""
        agent = RetrievalAgent()

        strategy = agent.generate_search_strategy(
            topic="neural networks",
            key_concepts=["deep learning", "transformer"],
        )

        assert isinstance(strategy, SearchStrategy)
        assert len(strategy.keywords) > 0
        assert len(strategy.categories) > 0
        assert len(strategy.date_range) == 2

    def test_paper_selection(self):
        """Test paper selection logic."""
        from src.tools.arxiv_api import ArxivPaper
        from datetime import datetime

        # Create mock papers
        papers = [
            ArxivPaper(
                paper_id=f"2301.{i:04d}",
                title=f"Paper {i}",
                authors=["Author A"],
                abstract="Abstract",
                published_date=f"2023-01-{i+1:02d}",
                updated_date="2023-01-01",
                categories=["cs.LG"],
                pdf_url=f"https://arxiv.org/pdf/2301.{i:04d}.pdf",
                arxiv_url=f"https://arxiv.org/abs/2301.{i:04d}",
            )
            for i in range(1, 6)
        ]

        agent = RetrievalAgent()
        selected_ids = agent.select_papers(papers, max_select=3)

        assert len(selected_ids) == 3
        # Should select newest first (higher number = newer)
        assert selected_ids[0] == "2301.0005"

    @pytest.mark.slow
    def test_retrieval_workflow(self):
        """Test complete retrieval workflow."""
        agent = RetrievalAgent()

        # This is a real API call test
        result = agent.run("deep learning image generation", max_results=3)

        assert isinstance(result, RetrievalResult)
        assert len(result.papers) <= 3
        assert isinstance(result.search_strategy, SearchStrategy)
        assert len(result.selected_paper_ids) > 0


class TestReaderAgent:
    """Test Reader Agent functionality."""

    def test_agent_initialization(self):
        """Test ReaderAgent can be initialized."""
        agent = ReaderAgent(max_workers=2)
        assert agent is not None
        assert agent.max_workers == 2

    def test_create_reading_tasks(self):
        """Test creating reading tasks."""
        from src.tools.arxiv_api import ArxivPaper

        papers = [
            ArxivPaper(
                paper_id="2301.0001",
                title="Test Paper 1",
                authors=["Author A"],
                abstract="Abstract 1",
                published_date="2023-01-01",
                updated_date="2023-01-01",
                categories=["cs.LG"],
                pdf_url="https://arxiv.org/pdf/2301.0001.pdf",
                arxiv_url="https://arxiv.org/abs/2301.0001",
            ),
            ArxivPaper(
                paper_id="2301.0002",
                title="Test Paper 2",
                authors=["Author B"],
                abstract="Abstract 2",
                published_date="2023-01-02",
                updated_date="2023-01-02",
                categories=["cs.CV"],
                pdf_url="https://arxiv.org/pdf/2301.0002.pdf",
                arxiv_url="https://arxiv.org/abs/2301.0002",
            ),
        ]

        agent = ReaderAgent()
        tasks = agent.create_tasks(papers)

        assert len(tasks) == 2
        assert all(isinstance(t, ReadingTask) for t in tasks)
        assert tasks[0].paper_id == "2301.0001"
        assert tasks[0].status == "pending"

    def test_reading_task_structure(self):
        """Test ReadingTask dataclass."""
        task = ReadingTask(
            paper_id="test123",
            title="Test Title",
            authors=["Author A", "Author B"],
            abstract="Test abstract",
            pdf_url="https://arxiv.org/pdf/test123.pdf",
            status="pending",
        )

        assert task.paper_id == "test123"
        assert len(task.authors) == 2
        assert task.status == "pending"

    def test_create_reading_tasks_for_langgraph(self):
        """Test creating tasks for LangGraph Send API."""
        papers_data = [
            {
                "paper_id": "2301.0001",
                "title": "Paper 1",
                "authors": ["A"],
                "abstract": "Abstract 1",
                "pdf_url": "url1",
            },
            {
                "paper_id": "2301.0002",
                "title": "Paper 2",
                "authors": ["B"],
                "abstract": "Abstract 2",
                "pdf_url": "url2",
            },
        ]

        tasks = create_reading_tasks(papers_data)

        assert len(tasks) == 2
        assert tasks[0]["paper_id"] == "2301.0001"
        assert "pdf_url" in tasks[0]

    def test_aggregate_reading_results(self):
        """Test aggregating reading results."""
        results = [
            {
                "paper_id": "2301.0001",
                "status": "completed",
                "title": "Paper 1",
                "authors": ["A"],
                "abstract": "Abstract 1",
                "extracted_content": {"word_count": 500},
            },
            {
                "paper_id": "2301.0002",
                "status": "failed",
                "error": "Download failed",
            },
        ]

        aggregated = aggregate_reading_results(results)

        assert "literature_data" in aggregated
        assert len(aggregated["literature_data"]) == 1
        assert aggregated["literature_data"][0]["paper_id"] == "2301.0001"


class TestAnalyzerAgent:
    """Test Analyzer Agent functionality."""

    def test_agent_initialization(self):
        """Test AnalyzerAgent can be initialized."""
        agent = AnalyzerAgent()
        assert agent is not None

    def test_prepare_paper_summary(self):
        """Test preparing paper summaries."""
        agent = AnalyzerAgent()

        literature_data = [
            {
                "paper_id": "2301.0001",
                "title": "Paper 1",
                "authors": ["A", "B"],
                "abstract": "Abstract 1",
                "extracted_content": {
                    "section_names": ["Introduction", "Methods"],
                    "word_count": 1000,
                    "reference_count": 20,
                },
            },
            {
                "paper_id": "2301.0002",
                "title": "Paper 2",
                "authors": ["C"],
                "abstract": "Abstract 2",
                "extracted_content": {
                    "section_names": ["Introduction", "Experiments"],
                    "word_count": 1500,
                    "reference_count": 25,
                },
            },
        ]

        summaries = agent.prepare_paper_summary(literature_data)

        assert len(summaries) == 2
        assert summaries[0]["paper_id"] == "2301.0001"
        assert summaries[0]["word_count"] == 1000

    def test_paper_cluster_structure(self):
        """Test PaperCluster dataclass."""
        cluster = PaperCluster(
            cluster_id="cluster_1",
            cluster_name="Deep Learning",
            paper_ids=["2301.0001", "2301.0002"],
            common_theme="Neural networks",
            common_approach="Deep learning",
            key_differences=["Architecture variations"],
            representative_papers=[],
        )

        assert cluster.cluster_id == "cluster_1"
        assert len(cluster.paper_ids) == 2

    def test_global_knowledge_structure(self):
        """Test GlobalKnowledge dataclass."""
        knowledge = GlobalKnowledge(
            research_background="Background text",
            mainstream_methods=[
                {"name": "Method 1", "description": "Desc", "pros": "Pro 1", "cons": "Con 1"}
            ],
            performance_comparison="Comparison text",
            research_gaps=[{"gap": "Gap 1", "importance": "high", "opportunity": "Op 1"}],
            future_directions=["Direction 1"],
            key_findings=["Finding 1"],
        )

        assert knowledge.research_background == "Background text"
        assert len(knowledge.mainstream_methods) == 1

    @pytest.mark.slow
    def test_analyze_literature_function(self):
        """Test analyze_literature convenience function."""
        # This is a real API call test (expensive)
        # We'll mock the LLM to avoid actual API calls

        literature_data = [
            {
                "paper_id": "2301.0001",
                "title": "Paper 1",
                "authors": ["A"],
                "abstract": "Abstract about deep learning",
                "extracted_content": {
                    "section_names": ["Introduction"],
                    "word_count": 500,
                    "reference_count": 10,
                },
            }
        ]

        # Mock the LLM to avoid real API calls
        with patch('config.settings.get_llm_client') as mock_llm:
            mock_response = Mock()
            mock_response.content = json.dumps({
                "clusters": [
                    {
                        "cluster_id": "cluster_1",
                        "cluster_name": "Test Cluster",
                        "paper_ids": ["2301.0001"],
                        "common_theme": "Deep learning",
                        "common_approach": "Neural networks",
                        "key_differences": ["None"]
                    }
                ]
            })
            mock_llm.return_value.invoke.return_value = mock_response

            result = analyze_literature(literature_data, "topic")

            assert "literature_clusters" in result
            assert "global_knowledge" in result


class TestIntegration:
    """Integration tests for retrieval + reading pipeline."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_retrieval_to_reading_pipeline(self):
        """Test full retrieval -> reading pipeline."""
        # This would be a real integration test
        # Skipping to avoid long test time
        pytest.skip("Integration test - run manually")

    def test_mock_pipeline(self):
        """Test pipeline with mocked components."""
        # Create mock papers
        from src.tools.arxiv_api import ArxivPaper

        mock_papers = [
            ArxivPaper(
                paper_id=f"23{i:02d}.0001",
                title=f"Paper {i}",
                authors=["Author"],
                abstract="Abstract",
                published_date=f"2023-01-0{i+1}",
                updated_date="2023-01-01",
                categories=["cs.LG"],
                pdf_url=f"https://arxiv.org/pdf/23{i:02d}.0001.pdf",
                arxiv_url=f"https://arxiv.org/abs/23{i:02d}.0001",
            )
            for i in range(1, 4)
        ]

        # Create reader agent
        agent = ReaderAgent(max_workers=2)
        tasks = agent.create_tasks(mock_papers)

        assert len(tasks) == 3
        assert all(t.status == "pending" for t in tasks)


class TestPerformance:
    """Performance tests."""

    @pytest.mark.slow
    def test_parallel_reading_performance(self):
        """Test parallel reading performance."""
        import time

        # Create mock tasks
        tasks = [
            ReadingTask(
                paper_id=f"test_{i}",
                title=f"Paper {i}",
                authors=["Author"],
                abstract="Abstract",
                pdf_url=f"url_{i}",
            )
            for i in range(5)
        ]

        # Mock processing
        def mock_process(task):
            import time
            time.sleep(0.1)  # Simulate work
            task.status = "completed"
            task.parsed_content = {"word_count": 100}
            return task

        agent = ReaderAgent(max_workers=3)

        # Patch process_task to avoid real work
        with patch.object(agent, 'process_task', mock_process):
            start = time.time()
            results = agent.process_batch(tasks, max_workers=3)
            elapsed = time.time() - start

        # With 3 workers, 5 tasks of 0.1s each should take ~0.2s (parallel)
        # But with overhead, should be < 1s
        assert elapsed < 1.0
        print(f"\nParallel processing time for 5 tasks: {elapsed:.3f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "not slow"])
