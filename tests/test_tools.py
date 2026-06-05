"""
Scira Tools Test Suite

Tests for:
1. PDF Parser (extraction)
2. Format Utils (citation formatting)

Note: Paper search functionality is now in MCP service (src/mcp/paper-search-mcp/)
"""

import os
import sys
import json
import tempfile
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Note: arxiv_api has been moved to src/mcp/paper-search-mcp/
# Import from MCP if needed:
# from src.mcp.paper_search_mcp.academic_platforms import arxiv_searcher

from src.tools.pdf_parser import PDFParser, ParserBackend, ParsedPaper
from src.tools.format_utils import (
    CitationFormatter,
    CitationStyle,
    Citation,
    PaperFormatter,
    ReferenceManager,
    format_citation,
)


# Test data directory
TEST_DATA_DIR = Path(__file__).parent.parent / "data" / "test"
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)


# Note: ArxivAPI tests removed - functionality moved to MCP service
# See tests/test_mcp.py for MCP service tests


class TestPDFParser:
    """Test PDF parsing and information extraction."""

    @pytest.fixture
    def sample_pdf_path(self):
        """Create a sample PDF for testing."""
        # Create a simple test PDF using reportlab or similar
        # For now, we'll check if pypdf can create one or skip
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter

            pdf_path = TEST_DATA_DIR / "sample_paper.pdf"

            # Create simple PDF
            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            c.drawString(100, 750, "Test Paper Title")
            c.drawString(100, 730, "Author: Test Author")
            c.drawString(100, 700, "Abstract: This is a test abstract.")
            c.drawString(100, 650, "1. Introduction")
            c.drawString(100, 630, "This is the introduction section.")
            c.drawString(100, 600, "2. Methods")
            c.drawString(100, 580, "This is the methods section.")
            c.drawString(100, 550, "References")
            c.drawString(100, 530, "[1] Test Reference 1")
            c.showPage()
            c.save()

            return str(pdf_path)

        except ImportError:
            pytest.skip("reportlab not installed, skipping PDF creation test")

    def test_parser_initialization(self):
        """Test parser can be initialized."""
        parser = PDFParser()
        assert parser is not None
        assert parser.backend == ParserBackend.PYMUPDF

    def test_parser_with_different_backends(self):
        """Test parser with different backends."""
        parser_pymupdf = PDFParser(backend=ParserBackend.PYMUPDF)
        parser_pypdf = PDFParser(backend=ParserBackend.PYPDF)

        assert parser_pymupdf.backend == ParserBackend.PYMUPDF
        assert parser_pypdf.backend == ParserBackend.PYPDF

    def test_parsed_paper_structure(self):
        """Test ParsedPaper dataclass structure."""
        # Create minimal test
        paper = ParsedPaper(
            paper_id="test123",
            title="Test Title",
            authors=["Author One", "Author Two"],
            abstract="Test abstract content",
            sections={"Introduction": "Intro text"},
            references=["Ref 1", "Ref 2"],
            tables=[],
            figures=[],
            raw_text="Full text",
            word_count=10,
            metadata={}
        )

        assert paper.paper_id == "test123"
        assert paper.title == "Test Title"
        assert len(paper.authors) == 2
        assert paper.word_count == 10

    def test_clean_text_function(self):
        """Test text cleaning functionality."""
        parser = PDFParser()

        # Test cleaning
        dirty_text = "Hello\n\n\n\nWorld"
        cleaned = parser._clean_text(dirty_text)
        assert "\n\n\n" not in cleaned


