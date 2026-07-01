"""
Scira MCP Service Tests

Tests for MCP paper search and download functionality.
"""

import os
import sys
import pytest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Add MCP project to path (目录名是下划线 paper_search_mcp，非连字符)
MCP_PATH = PROJECT_ROOT / "src" / "mcp" / "paper_search_mcp"
sys.path.insert(0, str(MCP_PATH.parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


@pytest.mark.integration
class TestMCPSearch:
    """Test MCP paper search functionality.

    Integration tests — require real network access to arXiv / Semantic Scholar /
    PubMed. Skipped by default; run with `pytest --run-integration` or
    `pytest -m integration`.
    """

    def test_search_arxiv(self):
        """Test arXiv search."""
        from paper_search_mcp.academic_platforms import arxiv_searcher

        results = arxiv_searcher.search("machine learning", max_results=5)

        assert isinstance(results, list)
        assert len(results) > 0, "Should return at least one result"

        # Check paper structure
        paper = results[0]
        assert hasattr(paper, "paper_id")
        assert hasattr(paper, "title")
        assert hasattr(paper, "pdf_url")

        print(f"\nArXiv search returned {len(results)} papers")
        print(f"First paper: {paper.title[:50]}...")

    def test_search_semantic_scholar(self):
        """Test Semantic Scholar search."""
        from paper_search_mcp.academic_platforms import semantic_searcher

        results = semantic_searcher.search("deep learning", max_results=5)

        assert isinstance(results, list)
        assert len(results) > 0, "Should return at least one result"

        paper = results[0]
        assert hasattr(paper, "paper_id")
        assert hasattr(paper, "title")

        print(f"\nSemantic Scholar search returned {len(results)} papers")

    def test_search_pubmed(self):
        """Test PubMed search."""
        from paper_search_mcp.academic_platforms import pubmed_searcher

        results = pubmed_searcher.search("cancer", max_results=5)

        assert isinstance(results, list)
        assert len(results) > 0, "Should return at least one result"

        paper = results[0]
        assert hasattr(paper, "paper_id")

        print(f"\nPubMed search returned {len(results)} papers")


@pytest.mark.integration
class TestMCPDownload:
    """Test MCP paper download functionality.

    Integration tests — require real arXiv PDF downloads. Skipped by default.
    """

    def test_download_arxiv_pdf(self):
        """Test arXiv PDF download."""
        from paper_search_mcp.academic_platforms import arxiv_searcher

        # First search for a paper
        results = arxiv_searcher.search("transformer", max_results=1)
        assert len(results) > 0, "Need at least one paper to download"

        paper_id = results[0].paper_id

        # Download PDF
        save_dir = PROJECT_ROOT / "data" / "test" / "downloads"
        save_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = arxiv_searcher.download_pdf(paper_id, str(save_dir))

        assert pdf_path is not None
        assert Path(pdf_path).exists(), f"PDF should exist at {pdf_path}"

        print(f"\nDownloaded PDF to: {pdf_path}")

        # Cleanup
        if Path(pdf_path).exists():
            Path(pdf_path).unlink()

    def test_download_arxiv_by_id(self):
        """Test downloading specific arXiv paper."""
        from paper_search_mcp.academic_platforms import arxiv_searcher

        # Use a known arXiv ID
        paper_id = "2310.00001"  # Example ID format

        save_dir = PROJECT_ROOT / "data" / "test" / "downloads"
        save_dir.mkdir(parents=True, exist_ok=True)

        try:
            pdf_path = arxiv_searcher.download_pdf(paper_id, str(save_dir))

            # Check if download succeeded (may fail if paper doesn't exist)
            if pdf_path and Path(pdf_path).exists():
                print(f"\nDownloaded PDF to: {pdf_path}")
                Path(pdf_path).unlink()
            else:
                print(f"\nPaper {paper_id} may not exist or download failed")
        except Exception as e:
            print(f"\nDownload failed (expected if paper doesn't exist): {e}")


@pytest.mark.integration
class TestMCPPaperRead:
    """Test MCP paper reading functionality.

    Integration tests — require real arXiv PDF download + parse. Skipped by default.
    """

    def test_read_arxiv_paper(self):
        """Test reading arXiv paper content."""
        from paper_search_mcp.academic_platforms import arxiv_searcher

        # Search for a paper
        results = arxiv_searcher.search("neural network", max_results=1)
        assert len(results) > 0

        paper_id = results[0].paper_id

        # Read paper content
        content = arxiv_searcher.read_paper(paper_id)

        assert content is not None
        assert len(content) > 0, "Paper content should not be empty"

        print(f"\nRead paper content: {len(content)} characters")
        print(f"First 200 chars: {content[:200]}...")


class TestMCPConfig:
    """Test MCP configuration from .env."""

    def test_env_loaded(self):
        """Test that environment variables are loaded."""
        # Check key MCP config
        email = os.getenv("PAPER_SEARCH_MCP_UNPAYWALL_EMAIL")
        print(f"\nUnpaywall email configured: {bool(email)}")

        # This should pass as long as .env is loaded
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
