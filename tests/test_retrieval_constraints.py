"""Tests for user-specified retrieval constraints (year range, min count)."""
import datetime
import json
from unittest.mock import patch, MagicMock

from src.agents.intent import IntentAgent, _extract_constraints_fallback
from src.agents.retrieval import RetrievalAgent, SearchStrategy


def test_fallback_recent_n_years_chinese_arabic():
    """'最近5年' should yield year_range ending at current year."""
    yr, _ = _extract_constraints_fallback("最近5年知识图谱最新研究")
    assert yr is not None
    start, end = yr
    import datetime
    today = datetime.date.today()
    assert end == today.year
    assert start == today.year - 5 + 1


def test_fallback_recent_n_years_chinese_numeral():
    """'近五年' with Chinese numeral should yield the same range."""
    yr, _ = _extract_constraints_fallback("近五年扩散模型进展")
    import datetime
    today = datetime.date.today()
    assert yr == (today.year - 5 + 1, today.year)


def test_fallback_min_count_phrasings():
    """'不少于20篇' / '至少20篇' / '20篇以上' should all yield min_count=20."""
    for msg in ("知识图谱综述，不少于20篇", "知识图谱综述，至少20篇", "知识图谱综述，20篇以上"):
        _, mc = _extract_constraints_fallback(msg)
        assert mc == 20, f"failed for: {msg}"


def test_fallback_no_constraints():
    """Plain query without constraints returns (None, None)."""
    yr, mc = _extract_constraints_fallback("扩散模型在药物发现中的最新进展")
    assert yr is None
    assert mc is None


def test_fallback_past_n_years_english():
    """'past 5 years' should yield range too."""
    yr, _ = _extract_constraints_fallback("knowledge graph survey, past 5 years")
    import datetime
    today = datetime.date.today()
    assert yr == (today.year - 5 + 1, today.year)


def test_intent_analyze_parses_llm_year_range_and_min_count():
    """LLM-returned year_range and min_count should flow into IntentResult."""
    fake_json = json.dumps({
        "intent": "search",
        "workflow_mode": "search",
        "confidence": 0.9,
        "reasoning": "user wants KG papers",
        "extracted_topic": "knowledge graph",
        "year_range": [2021, 2026],
        "min_count": 20,
    })
    with patch("src.agents.base.BaseAgent.invoke", return_value=fake_json):
        agent = IntentAgent()
        result = agent.analyze("最近5年知识图谱，不少于20篇")
    assert result.year_range == (2021, 2026)
    assert result.min_count == 20


def test_intent_analyze_falls_back_to_regex_when_llm_omits():
    """If LLM returns null for constraints, regex fallback fills them."""
    fake_json = json.dumps({
        "intent": "search",
        "workflow_mode": "search",
        "confidence": 0.9,
        "reasoning": "user wants KG papers",
        "extracted_topic": "knowledge graph",
        "year_range": None,
        "min_count": None,
    })
    with patch("src.agents.base.BaseAgent.invoke", return_value=fake_json):
        agent = IntentAgent()
        result = agent.analyze("最近5年知识图谱，不少于20篇")
    import datetime
    today = datetime.date.today()
    assert result.year_range == (today.year - 5 + 1, today.year)
    assert result.min_count == 20


def test_strategy_defaults_to_3_years_10_papers():
    """No user constraints → date range covers last 3 calendar years, max_results=10."""
    agent = RetrievalAgent()
    strategy = agent.generate_search_strategy(
        topic="diffusion models",
        key_concepts=["diffusion"],
        domain="computer_science",
        has_chinese=False,
    )
    today = datetime.date.today()
    expected_start = datetime.date(today.year - 3 + 1, 1, 1)
    assert strategy.date_range[0] == expected_start.strftime("%Y-%m-%d")
    assert strategy.max_results == 10
    assert strategy.year_range is None  # no explicit user range


