"""Tests for user-specified retrieval constraints (year range, min count)."""
import json
from unittest.mock import patch

from src.agents.intent import IntentAgent, _extract_constraints_fallback


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
