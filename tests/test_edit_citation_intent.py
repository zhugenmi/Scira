from src.mcp.server import (
    CitationIntent, _detect_citation_intent, _resolve_topic, _is_confirmation,
)


def test_detect_hit_chinese_keyword():
    r = _detect_citation_intent("帮我增加5篇参考文献")
    assert r is not None
    assert r.count == 5


def test_detect_hit_english_keyword():
    r = _detect_citation_intent("add 3 references about RAG")
    assert r is not None
    assert r.count == 3


def test_detect_default_count():
    r = _detect_citation_intent("补一些引用")
    assert r is not None
    assert r.count == 5  # 默认


def test_detect_topic_hint():
    r = _detect_citation_intent("加5篇关于大模型相关的参考文献")
    assert r is not None
    assert r.topic_hint == "大模型"


def test_detect_miss():
    assert _detect_citation_intent("把摘要改短一点") is None


def test_resolve_topic_from_hint():
    intent = CitationIntent(count=5, topic_hint="扩散模型")
    assert _resolve_topic(intent, "# RAG综述\n...", {}) == "扩散模型"


def test_resolve_topic_from_report_title():
    intent = CitationIntent(count=5, topic_hint=None)
    working = "# RAG最新进展\n\n## 摘要\n..."
    assert _resolve_topic(intent, working, {}) == "RAG最新进展"


def test_resolve_topic_from_session_topics():
    intent = CitationIntent(count=5, topic_hint=None)
    assert _resolve_topic(intent, "no title here", {"research_topics": ["X", "Y"]}) == "Y"


def test_resolve_topic_fallback_message_prefix():
    intent = CitationIntent(count=5, topic_hint=None)
    assert _resolve_topic(intent, "", {}) == ""  # 无任何来源返回空串


def test_is_confirmation_yes():
    assert _is_confirmation("用这些") is True
    assert _is_confirmation("就用这些吧") is True
    assert _is_confirmation("可以") is True
    assert _is_confirmation("yes") is True


def test_is_confirmation_no():
    assert _is_confirmation("换一批") is False
    assert _is_confirmation("不要") is False
