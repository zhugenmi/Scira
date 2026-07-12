"""
Scira Writer Agent

Implements paper writing:
- Outline generation
- Section-by-section writing
- Parallel chapter generation using Send API
"""

import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_config, get_llm_client, SciraConfig
from src.utils.logger import record_token_usage
from src.agents.prompts import (
    WRITER_OUTLINE_PROMPT,
    WRITER_SECTION_PROMPT,
    WRITER_ABSTRACT_PROMPT,
    WRITER_INTRO_PROMPT,
    WRITER_CONCLUSION_PROMPT,
    WRITER_SYSTEM,
    ACADEMIC_STYLE_RULES,
)

# 综述类章节关键词：标题含这些词的章节应用完整 ACADEMIC_STYLE_RULES
LIT_REVIEW_KEYWORDS = ("现状", "背景", "相关", "趋势", "综述", "进展", "review")


@dataclass
class PaperSection:
    """Single paper section."""
    section_id: str
    title: str
    content: str = ""
    subsections: List[str] = field(default_factory=list)
    key_points: List[str] = field(default_factory=list)
    word_count: int = 0
    status: str = "pending"  # pending, writing, completed, failed
    references: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class PaperOutline:
    """Complete paper outline."""
    title: str
    abstract_requirements: str  # What abstract should cover
    sections: List[PaperSection]
    total_estimated_words: int
    writing_style: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WritingResult:
    """Complete writing result."""
    outline: PaperOutline
    sections: Dict[str, PaperSection]
    completed_sections: int
    failed_sections: int
    total_words: int
    paper_content: str  # Combined content without abstract/intro/conclusion


def _build_citation_instruction(section_title: str, reference_list: list) -> str:
    """根据章节标题类型构造引用指令。

    综述类章节（标题含 LIT_REVIEW_KEYWORDS）：用 ACADEMIC_STYLE_RULES 替换原引用要求。
    非综述类章节：保留简化版 [n] 角标规范。
    无参考文献：返回不编造引用提示。

    Args:
        section_title: 章节标题，用于判断是否为综述类
        reference_list: 参考文献清单，每项含 authors/title/year

    Returns:
        拼接好的 citation_instruction 字符串，追加到 WRITER_SECTION_PROMPT 之后
    """
    if not reference_list:
        return (
            "\n\n# 参考文献引用要求\n"
            "本次没有可用的参考文献清单。不要在正文中编造任何引用或角标，"
            "仅基于已知信息客观陈述，参考文献目录将由系统留空。\n"
        )

    ref_lines = []
    for i, r in enumerate(reference_list, 1):
        authors = r.get("authors") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        author_str = ", ".join(authors[:3]) + (", 等" if len(authors) > 3 else "") if authors else "佚名"
        year = r.get("year", "")
        ref_lines.append(f"[{i}] {author_str}. {r.get('title','')}. {year}")
    reference_block = "\n".join(ref_lines)

    is_lit_review = any(kw in section_title for kw in LIT_REVIEW_KEYWORDS)
    if is_lit_review:
        return (
            "\n\n" + ACADEMIC_STYLE_RULES +
            f"\n\n# 参考文献清单（仅可引用这些）\n{reference_block}\n"
        )

    return (
        "\n\n# 参考文献引用要求（非常重要，必须严格遵守）\n"
        "下方提供了带编号的参考文献清单。这些文献全部来自系统实际检索/知识库，"
        "你不得自行编造任何清单之外的文献。\n"
        "撰写正文时，凡涉及某篇论文的方法、观点或结论，必须在对应处用方括号角标引用，"
        "例如「张三等人提出了XXX方法[1]」「相关工作表明[2,3]」。\n"
        "- 角标数字必须严格对应清单序号，严禁使用清单中不存在的编号。\n"
        "- 不得使用其他引用样式（如 (Author, Year)），统一使用 [n] 形式。\n"
        "- 若某论点无法对应到清单中任何一篇文献，则不写角标，绝不编造引用。\n"
        "- 参考文献目录将由系统自动生成（GB/T 7714-2015 格式），你只需在正文使用 [n] 角标，不要重复列出参考文献。\n"
        f"\n参考文献清单（仅可引用这些）：\n{reference_block}\n"
    )


