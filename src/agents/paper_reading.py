"""
Paper Reading Agent

单篇论文精读分析（区别于 reader.py 的批量阅读）。
集成PDF解析与LLM分析，支持四种阅读模式：
- snap: 30秒速览
- lens: 深度精读（公式、算法、实验）
- sphere: 研究全景（参考文献、主题）
- qa: 智能问答
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_config, get_llm_client
from src.tools.pdf_parser import PDFParser, ParserBackend, ParsedPaper

logger = logging.getLogger("paper_reading")


# ==================== Prompt 模板 ====================

SNAP_PROMPT_ZH = """你是一名科研论文分析助手。请基于提供的论文内容，生成"30秒速览"分析。

输出必须使用以下结构化Markdown格式：

## 一句话总结
用一句话概括：研究问题 + 方法 + 关键结果

## 核心贡献
- 3-5个要点，每条注明论文的具体贡献

## 关键实验发现
- 主要指标、提升幅度、对比结果

## 适用性与局限
- 适用场景：……
- 局限性：……

## 是否值得精读
给出建议（是/否）并简要说明理由

**注意**：
1. 简洁精确，这是分诊工具
2. 不得编造信息，只基于论文内容
3. 中文输出，技术术语保留英文
"""

SNAP_PROMPT_EN = """You are a paper analysis assistant. Generate a 30-second "Insight Snap" based on the paper content.

Use this structured Markdown format:

## One-Sentence Summary
(Problem + Method + Key Result in one sentence)

## Core Contributions
- 3-5 bullets

## Key Experimental Findings
- Main metrics, improvements, comparisons

## Applicability & Limitations
- Suitable for: ...
- Limitations: ...

## Worth Reading?
(Yes/No with justification)
"""

LENS_PROMPT_ZH = """你是一名资深科研论文深度精读助手。请基于提供的论文**原文内容**，进行细致深入的技术分析。

⚠️ 核心要求：
1. **必须引用原文** - 每个关键论点都要引用原文片段（使用 > 块引用）
2. **不得编造** - 所有内容必须来自论文原文，找不到的信息标注 "_论文未明确提及_"
3. **技术细节** - 提取具体数字、公式、算法步骤、超参数设置
4. **章节定位** - 标注信息来源章节，方便用户回溯

输出必须使用以下结构化Markdown格式：

# 深度精读报告

## 一、论文概览
- **标题**：[论文标题]
- **作者**：[作者列表]
- **核心研究问题**：用1-2句话精准概括

## 二、研究背景与动机
### 2.1 领域现状
说明该领域的研究现状（引用原文）：
> 引用原文片段

### 2.2 现有方法的不足
列出本文指出的现有方法的具体局限：
1. **不足1**：……（原文位置：[章节名]）
   > 引用原文
2. **不足2**：……

### 2.3 本文要解决的核心问题
- 问题1：……
- 问题2：……

## 三、方法论详解
### 3.1 整体框架
描述方法的总体设计思路（不少于100字）

### 3.2 核心创新点
逐一列出每个创新点，引用原文论述：
1. **创新点1**：……
   - 原理：……
   - 与现有方法的区别：……
   > 原文引用

2. **创新点2**：……

### 3.3 关键公式与算法
对论文中的核心公式逐一解析：

**公式1**：$$公式LaTeX$$
- 含义：……
- 各符号说明：
  - $x$：表示……
  - $y$：表示……
- 与现有方法的差异：……

**算法描述**（如有）：
```
算法步骤伪代码
```
- Step 1说明：……
- Step 2说明：……

### 3.4 模型架构
详细描述网络结构/模块组成（如有）：
- 输入：……
- 模块1（XX层）：作用是……
- 模块2（XX层）：作用是……
- 输出：……

## 四、实验设计与结果
### 4.1 数据集
| 数据集 | 规模 | 特点 | 用途 |
|--------|------|------|------|

### 4.2 评估指标
- 指标1：……（定义）
- 指标2：……

### 4.3 实验设置
- 超参数：……
- 训练细节：……
- 对比基线：……

