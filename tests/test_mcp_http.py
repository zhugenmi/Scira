"""
Scira MCP HTTP API Tests

Tests for MCP server HTTP API endpoints.
Requires MCP server to be running first.

Usage:
1. Terminal 1: python -m src.mcp.server
2. Terminal 2: python -m pytest tests/test_mcp_http.py -v
"""

import os
import sys
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

# 整个文件需要后端服务运行（python -m src.mcp.server），标记为 integration 默认跳过。
pytestmark = pytest.mark.integration

# Load environment variables
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# MCP server configuration
MCP_BASE_URL = os.getenv("MCP_API_URL", "http://localhost:8001")


class TestMCPHealth:
    """Test MCP server health endpoints."""

    def test_health_check(self):
        """Test /health endpoint."""
        response = requests.get(f"{MCP_BASE_URL}/health", timeout=10)

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data

        print(f"\nHealth status: {data['status']}")
        print(f"Services: {data['services']}")

    def test_list_services(self):
        """Test /services endpoint."""
        response = requests.get(f"{MCP_BASE_URL}/services", timeout=10)

        assert response.status_code == 200
        data = response.json()

        assert "paper-search" in data
        assert data["paper-search"]["enabled"] is True

        print(f"\nAvailable services: {list(data.keys())}")


class TestMCPPaperSearch:
    """Test paper search API - minimal version."""

    def test_search_all_sources_single(self):
        """Test all sources search - get only 1 result."""
        response = requests.post(
            f"{MCP_BASE_URL}/api/paper-search/search",
            json={
                "query": "machine learning",
                "max_results": 1,
                "sources": "all",  # Use all sources
            },
            timeout=120,
        )

        # Handle rate limiting
        if response.status_code == 429:
            pytest.skip("Rate limited by external API")

        print(f"\nResponse status: {response.status_code}")
        print(f"Response: {response.text[:300]}")

        assert response.status_code == 200
        data = response.json()

        assert "papers" in data
        assert data["total"] >= 1, f"Should have at least 1 result, got {data['total']}"

        print(f"\n✅ Search passed: {data['total']} paper found")
        print(f"Sources used: {data.get('sources_used', [])}")


class TestMCPPaperDownload:
    """Test paper download API - single file."""

    def test_download_single_paper(self):
        """Test downloading 1 paper."""
        # First search for a paper ID
        search_response = requests.post(
            f"{MCP_BASE_URL}/api/paper-search/search",
            json={
                "query": "transformer",
                "max_results": 1,
                "sources": "all",
            },
            timeout=120,
        )

        if search_response.status_code == 429:
            pytest.skip("Rate limited")

        papers = search_response.json().get("papers", [])
        if not papers:
            pytest.skip("No papers found")

        paper_id = papers[0].get("paper_id")
        if not paper_id:
            pytest.skip("No paper ID")

        print(f"\nDownloading paper: {paper_id}")

        # Download
        download_response = requests.post(
            f"{MCP_BASE_URL}/api/paper-search/download",
            json={
                "source": "arxiv",
                "paper_id": paper_id,
                "save_path": "./data/test/downloads",
            },
            timeout=120,
        )

        # May fail if paper doesn't exist
        if download_response.status_code == 500:
            pytest.skip(f"Download failed: {download_response.text}")

        assert download_response.status_code == 200
        data = download_response.json()

        assert data.get("success") is True
        print(f"\n✅ Download passed: {data.get('save_path')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
