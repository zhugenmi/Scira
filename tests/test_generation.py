"""
Scira Generation Pipeline Tests

Tests for:
1. WriterAgent - Outline generation, section writing
2. ReviewerAgent - Review, 首尾 generation
"""

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.writer import (
    WriterAgent,
    PaperSection,
    PaperOutline,
    WritingResult,
    write_paper,
    create_writing_tasks,
    writing_node,
)
from src.agents.reviewer import (
    ReviewerAgent,
    RevisionFeedback,
    ReviewResult,
    review_and_finalize,
)


TEST_DATA_DIR = Path(__file__).parent.parent / "data" / "test"
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)


class TestWriterAgent:
    """Test Writer Agent functionality."""

    def test_agent_initialization(self):
        """Test WriterAgent can be initialized."""
        agent = WriterAgent()
        assert agent is not None

    def test_paper_section_structure(self):
        """Test PaperSection dataclass."""
        section = PaperSection(
            section_id="intro",
            title="Introduction",
            content="Introduction content",
            subsections=["Motivation", "Background"],
            key_points=["Point 1", "Point 2"],
            word_count=100,
            status="completed",
        )

        assert section.section_id == "intro"
        assert section.word_count == 100
        assert section.status == "completed"

    def test_paper_outline_structure(self):
        """Test PaperOutline dataclass."""
        sections = [
            PaperSection(section_id="intro", title="Introduction"),
            PaperSection(section_id="methods", title="Methods"),
        ]

        outline = PaperOutline(
            title="Test Paper",
            abstract_requirements="Background, problem, approach, results",
            sections=sections,
            total_estimated_words=5000,
            writing_style="Academic",
        )

        assert outline.title == "Test Paper"
        assert len(outline.sections) == 2

    def test_default_outline(self):
        """Test default outline creation."""
        agent = WriterAgent()
        outline = agent._default_outline("Test Topic")

        assert outline.title == "Test Topic"
        assert len(outline.sections) > 0

    def test_combine_content(self):
        """Test combining sections into paper."""
        agent = WriterAgent()

        sections = {
            "intro": PaperSection(
                section_id="intro",
                title="Introduction",
                content="Intro content here",
                word_count=100,
                status="completed",
            ),
            "methods": PaperSection(
                section_id="methods",
                title="Methods",
                content="Methods content here",
                word_count=200,
                status="completed",
            ),
        }

        content = agent.combine_content(sections)

        assert "## Introduction" in content
        assert "## Methods" in content
        assert "Intro content here" in content

    def test_writing_result_structure(self):
        """Test WritingResult dataclass."""
        sections = {
            "intro": PaperSection(
                section_id="intro",
                title="Introduction",
                content="Content",
                word_count=100,
                status="completed",
            )
        }

        outline = PaperOutline(
            title="Test",
            abstract_requirements="",
            sections=[],
            total_estimated_words=1000,
            writing_style="Academic",
        )

        result = WritingResult(
            outline=outline,
            sections=sections,
            completed_sections=1,
            failed_sections=0,
            total_words=100,
            paper_content="Content",
        )

        assert result.completed_sections == 1
        assert result.total_words == 100

    def test_to_graphstate_format(self):
        """Test converting to GraphState format."""
        agent = WriterAgent()

        sections = {
            "intro": PaperSection(
                section_id="intro",
                title="Introduction",
                content="Intro text",
                word_count=100,
                status="completed",
                references=["Ref 1"],
            )
        }

        outline = PaperOutline(
            title="Test Paper",
            abstract_requirements="Background, method, results",
            sections=[PaperSection(section_id="intro", title="Introduction")],
            total_estimated_words=5000,
            writing_style="Academic",
        )

        result = WritingResult(
            outline=outline,
            sections=sections,
            completed_sections=1,
            failed_sections=0,
            total_words=100,
            paper_content="Intro text",
        )

        gs = agent.to_graphstate_format(result)

        assert "outline" in gs
        assert "chapter_drafts" in gs
        assert "final_paper" in gs
        assert "Introduction" in gs["chapter_drafts"]

    def test_create_writing_tasks(self):
        """Test creating writing tasks for LangGraph."""
        outline = {
            "sections": [
                {"section_id": "intro", "title": "Introduction", "key_points": ["Point 1"]},
                {"section_id": "methods", "title": "Methods", "key_points": ["Point 2"]},
            ]
        }

        tasks = create_writing_tasks(outline)

        assert len(tasks) == 2
        assert tasks[0]["section_id"] == "intro"
        assert "key_points" in tasks[0]


