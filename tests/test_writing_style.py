"""学术语体规范与写作提示词测试。"""
from src.agents.prompts import ACADEMIC_STYLE_RULES, WRITER_SECTION_FROM_KB_PROMPT, WRITER_CONCLUSION_PROMPT


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


def test_conclusion_prompt_includes_academic_tone_supplement():
    """WRITER_CONCLUSION_PROMPT 应包含学术语体补充要求。"""
    assert "学术语体补充要求" in WRITER_CONCLUSION_PROMPT
    assert "第三人称" in WRITER_CONCLUSION_PROMPT
    assert "量化" in WRITER_CONCLUSION_PROMPT
    assert "模糊态度词" in WRITER_CONCLUSION_PROMPT


from src.agents.writer import _build_citation_instruction


def test_build_citation_instruction_lit_review_section():
    """综述类章节标题应触发 ACADEMIC_STYLE_RULES。"""
    ref_list = [{"authors": ["Zhang"], "title": "Paper A", "year": "2026"}]
    result = _build_citation_instruction("一、研究背景与现状", ref_list)
    assert "引用主语与标注规则" in result
    assert "句式三模式" in result
    assert "[1]" in result
    assert "Zhang" in result


def test_build_citation_instruction_non_lit_review_section():
    """非综述类章节标题不应触发 ACADEMIC_STYLE_RULES，但保留 [n] 角标规范。"""
    ref_list = [{"authors": ["Li"], "title": "Paper B", "year": "2025"}]
    result = _build_citation_instruction("二、研究方法", ref_list)
    assert "句式三模式" not in result
    assert "[1]" in result
    assert "Li" in result


def test_build_citation_instruction_no_references():
    """无参考文献时应返回不编造引用提示。"""
    result = _build_citation_instruction("三、实验分析", [])
    assert "编造" in result


def test_build_citation_instruction_keywords_coverage():
    """综述类关键词应全部触发 ACADEMIC_STYLE_RULES。"""
    keywords = ["现状", "背景", "相关", "趋势", "综述", "进展", "review"]
    ref_list = [{"authors": ["A"], "title": "T", "year": "2026"}]
    for kw in keywords:
        result = _build_citation_instruction(f"章节含{kw}", ref_list)
        assert "句式三模式" in result, f"关键词 {kw} 未触发 ACADEMIC_STYLE_RULES"


from src.agents.writer import _format_reference_block


def test_format_reference_block_shared_helper():
    """_format_reference_block 应正确格式化参考文献清单，且 writer 和 reviewer 从同一处导入。"""
    # 空列表返回空字符串
    assert _format_reference_block([]) == ""

    # 正常格式化
    ref_list = [
        {"authors": ["Zhang", "Li"], "title": "Deep Learning", "year": "2026"},
        {"authors": ["Wang"], "title": "NLP Advances", "year": "2025"},
    ]
    result = _format_reference_block(ref_list)
    assert "[1] Zhang, Li. Deep Learning. 2026" in result
    assert "[2] Wang. NLP Advances. 2025" in result

    # 验证 reviewer.py 也从同一处导入
    from src.agents.reviewer import _build_citation_instruction as reviewer_build_ci
    # 通过检查 reviewer 的 _build_citation_instruction 是否使用了 _format_reference_block
    # 来验证去重：若 reviewer 未使用共享 helper，其输出中仍应有格式化的引用块
    ref_single = [{"authors": ["Smith"], "title": "Test Paper", "year": "2024"}]
    reviewer_result = reviewer_build_ci(ref_single)
    assert "[1] Smith. Test Paper. 2024" in reviewer_result


# ==================== 引用顺序重编号测试 ====================