### 4.4 主要实验结果
引用论文中的关键数字：

> 引用结果原文片段

**关键发现**：
1. 在XX数据集上，相比XX方法提升 **XX%**
2. ……

### 4.5 消融实验（如有）
- 消融模块1：……带来 **XX%** 提升
- 消融模块2：……

## 五、批判性思考
### 5.1 方法优势
基于原文及独立分析：
1. **优势1**：……
2. **优势2**：……

### 5.2 潜在局限
1. **局限1**（论文明确承认）：……
   > 原文引用
2. **局限2**（独立分析推断）：……

### 5.3 改进与扩展方向
- 方向1：……
- 方向2：……

## 六、复现要点
若要复现本工作，需注意：
1. **数据准备**：……
2. **关键超参**：……
3. **常见陷阱**：……

## 七、一句话总结
（用一句话精准概括论文核心贡献，便于记忆）

---
**注意事项**：
- 所有引用使用 > 块引用，并标注章节来源
- LaTeX格式：行内$x$，独立$$x$$
- 数值结果保留原文精度
- 不得用"该方法"等模糊表述，要具体到方法名
- 中文输出，技术术语首次出现时保留英文，如"Transformer（变换器）"
"""

LENS_PROMPT_EN = """You are a paper analysis assistant. Provide deep technical analysis of the paper.

Use this structured Markdown format:

## 1. Background & Motivation
- Gaps in existing methods
- Core problem addressed

## 2. Methodology
### Core Idea
### Key Formulas/Algorithms
(use LaTeX: $inline$ or $$display$$)
### Model Architecture

## 3. Experiments & Results
### Datasets
### Evaluation Metrics
### Main Results

## 4. Critical Analysis
### Strengths
### Limitations & Future Work
"""

SPHERE_PROMPT_ZH = """你是一名科研论文研究全景分析助手。请基于论文内容，生成研究全景分析。

输出必须使用以下结构化Markdown格式：

## 一、研究领域定位
本文在研究领域中的位置

## 二、技术演进脉络
从历史到本文的技术发展路线

## 三、相关工作聚类
按主题对相关工作进行聚类分析

## 四、与代表性工作对比
| 工作 | 方法 | 优势 | 不足 |
|------|------|------|------|

## 五、研究空白与机会
- 未解决的问题
- 潜在研究方向

## 六、推荐阅读路径
- 入门必读：[相关工作]
- 进阶阅读：[相关工作]

**注意**：基于论文中提到的参考文献和相关工作进行分析
"""

SPHERE_PROMPT_EN = """You are a research landscape analysis assistant. Generate a comprehensive research sphere analysis.

Use this structured Markdown format:

## 1. Research Field Position
## 2. Technical Evolution
## 3. Related Work Clusters
## 4. Comparison with Representative Works
## 5. Research Gaps & Opportunities
## 6. Recommended Reading Path
"""

QA_PROMPT_ZH = """你是一名论文问答助手。请基于论文内容，提供常见问题的答案。

输出必须使用以下Markdown格式：

## Q1: 这篇论文要解决什么问题？
答：……

## Q2: 论文提出了什么方法？
答：……

## Q3: 方法的核心创新点是什么？
答：……

## Q4: 实验结果如何？
答：……

## Q5: 这个方法有什么局限？
答：……

## Q6: 未来可以怎么改进？
答：……

**注意**：基于论文内容回答，不编造信息
"""

QA_PROMPT_EN = """You are a Q/A assistant for academic papers.

Use this Markdown format:

## Q1: What problem does this paper solve?
## Q2: What method is proposed?
## Q3: What are the core innovations?
## Q4: What are the experimental results?
## Q5: What are the limitations?
## Q6: How can it be improved?
"""


def get_prompt(mode: str, language: str = "zh") -> str:
    """获取对应模式和语言的Prompt"""
    prompts = {
        "snap": (SNAP_PROMPT_ZH, SNAP_PROMPT_EN),
        "lens": (LENS_PROMPT_ZH, LENS_PROMPT_EN),
        "sphere": (SPHERE_PROMPT_ZH, SPHERE_PROMPT_EN),
        "qa": (QA_PROMPT_ZH, QA_PROMPT_EN),
    }
    zh, en = prompts.get(mode, prompts["snap"])
    return zh if language == "zh" else en


def build_paper_context(parsed: ParsedPaper, mode: str = "snap", max_chars: int = 12000) -> str:
    """构建论文上下文。

    根据精读模式调整截取策略：
    - snap: 12K字符，仅摘要+关键章节
    - lens: 24K字符，包含方法/实验完整内容
    - sphere: 18K字符，包含相关工作+参考文献
    - qa: 15K字符，平衡覆盖
    """
    # 按模式调整上下文长度
    mode_chars = {"snap": 12000, "lens": 24000, "sphere": 18000, "qa": 15000}
    max_chars = mode_chars.get(mode, max_chars)

    parts = []

    if parsed.title:
        parts.append(f"# 论文标题\n{parsed.title}\n")

    if parsed.authors:
        parts.append(f"# 作者\n{', '.join(parsed.authors)}\n")

    if parsed.abstract:
        parts.append(f"# 摘要\n{parsed.abstract}\n")

    # 按模式确定关键章节关键词
    if mode == "lens":
        # Lens模式：聚焦方法、实验、结果
        key_section_keywords = [
            "introduction", "method", "approach", "model", "architecture",
            "algorithm", "framework", "design", "implementation",
            "experiment", "result", "evaluation", "ablation",
            "discussion", "conclusion", "analysis",
        ]
        # 每章节保留更多内容
        section_max = 5000
    elif mode == "sphere":
        # Sphere模式：聚焦相关工作和参考文献
        key_section_keywords = [
            "introduction", "related work", "background", "literature",
            "discussion", "conclusion",
        ]
        section_max = 3500
    else:
        key_section_keywords = [
            "introduction", "method", "approach", "model",
            "experiment", "result", "evaluation", "conclusion",
            "discussion", "related work"
        ]
        section_max = 3000

    if parsed.sections:
        parts.append("# 主要章节原文\n")
        for name, content in parsed.sections.items():
            name_lower = name.lower()
            if any(kw in name_lower for kw in key_section_keywords):
                section_content = content[:section_max] if len(content) > section_max else content
                parts.append(f"## 章节：{name}\n{section_content}\n")

    # 如果没有提取到章节，使用raw_text的前部分
    if not parsed.sections and parsed.raw_text:
        parts.append(f"# 论文内容\n{parsed.raw_text[:max_chars]}\n")

    # Sphere模式：附加参考文献样本
    if mode == "sphere" and parsed.references:
        parts.append("# 参考文献（前20条）\n")
        for i, ref in enumerate(parsed.references[:20], 1):
            ref_text = ref if isinstance(ref, str) else str(ref)
            parts.append(f"[{i}] {ref_text[:300]}")

    context = "\n".join(parts)
    if len(context) > max_chars:
        context = context[:max_chars] + "\n\n[... 内容已截断 ...]"

    return context


PAPER_READING_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "paper_reading"


def _cache_path(paper_id: str, mode: str, language: str) -> Path:
    """精读结果缓存路径：data/paper_reading/{paper_id}/{mode}_{language}.json"""
    return PAPER_READING_DIR / paper_id / f"{mode}_{language}.json"


def load_cached_result(paper_id: str, mode: str, language: str) -> Optional[Dict[str, Any]]:
    """读取已缓存的精读结果，没有则返回None"""
    cache_file = _cache_path(paper_id, mode, language)
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"命中缓存: {cache_file}")
        return data
    except Exception as e:
        logger.warning(f"缓存读取失败: {cache_file}, {e}")
        return None


def save_result(paper_id: str, mode: str, language: str, result: Dict[str, Any]) -> None:
    """保存精读结果到缓存"""
    cache_file = _cache_path(paper_id, mode, language)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"精读结果已保存: {cache_file}")
    except Exception as e:
        logger.error(f"保存缓存失败: {cache_file}, {e}")


def analyze_paper(
    pdf_path: str,
    paper_id: str,
    mode: str = "snap",
    language: str = "zh",
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    分析论文

    Args:
        pdf_path: PDF文件路径（绝对路径）
        paper_id: 论文ID
        mode: 阅读模式 (snap/lens/sphere/qa)
        language: 输出语言 (zh/en)
        use_cache: 是否使用缓存（默认True，重复分析直接读缓存）

    Returns:
        dict with markdown and json fields
    """
    logger.info(f"开始分析论文: paper_id={paper_id}, mode={mode}, pdf_path={pdf_path}")

    # 0. 检查缓存
    if use_cache:
        cached = load_cached_result(paper_id, mode, language)
        if cached:
            cached["from_cache"] = True
            return cached

    # 1. 解析PDF
    parser = PDFParser(backend=ParserBackend.PYMUPDF)
    try:
        parsed = parser.parse(pdf_path, paper_id, extract_sections=True)
        logger.info(f"PDF解析完成: title={parsed.title[:80] if parsed.title else 'N/A'}, "
                    f"sections={len(parsed.sections)}, words={parsed.word_count}")
    except Exception as e:
        logger.error(f"PDF解析失败: {e}")
        return {
            "markdown": f"# 解析失败\n\nPDF解析出错: {str(e)}",
            "json": json.dumps({"error": str(e)}, ensure_ascii=False),
            "error": str(e),
        }

    # 2. 构建上下文（根据模式调整长度和侧重点）
    context = build_paper_context(parsed, mode=mode)
    logger.info(f"上下文构建完成: mode={mode}, {len(context)}字符")

    # 3. 调用LLM
    system_prompt = get_prompt(mode, language)
    user_prompt = "请基于以下论文内容进行分析：\n\n" + context if language == "zh" \
                  else "Please analyze the following paper:\n\n" + context

    try:
        config = get_config()
        llm = get_llm_client(config)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        markdown = response.content
        used_llm = True
        logger.info(f"LLM分析完成: {len(markdown)}字符")
    except Exception as e:
        logger.error(f"LLM调用失败: {e}")
        # 降级到基础分析（基于解析内容）
        markdown = _fallback_analysis(parsed, mode, language)
        used_llm = False

    result = {
        "markdown": markdown,
        "json": json.dumps({
            "mode": mode,
            "paper_id": paper_id,
            "title": parsed.title,
            "authors": parsed.authors,
            "language": language,
            "word_count": parsed.word_count,
            "sections_count": len(parsed.sections),
        }, ensure_ascii=False),
        "from_cache": False,
    }

    # 保存结果（仅当LLM成功调用时才缓存，fallback结果不缓存）
    if used_llm:
        save_result(paper_id, mode, language, result)

    return result


