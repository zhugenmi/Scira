"""学术语体规范与写作提示词测试。"""
from src.agents.prompts import ACADEMIC_STYLE_RULES, WRITER_SECTION_FROM_KB_PROMPT


def test_academic_style_rules_exists():
    """ACADEMIC_STYLE_RULES 常量应存在且为非空字符串。"""
    assert isinstance(ACADEMIC_STYLE_RULES, str)
    assert len(ACADEMIC_STYLE_RULES) > 500


def test_academic_style_rules_contains_key_sections():
    """ACADEMIC_STYLE_RULES 应包含七节关键标题。"""
    required_sections = [
        "引用主语与标注规则",
        "句式三模式",
        "强制聚类与逻辑衔接",
        "学术语言基调",
        "发展趋势分析专项规则",
        "完整示范段落",
        "最终自检清单",
    ]
    for section in required_sections:
        assert section in ACADEMIC_STYLE_RULES, f"缺少章节: {section}"


def test_academic_style_rules_no_unescaped_braces():
    """ACADEMIC_STYLE_RULES 不得含未转义花括号，避免 .format() 报错。"""
    assert "{" not in ACADEMIC_STYLE_RULES
    assert "}" not in ACADEMIC_STYLE_RULES


def test_section_from_kb_prompt_includes_academic_style_rules():
    """WRITER_SECTION_FROM_KB_PROMPT 应包含 ACADEMIC_STYLE_RULES 全文。"""
    assert "引用主语与标注规则" in WRITER_SECTION_FROM_KB_PROMPT
    assert "句式三模式" in WRITER_SECTION_FROM_KB_PROMPT
    assert "发展趋势分析专项规则" in WRITER_SECTION_FROM_KB_PROMPT
    assert "完整示范段落" in WRITER_SECTION_FROM_KB_PROMPT


def test_section_from_kb_prompt_still_formats_correctly():
    """WRITER_SECTION_FROM_KB_PROMPT 应仍能被 format() 正确填充。"""
    result = WRITER_SECTION_FROM_KB_PROMPT.format(
        section_topic="国内外研究现状",
        n=5,
        constraints_line="无特殊约束",
        papers_context="论文上下文示例",
        reference_block="[1] 作者. 题目. 2026",
    )
    assert "国内外研究现状" in result
    assert "5" in result
    assert "论文上下文示例" in result
    assert "[1] 作者. 题目. 2026" in result
    assert "引用主语与标注规则" in result