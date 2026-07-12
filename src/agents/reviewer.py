"""
Scira Reviewer Agent

Implements paper review and revision:
- Content review and feedback
- Abstract/Introduction/Conclusion generation (首尾章节后置生成)
- Final paper assembly
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_config, get_llm_client, SciraConfig
from src.utils.logger import record_token_usage
from src.agents.prompts import (
    REVIEW_FEEDBACK_PROMPT,
    REVIEWER_SYSTEM,
    WRITER_SYSTEM,
    WRITER_ABSTRACT_PROMPT,
    WRITER_INTRO_PROMPT,
    WRITER_CONCLUSION_PROMPT,
)
from src.agents.writer import _format_reference_block


def _build_citation_instruction(reference_list: Optional[List[Dict[str, Any]]]) -> str:
    """
    构造引言/结论等后置生成章节的引用指令块。

    与 WriterAgent.write_section 中的 citation_instruction 保持一致：提供编号清单，
    要求正文只使用 [n] 角标、不重复列出参考文献、不编造引用。避免引言/结论出现
    [1] 作者. 题目[J]. 之类的不规范内联条目。
    """
    if not reference_list:
        return (
            "\n\n# 参考文献引用要求\n"
            "本次没有可用的参考文献清单。不要在正文中编造任何引用或角标，"
            "仅基于已知信息客观陈述，参考文献目录将由系统留空。\n"
        )
    reference_block = _format_reference_block(reference_list)
    return (
        "\n\n# 参考文献引用要求（非常重要，必须严格遵守）\n"
        "下方提供了带编号的参考文献清单。这些文献全部来自系统实际检索/知识库，"
        "你不得自行编造任何清单之外的文献。\n"
        "撰写正文时，凡涉及某篇论文的方法、观点或结论，必须在对应处用方括号角标引用，"
        "例如「相关工作表明[1]」「已有研究[2,3]指出」。\n"
        "- 角标数字必须严格对应清单序号，严禁使用清单中不存在的编号。\n"
        "- 不得使用其他引用样式（如 (Author, Year)），统一使用 [n] 形式。\n"
        "- 不得使用 [1] 作者. 题目[J]. 等会展开成完整条目的内联写法。\n"
        "- 若某论点无法对应到清单中任何一篇文献，则不写角标，绝不编造引用。\n"
        "- 参考文献目录将由系统自动生成（GB/T 7714-2015 格式），你只需在正文使用 [n] 角标，不要重复列出参考文献。\n"
        f"\n参考文献清单（仅可引用这些）：\n{reference_block}\n"
    )


@dataclass
class RevisionFeedback:
    """Revision feedback for a section or the whole paper."""
    section_id: Optional[str]  # None for whole paper
    logic_issues: List[Dict[str, str]]  # {location, issue, severity}
    language_issues: List[Dict[str, str]]  # {location, issue, suggestion}
    structure_issues: List[Dict[str, str]]
    overall_assessment: str
    revision_priority: str  # high, medium, low


@dataclass
class ReviewResult:
    """Complete review result."""
    feedback: List[RevisionFeedback]
    abstract: Optional[str] = None
    introduction: Optional[str] = None
    conclusion: Optional[str] = None
    final_paper: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ReviewerAgent:
    """
    Reviewer Agent for paper review and revision.

    Responsibilities:
    1. Review paper content for logic, language, structure
    2. Generate abstract (首尾生成)
    3. Generate introduction (首尾生成)
    4. Generate conclusion (首尾生成)
    5. Assemble final paper
    """

    def __init__(self, config: Optional[SciraConfig] = None):
        """Initialize Reviewer Agent."""
        self.config = config or get_config()
        self.llm = get_llm_client(self.config)

    def review_paper(
        self,
        paper_content: str,
        outline: Optional[Dict[str, Any]] = None,
    ) -> RevisionFeedback:
        """
        Review entire paper.

        Args:
            paper_content: Full paper content
            outline: Optional outline for reference

        Returns:
            RevisionFeedback
        """
        # Use the template prompt
        outline_str = json.dumps(outline) if outline else ""
        prompt = REVIEW_FEEDBACK_PROMPT.format(
            content=paper_content[:3000] + (f"\n\nOutline for reference: {outline_str}" if outline else "")
        )

        messages = [
            SystemMessage(content=REVIEWER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        response = self.llm.invoke(messages)
        record_token_usage(response, self.config.model.model_name or "gpt-4o")
        return self._parse_review(response.content)

    def _parse_review(self, response: str) -> RevisionFeedback:
        """Parse review response."""
        import re

        match = re.search(r'\{[\s\S]*\}', response)
        if not match:
            return RevisionFeedback(
                section_id=None,
                logic_issues=[],
                language_issues=[],
                structure_issues=[],
                overall_assessment="Unable to parse review",
                revision_priority="low",
            )

        try:
            data = json.loads(match.group())
            return RevisionFeedback(
                section_id=data.get("section_id"),
                logic_issues=data.get("logic_issues", []),
                language_issues=data.get("language_issues", []),
                structure_issues=data.get("structure_issues", []),
                overall_assessment=data.get("overall_assessment", ""),
                revision_priority=data.get("revision_priority", "low"),
            )
        except json.JSONDecodeError:
            return RevisionFeedback(
                section_id=None,
                logic_issues=[],
                language_issues=[],
                structure_issues=[],
                overall_assessment="Parse error",
                revision_priority="low",
            )

    # ==================== 首尾章节后置生成 ====================

    def generate_abstract(
        self,
        paper_content: str,
        topic: str,
        global_knowledge: Optional[Dict[str, Any]] = None,
        key_findings: Optional[List[str]] = None,
    ) -> str:
        """
        Generate abstract from paper content (首尾后置生成).

        Automatically generates abstract based on:
        - Full paper content
        - Research topic
        - Global knowledge context
        - Key findings

        Args:
            paper_content: Complete paper (body sections)
            topic: Research topic
            global_knowledge: Analysis results
            key_findings: Key findings from analysis

        Returns:
            Generated abstract
        """
        # Use the template prompt
        prompt = WRITER_ABSTRACT_PROMPT.format(
            title=topic,
            content=paper_content[:4000]
        )

        messages = [
            SystemMessage(content=WRITER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        abstract = self.llm.invoke(messages)
        record_token_usage(abstract, self.config.model.model_name or "gpt-4o")
        return abstract.content.strip()

    def generate_introduction(
        self,
        paper_content: str,
        topic: str,
        global_knowledge: Optional[Dict[str, Any]] = None,
        reference_list: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Generate introduction (首尾后置生成).

        Automatically generates introduction based on:
        - Research background
        - Problem statement
        - Related work summary
        - Contributions

        Args:
            paper_content: Full paper content
            topic: Research topic
            global_knowledge: Analysis results
            reference_list: 编号参考文献清单，用于正文 [n] 角标引用

        Returns:
            Generated introduction
        """
        # Use the template prompt
        global_knowledge_json = json.dumps(global_knowledge, indent=2, ensure_ascii=False) if global_knowledge else "{}"
        prompt = WRITER_INTRO_PROMPT.format(
            title=topic,
            topic=topic,
            global_knowledge=global_knowledge_json
        ) + _build_citation_instruction(reference_list)

        messages = [
            SystemMessage(content=WRITER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        introduction = self.llm.invoke(messages)
        record_token_usage(introduction, self.config.model.model_name or "gpt-4o")
        return introduction.content.strip()

    def generate_conclusion(
        self,
        paper_content: str,
        topic: str,
        global_knowledge: Optional[Dict[str, Any]] = None,
        reference_list: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Generate conclusion (首尾后置生成).

        Automatically generates conclusion based on:
        - Summarized key findings
        - Contributions
        - Limitations
        - Future work

        Args:
            paper_content: Full paper content
            topic: Research topic
            global_knowledge: Analysis results
            reference_list: 编号参考文献清单，用于正文 [n] 角标引用

        Returns:
            Generated conclusion
        """
        # Use the template prompt
        global_knowledge_json = json.dumps(global_knowledge, indent=2, ensure_ascii=False) if global_knowledge else "{}"
        prompt = WRITER_CONCLUSION_PROMPT.format(
            title=topic,
            content=paper_content[:4000],
            global_knowledge=global_knowledge_json
        ) + _build_citation_instruction(reference_list)

        messages = [
            SystemMessage(content=WRITER_SYSTEM),
            HumanMessage(content=prompt)
        ]

        conclusion = self.llm.invoke(messages)
        record_token_usage(conclusion, self.config.model.model_name or "gpt-4o")
        return conclusion.content.strip()

    def generate_front_matter(
        self,
        paper_content: str,
        topic: str,
        global_knowledge: Optional[Dict[str, Any]] = None,
        reference_list: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, str]:
        """
        Generate front matter (首尾后置生成).

        Convenience method to generate abstract + introduction.

        Args:
            paper_content: Full paper content
            topic: Research topic
            global_knowledge: Analysis results
            reference_list: 编号参考文献清单，用于引言/结论 [n] 角标引用

        Returns:
            Dict with abstract, introduction, conclusion
        """
        key_findings = global_knowledge.get("key_findings", []) if global_knowledge else []

        return {
            "abstract": self.generate_abstract(paper_content, topic, global_knowledge, key_findings),
            "introduction": self.generate_introduction(paper_content, topic, global_knowledge, reference_list),
            "conclusion": self.generate_conclusion(paper_content, topic, global_knowledge, reference_list),
        }

    # ==================== 最终整合 ====================

    def assemble_final_paper(
        self,
        abstract: str,
        introduction: str,
        body: str,
        conclusion: str,
    ) -> str:
        """
        Assemble final paper from parts.

        Args:
            abstract: Generated abstract
            introduction: Generated introduction
            body: Paper body (chapters)
            conclusion: Generated conclusion

        Returns:
            Complete paper
        """
        parts = []

        # 摘要
        parts.append("## 摘要\n\n")
        parts.append(abstract)
        parts.append("\n\n")

        # 引言
        parts.append("## 引言\n\n")
        parts.append(introduction)
        parts.append("\n\n")

        # Body (already has ## headings)
        parts.append(body)
        parts.append("\n\n")

        # 结论
        parts.append("## 结论\n\n")
        parts.append(conclusion)

        return "".join(parts)

    def run(
        self,
        paper_content: str,
        topic: str,
        outline: Optional[Dict[str, Any]] = None,
        global_knowledge: Optional[Dict[str, Any]] = None,
        generate_front_matter: bool = True,
        reference_list: Optional[List[Dict[str, Any]]] = None,
    ) -> ReviewResult:
        """
        Run complete review workflow.

        Args:
            paper_content: Paper body content
            topic: Research topic
            outline: Paper outline
            global_knowledge: Analysis results
            generate_front_matter: Whether to generate abstract/intro/conclusion
            reference_list: 编号参考文献清单，传给引言/结论用于 [n] 角标引用

        Returns:
            ReviewResult
        """
        # Step 1: Review paper
        feedback = self.review_paper(paper_content, outline)

        # Step 2: Generate front matter (首尾后置生成)
        abstract = None
        introduction = None
        conclusion = None
        final_paper = None

        if generate_front_matter:
            front_matter = self.generate_front_matter(paper_content, topic, global_knowledge, reference_list)
            abstract = front_matter["abstract"]
            introduction = front_matter["introduction"]
            conclusion = front_matter["conclusion"]

            # Step 3: Assemble final paper
            final_paper = self.assemble_final_paper(
                abstract=abstract,
                introduction=introduction,
                body=paper_content,
                conclusion=conclusion,
            )

        return ReviewResult(
            feedback=[feedback],
            abstract=abstract,
            introduction=introduction,
            conclusion=conclusion,
            final_paper=final_paper,
            metadata={
                "revision_priority": feedback.revision_priority,
                "overall_assessment": feedback.overall_assessment,
            },
        )

    def to_graphstate_format(self, result: ReviewResult) -> Dict[str, Any]:
        """
        Convert to GraphState format.

        Args:
            result: ReviewResult

        Returns:
            Dict for GraphState
        """
        # Build revision feedback
        revision_feedback = {
            "logic_issues": [],
            "language_issues": [],
            "structure_issues": [],
            "overall_assessment": "",
            "revision_priority": "low",
        }

        if result.feedback:
            fb = result.feedback[0]
            revision_feedback = {
                "logic_issues": fb.logic_issues,
                "language_issues": fb.language_issues,
                "structure_issues": fb.structure_issues,
                "overall_assessment": fb.overall_assessment,
                "revision_priority": fb.revision_priority,
            }

        return {
            "revision_feedback": revision_feedback,
            "abstract": result.abstract,
            "introduction": result.introduction,
            "conclusion": result.conclusion,
            "final_review": result.final_paper,
        }


# Convenience function
def review_and_finalize(
    paper_content: str,
    topic: str,
    global_knowledge: Optional[Dict] = None,
    outline: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Quick review and finalization function.

    Args:
        paper_content: Paper body
        topic: Research topic
        global_knowledge: Analysis results
        outline: Paper outline

    Returns:
        Review result in GraphState format
    """
    agent = ReviewerAgent()
    result = agent.run(paper_content, topic, outline, global_knowledge)
    return agent.to_graphstate_format(result)