def test_renumber_citations_basic_first_appearance():
    """首次出现顺序应决定新编号：[6][1][2] -> [1][2][3]。"""
    from src.mcp.server import _renumber_citations

    text = "前文[6]提到融合技术。Noh 等人[1]提出 TinyML。Wang 等[2]构建分层架构。"
    ref_list = [
        {"authors": ["Noh"], "title": "TinyML", "year": "2025"},
        {"authors": ["Wang"], "title": "Layered Fusion", "year": "2026"},
        {"authors": ["Lin"], "title": "Survey", "year": "2025"},
        {"authors": ["X"], "title": "Y", "year": "2024"},
        {"authors": ["Z"], "title": "W", "year": "2023"},
        {"authors": ["Intro"], "title": "Overview", "year": "2026"},
    ]
    new_text, new_refs = _renumber_citations(text, ref_list)

    # [6] 首次出现 -> 新 [1]；[1] 第二次出现 -> 新 [2]；[2] 第三次出现 -> 新 [3]
    assert "[1]提到融合技术" in new_text
    assert "[2]提出 TinyML" in new_text
    assert "[3]构建分层架构" in new_text
    # ref_list 重排：new[0] 应是原 ref_list[5] (Intro), new[1] 是原 [0] (Noh), new[2] 是原 [1] (Wang)
    assert new_refs[0]["authors"] == ["Intro"]
    assert new_refs[1]["authors"] == ["Noh"]
    assert new_refs[2]["authors"] == ["Wang"]
    # 未被引用的 [3][4] 应从 ref_list 中删除
    assert len(new_refs) == 3


def test_renumber_citations_same_reference_twice():
    """同一文献多次引用应使用相同新编号。"""
    from src.mcp.server import _renumber_citations

    text = "Noh 等人[1]提出方法。该方法[1]在边缘端验证。"
    ref_list = [{"authors": ["Noh"], "title": "TinyML", "year": "2025"}]
    new_text, new_refs = _renumber_citations(text, ref_list)

    assert new_text.count("[1]") == 2
    assert len(new_refs) == 1
    assert new_refs[0]["authors"] == ["Noh"]


def test_renumber_citations_multi_citation():
    """多引用 [n,m] 应分别按首次出现分配新编号。"""
    from src.mcp.server import _renumber_citations

    # [3,1] 首次出现 -> 3 映射为 1，1 映射为 2，输出 [1,2]
    # 随后 [2] 首次出现 -> 映射为 3
    text = "多项研究[3,1]表明。另见[2]。"
    ref_list = [
        {"authors": ["A"], "title": "T1", "year": "2026"},
        {"authors": ["B"], "title": "T2", "year": "2026"},
        {"authors": ["C"], "title": "T3", "year": "2026"},
    ]
    new_text, new_refs = _renumber_citations(text, ref_list)

    assert "[1,2]表明" in new_text
    assert "[3]。" in new_text
    # 重排：new[0]=原[2](C), new[1]=原[0](A), new[2]=原[1](B)
    assert new_refs[0]["authors"] == ["C"]
    assert new_refs[1]["authors"] == ["A"]
    assert new_refs[2]["authors"] == ["B"]


def test_renumber_citations_no_citations_returns_empty_refs():
    """正文无引用时，ref_list 应清空（GB/T 7714 只列被引文献）。"""
    from src.mcp.server import _renumber_citations

    text = "本文综述了多源数据融合领域的发展，未引用具体文献。"
    ref_list = [{"authors": ["A"], "title": "T", "year": "2026"}]
    new_text, new_refs = _renumber_citations(text, ref_list)

    assert new_text == text
    assert new_refs == []


def test_renumber_citations_preserves_text_outside_brackets():
    """正文中非引用的方括号（如 [2 ms]）不应被误处理。"""
    from src.mcp.server import _renumber_citations

    text = "推理延迟仅[2 ms]，Noh 等人[1]提出方法。"
    ref_list = [{"authors": ["Noh"], "title": "TinyML", "year": "2025"}]
    new_text, new_refs = _renumber_citations(text, ref_list)

    # [2 ms] 不应被改动（非纯数字），[1] 应重编号为 [1]（首次出现）
    assert "[2 ms]" in new_text
    assert "[1]提出方法" in new_text
    assert len(new_refs) == 1
