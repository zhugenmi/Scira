"""Tests for RetrievalAgent domain extraction and source routing.

These tests mock the LLM and the HTTP call to MCP search, so they verify
routing logic without any real network traffic.
"""
import json
from unittest.mock import patch, MagicMock

import pytest

from src.agents.retrieval import RetrievalAgent, SearchStrategy
from src.mcp.paper_search_mcp.domain_routing import VALID_DOMAINS


def _fake_llm_response(content: str):
    """Build a fake LLM response object with .content and .usage_metadata."""
    resp = MagicMock()
    resp.content = content
    resp.usage_metadata = {}
    return resp


def test_analyze_query_extracts_domain():
    """analyze_query should return a 'domain' key from the LLM JSON."""
    agent = RetrievalAgent()
    fake_json = json.dumps({
        "normalized_topic": "graph neural networks",
        "key_concepts": ["GNN", "message passing"],
        "research_direction": "exploratory",
        "background_context": "graph representation learning",
        "domain": "computer_science",
    })
    with patch("config.settings.get_llm_client") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _fake_llm_response(fake_json)
        mock_llm_factory.return_value = mock_llm
        result = agent.analyze_query("graph neural networks survey")

    assert result["domain"] == "computer_science"


def test_analyze_query_invalid_domain_falls_back_to_general():
    """LLM returning a bogus domain should fall back to 'general'."""
    agent = RetrievalAgent()
    fake_json = json.dumps({
        "normalized_topic": "quantum biology",
        "key_concepts": ["quantum", "biology"],
        "research_direction": "exploratory",
        "background_context": "cross-field",
        "domain": "quantum_unicorn_field",  # invalid
    })
    with patch("config.settings.get_llm_client") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _fake_llm_response(fake_json)
        mock_llm_factory.return_value = mock_llm
        result = agent.analyze_query("quantum biology")

    assert result["domain"] == "general"


def test_analyze_query_missing_domain_falls_back_to_general():
    """LLM omitting domain should fall back to 'general'."""
    agent = RetrievalAgent()
    fake_json = json.dumps({
        "normalized_topic": "diffusion models",
        "key_concepts": ["diffusion", "generative"],
        "research_direction": "exploratory",
        "background_context": "generative models",
    })
    with patch("config.settings.get_llm_client") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _fake_llm_response(fake_json)
        mock_llm_factory.return_value = mock_llm
        result = agent.analyze_query("diffusion models")

    assert result["domain"] == "general"
