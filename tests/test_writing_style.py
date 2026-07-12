"""学术语体规范与写作提示词测试。"""
from src.agents.prompts import ACADEMIC_STYLE_RULES


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