class TestFormatUtils:
    """Test citation formatting and paper output."""

    def test_citation_formatter_apa(self):
        """Test APA citation format."""
        citation = Citation(
            paper_id="2301.12345",
            authors=["John Smith", "Jane Doe"],
            title="Deep Learning for Science",
            year="2023",
            venue="Nature",
            journal="Nature",
            volume="15",
            issue="3",
            pages="123-145",
            doi="10.1234/test",
            url="https://arxiv.org/2301.12345",
            arxiv_id="2301.12345"
        )

        formatter = CitationFormatter(CitationStyle.APA)
        result = formatter.format(citation)

        assert "Smith" in result
        assert "2023" in result
        assert "Deep Learning for Science" in result

    def test_citation_formatter_ieee(self):
        """Test IEEE citation format."""
        citation = Citation(
            paper_id="2301.12345",
            authors=["John Smith", "Jane Doe"],
            title="Test Paper",
            year="2023",
            venue="Conference",
            journal=None,
            volume="1",
            issue="1",
            pages="10-20",
            doi=None,
            url=None,
            arxiv_id="2301.12345"
        )

        formatter = CitationFormatter(CitationStyle.IEEE)
        result = formatter.format(citation)

        assert "Smith" in result
        assert "Test Paper" in result

    def test_citation_formatter_mla(self):
        """Test MLA citation format."""
        citation = Citation(
            paper_id="2301.12345",
            authors=["John Smith"],
            title="A Great Paper",
            year="2023",
            venue="Journal",
            journal="Journal",
            volume="5",
            issue="2",
            pages="50-60",
            doi=None,
            url=None,
            arxiv_id=None
        )

        formatter = CitationFormatter(CitationStyle.MLA)
        result = formatter.format(citation)

        assert "Smith" in result

    def test_citation_list_formatting(self):
        """Test formatting multiple citations."""
        citations = [
            Citation("1", ["A Author"], "Paper 1", "2023", None, None, None, None, None, None, None, None),
            Citation("2", ["B Author"], "Paper 2", "2022", None, None, None, None, None, None, None, None),
        ]

        formatter = CitationFormatter(CitationStyle.IEEE)
        result = formatter.format_list(citations)

        assert "[1]" in result
        assert "[2]" in result

    def test_format_citation_helper(self):
        """Test quick format_citation helper."""
        paper_data = {
            "paper_id": "2301.12345",
            "authors": ["Test Author"],
            "title": "Test Title",
            "published_date": "2023-01-15",
            "journal_ref": "Test Journal",
            "doi": "10.1234/test",
        }

        result = format_citation(paper_data, CitationStyle.APA)

        assert "Author" in result
        assert "2023" in result

    def test_paper_formatter_markdown(self):
        """Test Markdown output formatting."""
        formatter = PaperFormatter()

        sections = {
            "Introduction": "This is the introduction.",
            "Methods": "This describes the methods."
        }

        citations = [
            Citation("1", ["Author A"], "Paper A", "2023", None, None, None, None, None, None, None, None)
        ]

        result = formatter.format_markdown(
            title="Test Paper",
            abstract="This is abstract.",
            sections=sections,
            references=citations,
            style=CitationStyle.IEEE
        )

        assert "# Test Paper" in result
        assert "## Abstract" in result
        assert "## Introduction" in result
        assert "## References" in result

    def test_reference_manager(self):
        """Test ReferenceManager functionality."""
        manager = ReferenceManager()

        paper_data = {
            "paper_id": "test123",
            "authors": ["Test Author"],
            "title": "Test Title",
            "published_date": "2023-01-01",
            "journal_ref": "Test Journal",
        }

        citation = manager.add(paper_data)

        assert citation.paper_id == "test123"
        assert manager.get("test123") is not None

        all_citations = manager.get_all()
        assert len(all_citations) == 1

    def test_reference_manager_json_export(self):
        """Test ReferenceManager JSON export/import."""
        manager = ReferenceManager()

        paper_data = {
            "paper_id": "test123",
            "authors": ["Test Author"],
            "title": "Test Title",
            "published_date": "2023-01-01",
        }

        manager.add(paper_data)

        json_str = manager.to_json()
        assert "test123" in json_str

        # Test import
        new_manager = ReferenceManager()
        new_manager.from_json(json_str)
        assert len(new_manager.get_all()) == 1


# Note: Integration and Performance tests removed - depend on ArxivClient
# which has been moved to MCP service


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