class TestReviewerAgent:
    """Test Reviewer Agent functionality."""

    def test_agent_initialization(self):
        """Test ReviewerAgent can be initialized."""
        agent = ReviewerAgent()
        assert agent is not None

    def test_revision_feedback_structure(self):
        """Test RevisionFeedback dataclass."""
        feedback = RevisionFeedback(
            section_id=None,
            logic_issues=[{"location": "Section 2", "issue": "Logic gap", "severity": "high"}],
            language_issues=[{"location": "Section 1", "issue": "Word choice", "suggestion": "Use better word"}],
            structure_issues=[],
            overall_assessment="Good paper",
            revision_priority="medium",
        )

        assert feedback.revision_priority == "medium"
        assert len(feedback.logic_issues) == 1

    def test_review_result_structure(self):
        """Test ReviewResult dataclass."""
        feedback = RevisionFeedback(
            section_id=None,
            logic_issues=[],
            language_issues=[],
            structure_issues=[],
            overall_assessment="Good",
            revision_priority="low",
        )

        result = ReviewResult(
            feedback=[feedback],
            abstract="Abstract text",
            introduction="Intro text",
            conclusion="Conclusion text",
            final_paper="Full paper",
        )

        assert result.abstract == "Abstract text"
        assert result.final_paper is not None

    def test_assemble_final_paper(self):
        """Test assembling final paper from parts."""
        agent = ReviewerAgent()

        final = agent.assemble_final_paper(
            abstract="This is abstract.",
            introduction="This is introduction.",
            body="## Methods\nMethods content.\n\n## Results\nResults content.",
            conclusion="This is conclusion.",
        )

        assert "## Abstract" in final
        assert "This is abstract." in final
        assert "## Introduction" in final
        assert "## Conclusion" in final

    def test_to_graphstate_format(self):
        """Test converting to GraphState format."""
        agent = ReviewerAgent()

        feedback = RevisionFeedback(
            section_id=None,
            logic_issues=[],
            language_issues=[],
            structure_issues=[],
            overall_assessment="Good",
            revision_priority="low",
        )

        result = ReviewResult(
            feedback=[feedback],
            abstract="Abstract",
            introduction="Intro",
            conclusion="Conclusion",
            final_paper="Full paper",
        )

        gs = agent.to_graphstate_format(result)

        assert "revision_feedback" in gs
        assert "abstract" in gs
        assert "introduction" in gs
        assert "conclusion" in gs
        assert "final_review" in gs
        assert gs["final_review"] == "Full paper"