class WriterAgent:
    """
    Writer Agent for paper writing.

    Responsibilities:
    1. Generate paper outline from analysis
    2. Write sections one by one or in parallel
    3. Maintain consistency across sections
    """

    def __init__(self, config: Optional[SciraConfig] = None):
        """Initialize Writer Agent."""
        self.config = config or get_config()
        self.llm = get_llm_client(self.config)

    def generate_outline(
        self,
        global_knowledge: Dict[str, Any],
        topic: str,
    ) -> PaperOutline:
        """
        Generate paper outline from analysis.

        Args:
            global_knowledge: Analysis result from AnalyzerAgent
            topic: Research topic

        Returns:
            PaperOutline object
        """
        knowledge_json = json.dumps(global_knowledge, indent=2, ensure_ascii=False)

        # Use the template prompt
        prompt = WRITER_OUTLINE_PROMPT.format(
            topic=topic,
            global_knowledge=knowledge_json
        )

        messages = [
            SystemMessage(content=WRITER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        response = self.llm.invoke(messages)
        record_token_usage(response, self.config.model.model_name or "gpt-4o")
        return self._parse_outline(response.content, topic)

    def _parse_outline(self, response: str, topic: str) -> PaperOutline:
        """Parse outline from LLM response."""
        import re

        match = re.search(r'\{[\s\S]*\}', response)
        if not match:
            # Return default outline
            return self._default_outline(topic)

        try:
            data = json.loads(match.group())

            sections = []
            for s in data.get("sections", []):
                # 过滤引言和结论章节，这些由审稿专家后置生成
                title = s.get("title", "Untitled")
                if any(kw in title for kw in ["引言", "绪论", "前言", "结论", "总结"]):
                    continue
                section = PaperSection(
                    section_id=s.get("section_id", f"section_{len(sections)+1}"),
                    title=title,
                    subsections=s.get("subsections", []),
                    key_points=s.get("key_points", []),
                )
                sections.append(section)

            return PaperOutline(
                title=data.get("title", topic),
                abstract_requirements=data.get("abstract_requirements", ""),
                sections=sections,
                total_estimated_words=data.get("total_estimated_words", 5000),
                writing_style=data.get("writing_style", "Academic"),
            )

        except json.JSONDecodeError:
            return self._default_outline(topic)

    def _default_outline(self, topic: str) -> PaperOutline:
        """Create default outline structure. 引言和结论由审稿专家生成，不包含在此。"""
        return PaperOutline(
            title=f"{topic} 研究报告",
            abstract_requirements="研究背景、研究问题、核心方法、主要发现、关键贡献",
            sections=[
                PaperSection(section_id="background", title="一、研究背景与现状"),
                PaperSection(section_id="methods", title="二、研究方法"),
                PaperSection(section_id="experiments", title="三、实验与分析"),
                PaperSection(section_id="results", title="四、结果与讨论"),
                PaperSection(section_id="future", title="五、未来研究方向"),
            ],
            total_estimated_words=5000,
            writing_style="学术风格",
        )

    def write_section(
        self,
        section: PaperSection,
        context: Dict[str, Any],
        stream_callback: Optional[Callable[[str, str, str], None]] = None,
    ) -> PaperSection:
        """
        Write a single section.

        Args:
            section: Section to write
            context: Context information
            stream_callback: 可选 (section_id, section_title, token) 回调，流式输出时逐 token 调用

        Returns:
            Updated section with content
        """
        section.status = "writing"

        try:
            # Build context for the prompt
            style = context.get('writing_style', 'academic')
            outline_requirements = ", ".join(section.key_points) if section.key_points else "Standard academic writing"
            previous_content = ""
            if "previous_sections" in context:
                for prev in context.get("previous_sections", []):
                    previous_content += f"\n## {prev.get('title', '')}\n{prev.get('content', '')[:500]}...\n"

            # Build references from global knowledge
            references = ""
            if "global_knowledge" in context:
                methods = context['global_knowledge'].get('mainstream_methods', [])
                references = json.dumps(methods, indent=2)

            global_knowledge = json.dumps(context.get('global_knowledge', {}), indent=2, ensure_ascii=False)

            # 构造引用指令：综述类章节用 ACADEMIC_STYLE_RULES，非综述类保留简化要求
            reference_list = context.get("reference_list") or []
            citation_instruction = _build_citation_instruction(section.title, reference_list)

            # Use the template prompt
            prompt = WRITER_SECTION_PROMPT.format(
                style=style,
                section_title=section.title,
                outline_requirements=outline_requirements,
                previous_content=previous_content,
                references=references,
                global_knowledge=global_knowledge,
                word_count=500
            ) + citation_instruction

            messages = [
                SystemMessage(content=WRITER_SYSTEM),
                HumanMessage(content=prompt)
            ]

            if stream_callback:
                chunks = []
                for chunk in self.llm.stream(messages):
                    c = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    chunks.append(c)
                    if c:
                        stream_callback(section.section_id, section.title, c)
                content = "".join(chunks)
            else:
                content = self.llm.invoke(messages)
                record_token_usage(content, self.config.model.model_name or "gpt-4o")

            section.content = content.content if hasattr(content, 'content') else str(content)
            section.word_count = len(section.content.split())
            section.status = "completed"

        except Exception as e:
            section.status = "failed"
            section.error = str(e)

        return section

    def _build_section_prompt(self, section: PaperSection, context: Dict) -> str:
        """Build prompt for section writing."""
        prompt = f"""Write the "{section.title}" section for an academic paper.

"""
        # Add context
        if "topic" in context:
            prompt += f"Paper topic: {context['topic']}\n\n"

        if "global_knowledge" in context:
            prompt += f"Research background:\n{context['global_knowledge'].get('research_background', '')}\n\n"
            prompt += f"Mainstream methods:\n{json.dumps(context['global_knowledge'].get('mainstream_methods', []), indent=2)}\n\n"

        if "literature_clusters" in context:
            prompt += f"Related literature clusters:\n{json.dumps(context['literature_clusters'], indent=2)}\n\n"

        if "key_points" in section.key_points:
            prompt += f"Key points to cover:\n" + "\n".join(f"- {p}" for p in section.key_points) + "\n\n"

        if section.subsections:
            prompt += f"Subsections:\n" + "\n".join(f"- {s}" for s in section.subsections) + "\n\n"

        # Add previous sections for continuity
        if "previous_sections" in context:
            prompt += "Previous sections:\n"
            for prev in context["previous_sections"]:
                prompt += f"\n## {prev['title']}\n{prev['content'][:500]}...\n"

        prompt += f"""

Write in academic style with proper citations. Output ONLY the section content, no headings or markdown.
Target length: approximately {section.key_points.get('expected_length_words', 500)} words.
"""
        return prompt

    def write_section_with_feedback(
        self,
        section: PaperSection,
        context: Dict[str, Any],
        feedback: Optional[Dict[str, Any]] = None,
    ) -> PaperSection:
        """
        Write section with revision feedback.

        Args:
            section: Section to write
            context: Context information
            feedback: Previous revision feedback

        Returns:
            Updated section
        """
        if feedback and section.content:
            # Rewrite with feedback
            prompt = f"""Rewrite this section incorporating the feedback:

Original section:
{section.content}

Feedback:
{json.dumps(feedback, indent=2)}

Write the improved version maintaining academic style.
Output ONLY the section content.
"""
            messages = [
                SystemMessage(content=WRITER_SYSTEM),
                HumanMessage(content=prompt)
            ]

            try:
                content = self.llm.invoke(messages)
                record_token_usage(content, self.config.model.model_name or "gpt-4o")
                section.content = content
                section.word_count = len(content.split())
                section.status = "completed"
            except Exception as e:
                section.status = "failed"
                section.error = str(e)
        else:
            section = self.write_section(section, context)

        return section

    def write_batch(
        self,
        sections: List[PaperSection],
        context: Dict[str, Any],
        max_workers: int = 3,
        stream_callback: Optional[Callable[[str, str, str], None]] = None,
    ) -> Dict[str, PaperSection]:
        """
        Write multiple sections in parallel.

        Args:
            sections: Sections to write
            context: Context information
            max_workers: Max parallel workers

        Returns:
            Dict of section_id -> PaperSection
        """
        # Sort sections - intro first, conclusion last
        priority_order = {"intro": 0, "introduction": 0, "conclusion": 5, "conclusions": 5}
        sorted_sections = sorted(
            sections,
            key=lambda s: priority_order.get(s.title.lower(), 3)
        )

        results = {}
        previous_sections = []

        # Write sequentially to maintain continuity
        for section in sorted_sections:
            # Add previous sections to context
            section_context = context.copy()
            section_context["previous_sections"] = previous_sections

            result = self.write_section(section, section_context, stream_callback=stream_callback)
            results[section.section_id] = result

            if result.status == "completed":
                previous_sections.append({
                    "section_id": result.section_id,
                    "title": result.title,
                    "content": result.content,
                })

        return results

    def combine_content(self, sections: Dict[str, PaperSection], section_order: Optional[List[str]] = None) -> str:
        """Combine sections into full paper content.

        Args:
            sections: Dict of section_id -> PaperSection
            section_order: Optional list of section_ids in desired order
        """
        import re

        def get_sort_key(section: PaperSection) -> tuple:
            """Get sort key for section ordering."""
            if section_order:
                # Use provided order
                try:
                    idx = section_order.index(section.section_id)
                    return (0, idx, section.section_id)
                except ValueError:
                    pass

            # Try to extract Chinese number from title
            # Pattern: 一、二、三、四、五、六、七、八、九、十、十一...
            chinese_numbers = {
                '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
                '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
            }
            title = section.title
            match = re.match(r'^[一二三四五六七八九十十一]+(?=、)', title)
            if match:
                num_str = match.group()
                num = chinese_numbers.get(num_str, 99)
                return (0, num, section.section_id)

            # Try to extract Arabic number
            match = re.match(r'^\d+', title)
            if match:
                return (0, int(match.group()), section.section_id)

            # Special sections
            lower_title = title.lower()
            if 'abstract' in lower_title or '摘要' in title:
                return (0, -2, section.section_id)
            if 'introduction' in lower_title or '引言' in title:
                return (0, -1, section.section_id)
            if 'conclusion' in lower_title or '结论' in title:
                return (0, 100, section.section_id)
            if 'reference' in lower_title or '参考文献' in title:
                return (0, 200, section.section_id)
            if 'appendix' in lower_title or '附录' in title:
                return (0, 150, section.section_id)

            # Default: use section_id
            return (1, 0, section.section_id)

        parts = []

        # Sort by Chinese number order
        sorted_sections = sorted(sections.values(), key=get_sort_key)

        for section in sorted_sections:
            if section.status == "completed" and section.content:
                parts.append(f"\n\n## {section.title}\n\n")
                # 去除内容开头可能重复的章节标题
                content = section.content
                title_stripped = section.title.lstrip('#').strip()
                if content.startswith(title_stripped):
                    content = content[len(title_stripped):].lstrip('\n').lstrip()
                elif content.startswith(f"## {section.title}") or content.startswith(f"# {section.title}"):
                    # 处理LLM在内容中添加Markdown标题的情况
                    lines = content.split('\n')
                    while lines and (lines[0].startswith('#') or lines[0].strip() == ''):
                        lines.pop(0)
                    content = '\n'.join(lines)
                parts.append(content)

        return "".join(parts)

    def run(
        self,
        global_knowledge: Dict[str, Any],
        topic: str,
        literature_clusters: Optional[List[Dict]] = None,
        max_workers: int = 3,
        reference_list: Optional[List[Dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[str, str, str], None]] = None,
    ) -> WritingResult:
        """
        Run complete writing workflow.

        Args:
            global_knowledge: Analysis from AnalyzerAgent
            topic: Research topic
            literature_clusters: Optional literature clusters
            max_workers: Parallel workers
            reference_list: 带编号的参考文献清单，用于正文 [n] 角标引用

        Returns:
            WritingResult
        """
        # Generate outline
        outline = self.generate_outline(global_knowledge, topic)

        # Build context
        context = {
            "topic": topic,
            "global_knowledge": global_knowledge,
            "literature_clusters": literature_clusters or [],
            "writing_style": outline.writing_style,
            "reference_list": reference_list or [],
        }

        # Write sections (in order to maintain continuity)
        # Note: We write sequentially for better coherence
        sections = self.write_batch(outline.sections, context, max_workers, stream_callback=stream_callback)

        # Get section order from outline
        section_order = [s.section_id for s in outline.sections]

        # Combine content with proper order
        paper_content = self.combine_content(sections, section_order)

        # Count words
        total_words = sum(s.word_count for s in sections.values() if s.status == "completed")
        completed = sum(1 for s in sections.values() if s.status == "completed")
        failed = sum(1 for s in sections.values() if s.status == "failed")

        return WritingResult(
            outline=outline,
            sections=sections,
            completed_sections=completed,
            failed_sections=failed,
            total_words=total_words,
            paper_content=paper_content,
        )

    def to_graphstate_format(self, result: WritingResult) -> Dict[str, Any]:
        """
        Convert to GraphState format.

        Args:
            result: WritingResult

        Returns:
            Dict for GraphState
        """
        # Convert sections
        chapter_drafts = {}
        for section_id, section in result.sections.items():
            if section.status == "completed":
                chapter_drafts[section.title] = {
                    "title": section.title,
                    "content": section.content,
                    "word_count": section.word_count,
                    "references": section.references,
                    "status": section.status,
                }

        # Convert outline
        outline = {
            "title": result.outline.title,
            "abstract_requirements": result.outline.abstract_requirements,
            "sections": [
                {
                    "section_id": s.section_id,
                    "title": s.title,
                    "subsections": s.subsections,
                    "key_points": s.key_points,
                }
                for s in result.outline.sections
            ],
            "total_estimated_words": result.outline.total_estimated_words,
            "writing_style": result.outline.writing_style,
        }

        return {
            "outline": outline,
            "chapter_drafts": chapter_drafts,
            "final_paper": result.paper_content,
            "writing_progress": {
                "completed_sections": result.completed_sections,
                "failed_sections": result.failed_sections,
                "total_words": result.total_words,
            },
        }


# Convenience function
def write_paper(
    topic: str,
    global_knowledge: Dict,
    literature_clusters: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Quick paper writing function.

    Args:
        topic: Research topic
        global_knowledge: Analysis result
        literature_clusters: Optional clusters

    Returns:
        Writing result in GraphState format
    """
    agent = WriterAgent()
    result = agent.run(global_knowledge, topic, literature_clusters)
    return agent.to_graphstate_format(result)


# LangGraph Send API functions for parallel writing
def create_writing_tasks(outline: Dict) -> List[Dict]:
    """
    Create writing tasks for LangGraph Map-Reduce.

    Args:
        outline: Paper outline

    Returns:
        List of task dicts
    """
    tasks = []
    for section in outline.get("sections", []):
        tasks.append({
            "section_id": section.get("section_id"),
            "title": section.get("title"),
            "subsections": section.get("subsections", []),
            "key_points": section.get("key_points", []),
        })
    return tasks


def writing_node(task: Dict, context: Dict) -> Dict:
    """
    Single section writing node for LangGraph.

    Args:
        task: Writing task
        context: Shared context

    Returns:
        Section result
    """
    from config.settings import get_llm_client
    from dataclasses import dataclass

    @dataclass
    class PaperSection:
        section_id: str
        title: str
        content: str = ""
        word_count: int = 0
        status: str = "pending"

    section = PaperSection(
        section_id=task.get("section_id"),
        title=task.get("title"),
    )

    try:
        llm = get_llm_client()

        prompt = f"""Write the "{section.title}" section.

Topic: {context.get('topic')}
Background: {context.get('global_knowledge', {}).get('research_background', '')}

Key points: {json.dumps(task.get('key_points', []))}

Write in academic style. Output ONLY the section content."""

        messages = [HumanMessage(content=prompt)]
        content = llm.invoke(messages)

        section.content = content.content
        section.word_count = len(content.content.split())
        section.status = "completed"

    except Exception as e:
        section.status = "failed"
        section.content = str(e)

    return {
        "section_id": section.section_id,
        "title": section.title,
        "content": section.content,
        "word_count": section.word_count,
        "status": section.status,
    }
