import json
from unittest.mock import MagicMock

from src.tools.paper_info_extractor import PaperInfoExtractor


def test_extract_valid_json():
    """正常 LLM 返回 JSON 应正确解析。"""
    valid_json = json.dumps({
        "title": "Attention Is All You Need",
        "title_zh": None,
        "title_en": "Attention Is All You Need",
        "authors": ["Ashish Vaswani (Google Brain)"],
        "abstract": "The dominant sequence transduction models...",
        "keywords": ["transformer", "attention"],
        "doi": "10.1000/xyz",
        "journal": "NeurIPS",
        "year": 2017,
        "volume": "30",
        "issue": None,
        "pages": "5998-6008",
    })

    class MockResponse:
        content = valid_json
        usage_metadata = {"input_tokens": 100, "output_tokens": 50}

    class MockLLM:
        def invoke(self, messages, **kwargs):
            return MockResponse()

    extractor = PaperInfoExtractor()
    extractor.llm = MockLLM()

    result = extractor.extract("Attention Is All You Need\nAshish Vaswani...")
    assert result["title"] == "Attention Is All You Need"
    assert result["doi"] == "10.1000/xyz"
    assert result["metadata_quality"] == "llm_extracted"


def test_extract_invalid_json_retry():
    """LLM 返回非法 JSON 应重试一次。"""
    call_count = [0]

    class BadThenGoodLLM:
        def invoke(self, messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(content="not valid json {{{", usage_metadata={})
            else:
                return MagicMock(
                    content=json.dumps({"title": "Test", "authors": [], "abstract": ""}),
                    usage_metadata={},
                )

    extractor = PaperInfoExtractor()
    extractor.llm = BadThenGoodLLM()
    result = extractor.extract("some text")
    assert call_count[0] == 2
    assert result["metadata_quality"] == "llm_extracted"


def test_extract_json_retry_exhausted():
    """两次尝试都失败应返回默认值。"""
    class AlwaysBadLLM:
        def invoke(self, messages, **kwargs):
            return MagicMock(content="garbage {{{", usage_metadata={})

    extractor = PaperInfoExtractor()
    extractor.llm = AlwaysBadLLM()
    result = extractor.extract("some text")
    assert result["title"] == ""
    assert result["metadata_quality"] == "partial"


def test_parse_response_strips_markdown_code_block():
    """_parse_response 应能去除 markdown 代码块包裹。"""
    extractor = PaperInfoExtractor()
    raw = '```json\n{"title": "Test", "authors": [], "abstract": ""}\n```'
    result = extractor._parse_response(raw)
    assert result["title"] == "Test"