def test_strategy_uses_user_year_range_and_min_count():
    """User-supplied year_range / min_count override defaults."""
    agent = RetrievalAgent()
    strategy = agent.generate_search_strategy(
        topic="knowledge graph",
        key_concepts=["KG"],
        domain="computer_science",
        has_chinese=False,
        year_range=(2021, 2026),
        min_count=20,
    )
    assert strategy.year_range == (2021, 2026)
    assert strategy.max_results == 20
    # date_range derived from year_range
    assert strategy.date_range[0] == "2021-01-01"


def test_execute_search_post_filters_by_year_range():
    """Papers outside year_range should be dropped after MCP returns them."""
    agent = RetrievalAgent()
    strategy = SearchStrategy(
        keywords=["kg"],
        boolean_query='("kg")',
        categories=[],
        date_range=("2021-01-01", "2026-12-31"),
        max_results=20,
        rationale="test",
        domain="computer_science",
        has_chinese=False,
        year_range=(2021, 2026),
    )

    fake_papers = [
        {"paper_id": "p1", "title": "in-range old", "published": "2021-06-01"},
        {"paper_id": "p2", "title": "in-range new", "published": "2025-03-01"},
        {"paper_id": "p3", "title": "out of range", "published": "2019-01-01"},
        {"paper_id": "p4", "title": "no date", "published": ""},
    ]

    with patch("src.agents.retrieval.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"papers": fake_papers}
        mock_post.return_value = mock_resp

        result = agent.execute_search(strategy)

    ids = [p["paper_id"] for p in result]
    # p3 (2019) dropped; p4 (no date) kept — can't filter without date
    assert "p1" in ids and "p2" in ids and "p4" in ids
    assert "p3" not in ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_llm_response(json_str: str) -> str:
    """Mock LLM invoke return: BaseAgent.invoke returns response.content (a str)."""
    return json_str


# ---------------------------------------------------------------------------
# E2E integration tests — user constraints flow from IntentAgent to RetrievalAgent
# ---------------------------------------------------------------------------

def test_e2e_user_constraints_flow_to_strategy():
    """IntentAgent + RetrievalAgent together: '最近5年...不少于20篇' -> strategy."""
    from src.agents.intent import IntentAgent, IntentType

    fake_json = json.dumps({
        "intent": "search",
        "workflow_mode": "search",
        "confidence": 0.95,
        "reasoning": "user wants KG survey",
        "extracted_topic": "knowledge graph",
        "year_range": [2021, 2026],
        "min_count": 20,
    })
    with patch("src.agents.base.BaseAgent.invoke", return_value=_fake_llm_response(fake_json)):
        intent = IntentAgent().analyze("最近5年知识图谱最新研究，不少于20篇")

    assert intent.year_range == (2021, 2026)
    assert intent.min_count == 20

    agent = RetrievalAgent()
    strategy = agent.generate_search_strategy(
        topic=intent.extracted_topic or "knowledge graph",
        key_concepts=[],
        domain="computer_science",
        has_chinese=True,
        year_range=intent.year_range,
        min_count=intent.min_count,
    )
    assert strategy.year_range == (2021, 2026)
    assert strategy.max_results == 20
    assert strategy.date_range[0] == "2021-01-01"


def test_e2e_no_constraints_uses_defaults():
    """Plain query -> no year_range, max_results=10, date range last 3 years."""
    from src.agents.intent import IntentAgent

    fake_json = json.dumps({
        "intent": "search", "workflow_mode": "search", "confidence": 0.9,
        "reasoning": "", "extracted_topic": "diffusion models",
        "year_range": None, "min_count": None,
    })
    with patch("src.agents.base.BaseAgent.invoke", return_value=_fake_llm_response(fake_json)):
        intent = IntentAgent().analyze("diffusion models survey")

    assert intent.year_range is None
    assert intent.min_count is None

    agent = RetrievalAgent()
    strategy = agent.generate_search_strategy(
        topic="diffusion models", key_concepts=[],
        domain="computer_science", has_chinese=False,
    )
    today = datetime.date.today()
    assert strategy.max_results == 10
    assert strategy.date_range[0] == datetime.date(today.year - 3 + 1, 1, 1).strftime("%Y-%m-%d")
