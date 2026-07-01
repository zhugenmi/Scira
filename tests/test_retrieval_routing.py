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


def _make_strategy(domain: str = "general", has_chinese: bool = False) -> SearchStrategy:
    return SearchStrategy(
        keywords=["test"],
        boolean_query='"test"',
        categories=[],
        date_range=("2024-01-01", "2026-01-01"),
        max_results=10,
        rationale="test",
        domain=domain,
        has_chinese=has_chinese,
    )


def test_execute_search_uses_computed_sources_for_medical():
    """execute_search should post sources containing pubmed (not dblp) for medical domain."""
    agent = RetrievalAgent()
    strategy = _make_strategy(domain="medical", has_chinese=False)
    with patch("src.agents.retrieval.requests.post") as mock_post, \
         patch.dict("os.environ", {}, clear=False):
        mock_post.return_value.json.return_value = {"papers": []}
        mock_post.return_value.raise_for_status.return_value = None
        agent.execute_search(strategy)
    posted_payload = mock_post.call_args[1]["json"]
    sources = posted_payload["sources"].split(",")
    assert "pubmed" in sources
    assert "dblp" not in sources
    assert sources != ["all"]


def test_execute_search_uses_computed_sources_for_cs_with_chinese():
    """CS query with Chinese text should add wanfang when enabled."""
    agent = RetrievalAgent()
    strategy = _make_strategy(domain="computer_science", has_chinese=True)
    env = {"WFDATA_APP_KEY": "k", "WFDATA_APP_CODE": "c", "APAPER_MCP_ENABLED": "1"}
    with patch("src.agents.retrieval.requests.post") as mock_post, \
         patch.dict("os.environ", env, clear=False):
        mock_post.return_value.json.return_value = {"papers": []}
        mock_post.return_value.raise_for_status.return_value = None
        agent.execute_search(strategy)
    posted_payload = mock_post.call_args[1]["json"]
    sources = posted_payload["sources"].split(",")
    assert "dblp" in sources
    assert "wanfang" in sources
    assert "cnki" in sources


def test_execute_search_omits_cn_when_disabled():
    """No CN env vars → no wanfang/cnki in sources, even for Chinese medical query."""
    agent = RetrievalAgent()
    strategy = _make_strategy(domain="medical", has_chinese=True)
    with patch("src.agents.retrieval.requests.post") as mock_post, \
         patch.dict("os.environ", {}, clear=True):
        mock_post.return_value.json.return_value = {"papers": []}
        mock_post.return_value.raise_for_status.return_value = None
        agent.execute_search(strategy)
    posted_payload = mock_post.call_args[1]["json"]
    sources = posted_payload["sources"].split(",")
    assert "wanfang" not in sources
    assert "cnki" not in sources


def test_search_strategy_has_domain_and_has_chinese_fields():
    s = _make_strategy(domain="biology", has_chinese=True)
    assert s.domain == "biology"
    assert s.has_chinese is True


def test_graphstate_has_domain_field():
    """GraphState TypedDict must declare 'domain' or LangGraph silently drops it."""
    from src.core.state import GraphState
    # TypedDict.__annotations__ lists all declared fields.
    assert "domain" in GraphState.__annotations__