class TestIntegration:
    """Integration tests for generation pipeline."""

    @pytest.mark.slow
    def test_mocked_write_and_review(self):
        """Test mocked write + review pipeline."""
        # Mock LLM
        with patch('config.settings.get_llm_client') as mock_get_llm:
            mock_llm = MagicMock()
            mock_response = Mock()
            mock_response.content = json.dumps({
                "title": "Test Paper",
                "abstract_requirements": "Background, method, results",
                "sections": [
                    {"section_id": "intro", "title": "Introduction", "key_points": ["Point 1"]}
                ],
                "total_estimated_words": 5000,
                "writing_style": "Academic"
            })
            mock_llm.invoke.return_value = mock_response
            mock_get_llm.return_value = mock_llm

            # Test WriterAgent
            agent = WriterAgent()
            global_knowledge = {
                "research_background": "Background text",
                "mainstream_methods": [],
                "key_findings": ["Finding 1"],
            }

            outline = agent.generate_outline(global_knowledge, "Test Topic")
            assert outline.title == "Test Paper"

    def test_section_writing_context(self):
        """Test section writing with context."""
        agent = WriterAgent()

        section = PaperSection(
            section_id="intro",
            title="Introduction",
            key_points=["Motivation", "Problem"],
        )

        context = {
            "topic": "Machine Learning",
            "global_knowledge": {
                "research_background": "ML background"
            },
            "writing_style": "Academic",
        }

        # Mock LLM to avoid real API call
        with patch.object(agent, 'llm') as mock_llm:
            mock_response = Mock()
            mock_response.content = "Written content"
            mock_llm.invoke.return_value = mock_response

            result = agent.write_section(section, context)

            assert result.status == "completed"
            assert result.content == "Written content"
            assert result.word_count == 2


class TestFrontMatterGeneration:
    """Tests for 首尾章节后置生成."""

    def test_abstract_generation(self):
        """Test abstract generation."""
        with patch('config.settings.get_llm_client') as mock_get_llm:
            mock_llm = MagicMock()
            mock_response = Mock()
            mock_response.content = "This is a generated abstract."
            mock_llm.invoke.return_value = mock_response
            mock_get_llm.return_value = mock_llm

            agent = ReviewerAgent()
            abstract = agent.generate_abstract(
                paper_content="Body content here...",
                topic="Machine Learning",
                global_knowledge={"research_background": "ML background"},
                key_findings=["Finding 1"],
            )

            assert abstract == "This is a generated abstract."

    def test_introduction_generation(self):
        """Test introduction generation."""
        with patch('config.settings.get_llm_client') as mock_get_llm:
            mock_llm = MagicMock()
            mock_response = Mock()
            mock_response.content = "This is a generated introduction."
            mock_llm.invoke.return_value = mock_response
            mock_get_llm.return_value = mock_llm

            agent = ReviewerAgent()
            intro = agent.generate_introduction(
                paper_content="Body content...",
                topic="Deep Learning",
                global_knowledge={"research_background": "DL background"},
            )

            assert intro == "This is a generated introduction."

    def test_conclusion_generation(self):
        """Test conclusion generation."""
        with patch('config.settings.get_llm_client') as mock_get_llm:
            mock_llm = MagicMock()
            mock_response = Mock()
            mock_response.content = "This is a generated conclusion."
            mock_llm.invoke.return_value = mock_response
            mock_get_llm.return_value = mock_llm

            agent = ReviewerAgent()
            conclusion = agent.generate_conclusion(
                paper_content="Body content...",
                topic="Neural Networks",
                global_knowledge={"key_findings": ["Finding 1"]},
            )

            assert conclusion == "This is a generated conclusion."

    def test_generate_front_matter(self):
        """Test front matter generation."""
        with patch('config.settings.get_llm_client') as mock_get_llm:
            mock_llm = MagicMock()
            mock_response = Mock()

            # Different responses for different calls
            call_count = [0]
            def invoke_side_effect(*args, **kwargs):
                call_count[0] += 1
                mock_resp = Mock()
                if call_count[0] == 1:
                    mock_resp.content = "Generated abstract"
                elif call_count[0] == 2:
                    mock_resp.content = "Generated introduction"
                else:
                    mock_resp.content = "Generated conclusion"
                return mock_resp

            mock_llm.invoke.side_effect = invoke_side_effect
            mock_get_llm.return_value = mock_llm

            agent = ReviewerAgent()
            front_matter = agent.generate_front_matter(
                paper_content="Body",
                topic="AI",
                global_knowledge={},
            )

            assert "abstract" in front_matter
            assert "introduction" in front_matter
            assert "conclusion" in front_matter


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