def _fallback_analysis(parsed: ParsedPaper, mode: str, language: str) -> str:
    """LLM不可用时的降级分析 - 基于PDF解析结果构建结构化报告"""
    lines = []
    lines.append(f"# {parsed.title or '论文分析'}\n")

    if parsed.authors:
        lines.append(f"**作者**: {', '.join(parsed.authors)}\n")

    if parsed.abstract:
        lines.append(f"## 摘要\n\n> {parsed.abstract}\n")

    if mode == "snap":
        lines.append("## 论文速览\n")
        lines.append(f"| 指标 | 数值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 总字数 | {parsed.word_count} |")
        lines.append(f"| 章节数 | {len(parsed.sections)} |")
        lines.append(f"| 参考文献数 | {len(parsed.references)} |")
        lines.append(f"| 表格数 | {len(parsed.tables)} |")
        lines.append(f"| 图片数 | {len(parsed.figures)} |\n")

        if parsed.sections:
            lines.append("## 主要章节\n")
            for name in list(parsed.sections.keys())[:10]:
                lines.append(f"- {name}")
            lines.append("")

    elif mode == "lens":
        # Lens模式：详细的章节内容展示
        lines.append("## 一、论文结构概览\n")
        lines.append(f"本论文包含 **{len(parsed.sections)}** 个主要章节，共 **{parsed.word_count}** 字。\n")

        if parsed.sections:
            lines.append("**章节列表**：")
            for i, name in enumerate(parsed.sections.keys(), 1):
                lines.append(f"{i}. {name}")
            lines.append("")

        # 方法章节
        method_keywords = ["method", "approach", "model", "architecture", "framework", "algorithm"]
        method_sections = {
            name: content for name, content in parsed.sections.items()
            if any(kw in name.lower() for kw in method_keywords)
        }
        if method_sections:
            lines.append("## 二、方法论原文摘录\n")
            for name, content in list(method_sections.items())[:3]:
                preview = content[:2000] + "\n\n[... 更多内容请查看原文 ...]" if len(content) > 2000 else content
                lines.append(f"### {name}\n")
                lines.append(f"> {preview}\n")

        # 实验章节
        exp_keywords = ["experiment", "result", "evaluation", "ablation"]
        exp_sections = {
            name: content for name, content in parsed.sections.items()
            if any(kw in name.lower() for kw in exp_keywords)
        }
        if exp_sections:
            lines.append("## 三、实验设计与结果原文\n")
            for name, content in list(exp_sections.items())[:3]:
                preview = content[:1500] + "\n\n[... 更多内容请查看原文 ...]" if len(content) > 1500 else content
                lines.append(f"### {name}\n")
                lines.append(f"> {preview}\n")

        # 结论章节
        concl_keywords = ["conclusion", "discussion", "summary"]
        concl_sections = {
            name: content for name, content in parsed.sections.items()
            if any(kw in name.lower() for kw in concl_keywords)
        }
        if concl_sections:
            lines.append("## 四、结论与讨论原文\n")
            for name, content in list(concl_sections.items())[:2]:
                preview = content[:1000] + "..." if len(content) > 1000 else content
                lines.append(f"### {name}\n")
                lines.append(f"> {preview}\n")

        # 表格图片信息
        if parsed.tables or parsed.figures:
            lines.append("## 五、表格与图片\n")
            if parsed.tables:
                lines.append(f"**表格数**: {len(parsed.tables)}")
            if parsed.figures:
                lines.append(f"**图片数**: {len(parsed.figures)}")
            lines.append("")

    elif mode == "sphere":
        lines.append("## 一、论文基本信息\n")
        lines.append(f"- 标题：{parsed.title}")
        lines.append(f"- 参考文献总数：**{len(parsed.references)}**\n")

        # 相关工作章节
        related_keywords = ["related work", "background", "introduction"]
        related_sections = {
            name: content for name, content in parsed.sections.items()
            if any(kw in name.lower() for kw in related_keywords)
        }
        if related_sections:
            lines.append("## 二、相关工作原文\n")
            for name, content in list(related_sections.items())[:2]:
                preview = content[:2000] + "..." if len(content) > 2000 else content
                lines.append(f"### {name}\n")
                lines.append(f"> {preview}\n")

        if parsed.references:
            lines.append(f"## 三、参考文献（前20条）\n")
            for i, ref in enumerate(parsed.references[:20], 1):
                ref_text = ref if isinstance(ref, str) else str(ref)
                lines.append(f"{i}. {ref_text[:200]}")
            lines.append("")

    elif mode == "qa":
        lines.append("## Q: 论文章节有哪些？\n")
        if parsed.sections:
            for i, name in enumerate(parsed.sections.keys(), 1):
                lines.append(f"{i}. {name}")
        lines.append("")
        lines.append("## Q: 论文摘要说了什么？\n")
        if parsed.abstract:
            lines.append(f"> {parsed.abstract}\n")

    lines.append("\n---")
    lines.append("⚠️ **注意**：LLM服务不可用（API订阅已过期或网络不可达），以上为基于PDF解析的原文摘录。请更新API密钥后重新分析以获得AI生成的深度分析结果。")

    return "\n".join(lines)
