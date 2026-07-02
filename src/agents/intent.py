"""
Scira Intent Agent

专门负责用户消息的意图识别，并决定启动哪一段工作流：

- full_research      完整工作流（检索 → 阅读 → 分析 → 写作 → 审查 → 生成综述）
- search_only        仅检索论文（保存元数据，不下载 PDF、不生成报告）
- search_download    检索 + 下载 PDF（不生成报告）
- none               不启动工作流（问候 / 知识查询 / 帮助 / 需澄清）

通过一个 LLM 调用完成意图分类，输出结构化 JSON。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.agents.base import BaseAgent
from src.agents.prompts import INTENT_SYSTEM, INTENT_ANALYZE_PROMPT
from config.settings import SciraConfig


class WorkflowMode(str, Enum):
    """工作流执行模式。"""
    FULL = "full"        # 完整工作流：检索→下载→阅读→分析→写作→审查→生成综述
    SEARCH = "search"    # 检索 + 下载 PDF（不生成综述，完成后返回论文简介）
    NONE = "none"        # 不启动工作流（问候 / 知识查询 / 帮助 / 需澄清）


class IntentType(str, Enum):
    """用户意图类型。"""
    GREETING = "greeting"
    KNOWLEDGE_QUERY = "knowledge_query"
    FULL_RESEARCH = "full_research"
    SEARCH = "search"          # 检索 + 下载论文（不生成综述）
    # 子任务意图：只生成对应章节，不触发完整检索/写作工作流。
    # 复用 workflow_mode=NONE，由 Orchestrator 直连 ReviewerAgent 生成器。
    GENERATE_ABSTRACT = "generate_abstract"
    GENERATE_INTRODUCTION = "generate_introduction"
    GENERATE_CONCLUSION = "generate_conclusion"
    # 询问系统知识库本身的结构（有哪些知识库/包含哪些论文），不走 LLM 知识检索
    LIST_KB = "list_kb"
    CLARIFICATION = "clarification"
    HELP = "help"
    UNKNOWN = "unknown"


# intent → workflow_mode 的映射，用于兜底/解析失败时回退
_INTENT_TO_MODE: Dict[str, WorkflowMode] = {
    IntentType.GREETING.value: WorkflowMode.NONE,
    IntentType.KNOWLEDGE_QUERY.value: WorkflowMode.NONE,
    IntentType.FULL_RESEARCH.value: WorkflowMode.FULL,
    IntentType.SEARCH.value: WorkflowMode.SEARCH,
    IntentType.GENERATE_ABSTRACT.value: WorkflowMode.NONE,
    IntentType.GENERATE_INTRODUCTION.value: WorkflowMode.NONE,
    IntentType.GENERATE_CONCLUSION.value: WorkflowMode.NONE,
    IntentType.LIST_KB.value: WorkflowMode.NONE,
    IntentType.CLARIFICATION.value: WorkflowMode.NONE,
    IntentType.HELP.value: WorkflowMode.NONE,
    IntentType.UNKNOWN.value: WorkflowMode.FULL,  # 未知时保守走完整流程
}


@dataclass
class IntentResult:
    """意图识别结果。"""
    intent: IntentType
    workflow_mode: WorkflowMode
    confidence: float
    reasoning: str
    extracted_topic: Optional[str] = None


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从可能含噪声的 LLM 输出中提取首个 JSON 对象。"""
    if not text:
        return None
    # 去掉 ```json ... ``` 包裹
    cleaned = text.strip()
    if "```" in cleaned:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1)
    # 直接定位首个 {...}
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    import json
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


_CN_NUMERAL_MAP = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _cn_numeral_to_int(s: str) -> Optional[int]:
    """Convert a Chinese numeral string (1-99) to int. Returns None if not matched."""
    if not s:
        return None
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    if len(s) == 1:
        return _CN_NUMERAL_MAP.get(s)
    # e.g. 十五 / 二十 / 二十五
    if s.startswith("十"):
        rest = _CN_NUMERAL_MAP.get(s[1:], 0)
        return 10 + rest if rest or s[1:] == "零" else 10
    if "十" in s:
        parts = s.split("十")
        tens = _CN_NUMERAL_MAP.get(parts[0], 0) or 1
        ones = _CN_NUMERAL_MAP.get(parts[1], 0) if parts[1] else 0
        return tens * 10 + ones
    return None


def _extract_constraints_fallback(
    user_message: str,
) -> Tuple[Optional[Tuple[int, int]], Optional[int]]:
    """Regex-based fallback for extracting year_range and min_count from user message.

    Covers Chinese ('最近N年/近N年/N年内') and English ('past/last N years'),
    plus '不少于/至少/最少 N 篇' and 'N 篇以上'. Returns (year_range, min_count),
    either may be None.
    """
    import datetime

    if not user_message:
        return None, None

    today = datetime.date.today()
    year_range: Optional[Tuple[int, int]] = None
    min_count: Optional[int] = None

    # Year range: Chinese with arabic or numeral
    # 最近5年 / 近五年 / 5年内
    m = re.search(r"(?:最近|近|过去)?\s*([0-9一二三四五六七八九十两]{1,3})\s*年(?:内|内的|的)?", user_message)
    if m:
        n = _cn_numeral_to_int(m.group(1))
        if n and 1 <= n <= 30:
            year_range = (today.year - n + 1, today.year)

    # English: past/last N years
    m_en = re.search(r"(?:past|last|recent)\s+(\d{1,2})\s+years?", user_message, re.IGNORECASE)
    if m_en and not year_range:
        n = int(m_en.group(1))
        if 1 <= n <= 30:
            year_range = (today.year - n + 1, today.year)

    # Min count: 不少于/至少/最少 N 篇
    m_mc = re.search(r"(?:不少于|至少|最少|不小于)\s*(\d{1,4})\s*篇", user_message)
    if m_mc:
        min_count = int(m_mc.group(1))
    else:
        # N 篇以上
        m_above = re.search(r"(\d{1,4})\s*篇\s*以上", user_message)
        if m_above:
            min_count = int(m_above.group(1))

    return year_range, min_count


class IntentAgent(BaseAgent):
    """
    意图识别 Agent。

    输入用户消息（可选会话上下文 + 历史），输出 IntentResult：
    - intent: 意图类型
    - workflow_mode: 工作流模式（full / search_only / search_download / none）
    - extracted_topic: 抽取的研究主题
    """

    def __init__(self, config: Optional[SciraConfig] = None):
        super().__init__(name="intent", system_prompt=INTENT_SYSTEM, config=config)

    def analyze(
        self,
        user_message: str,
        session_context: Optional[Dict[str, Any]] = None,
        message_history: Optional[List[Dict[str, Any]]] = None,
    ) -> IntentResult:
        """
        分析用户消息意图。

        Args:
            user_message: 用户消息
            session_context: 会话上下文（含 research_topics 等）
            message_history: 历史消息（取最近 5 条提供上下文）

        Returns:
            IntentResult
        """
        kb_summary = ""
        if session_context:
            kb_summary = session_context.get("kb_summary", "")
        if not kb_summary:
            kb_summary = "（未提供知识库概况）"
        kb_summary_block = f"\n系统知识库概况：{kb_summary}"

        context_info = ""
        if session_context:
            topics = session_context.get("research_topics", [])
            if topics:
                context_info = f"\n当前会话已研究的主题：{', '.join(topics)}"

        history_info = ""
        if message_history:
            recent = message_history[-5:]
            lines = []
            for msg in recent:
                role = "用户" if msg.get("role") == "user" else "助手"
                content = (msg.get("content") or "")[:100]
                if content:
                    lines.append(f"{role}: {content}")
            if lines:
                history_info = "\n\n对话历史（最近几条）：\n" + "\n".join(lines)

        prompt = INTENT_ANALYZE_PROMPT.format(
            user_query=user_message,
            kb_summary=kb_summary_block,
            context_info=context_info,
            history_info=history_info,
        )

        try:
            raw = self.invoke(prompt)
            parsed = _extract_json(raw) or {}
            intent_str = str(parsed.get("intent", "unknown")).strip().lower()
            mode_str = str(parsed.get("workflow_mode", "")).strip().lower()

            # 解析 intent
            try:
                intent = IntentType(intent_str)
            except ValueError:
                intent = IntentType.UNKNOWN

            # 解析 workflow_mode：优先用 LLM 返回值，无效则按 intent 映射兜底
            try:
                workflow_mode = WorkflowMode(mode_str)
            except ValueError:
                workflow_mode = _INTENT_TO_MODE.get(intent.value, WorkflowMode.FULL)

            # 一致性校正：intent 与 mode 不匹配时以 intent 映射为准
            expected_mode = _INTENT_TO_MODE.get(intent.value, WorkflowMode.FULL)
            if workflow_mode != expected_mode and intent != IntentType.UNKNOWN:
                workflow_mode = expected_mode

            return IntentResult(
                intent=intent,
                workflow_mode=workflow_mode,
                confidence=float(parsed.get("confidence", 0.5)),
                reasoning=parsed.get("reasoning", ""),
                extracted_topic=parsed.get("extracted_topic") or None,
            )
        except Exception as e:
            # LLM 调用失败：走关键词兜底，避免阻塞用户
            return self._keyword_fallback(user_message, str(e))

    def _keyword_fallback(self, user_message: str, err: str) -> IntentResult:
        """
        关键词兜底：LLM 不可用时按规则字面匹配。

        规则优先级（自上而下，命中即返回）：
        1. 综述/报告/写论文 → full_research
        2. 检索/查找/搜索/下载论文 → search
        3. 生成摘要/写摘要 → generate_abstract
        4. 生成引言/写引言 → generate_introduction
        5. 生成结论/生成总结/写结论/写总结 → generate_conclusion
        6. 默认完整流程（保守：不漏掉用户的综述需求）
        检索和下载统一归为 search 模式（检索后自动下载）。
        """
        msg = user_message or ""
        has_report = any(k in msg for k in ("综述", "报告", "写一篇", "写论文", "生成论文", "review", "survey"))
        has_search = any(k in msg for k in (
            "检索", "查找", "搜索", "下载", "获取", "search", "find", "look up", "download", "fetch",
        ))
        has_abstract = any(k in msg for k in ("生成摘要", "写摘要", "写个摘要", "写一个摘要", "帮我写摘要"))
        has_intro = any(k in msg for k in ("生成引言", "写引言", "写个引言", "写开头", "帮我写引言", "引言部分"))
        has_conclusion = any(k in msg for k in (
            "生成结论", "生成总结", "写结论", "写总结", "收尾", "结论部分", "帮我写结论",
        ))
        # 列举系统知识库本身：含"知识库"且含"有哪些/列表/包含/几个"等枚举词
        has_list_kb = "知识库" in msg and any(
            k in msg for k in ("有哪些", "列出", "列表", "包含哪些", "几个", "都有什么", "都有哪些", "list")
        )

        if has_list_kb:
            return IntentResult(
                intent=IntentType.LIST_KB,
                workflow_mode=WorkflowMode.NONE,
                confidence=0.8,
                reasoning=f"keyword fallback (list_kb): {err}",
                extracted_topic=None,
            )

        if has_report:
            return IntentResult(
                intent=IntentType.FULL_RESEARCH,
                workflow_mode=WorkflowMode.FULL,
                confidence=0.6,
                reasoning=f"keyword fallback (report): {err}",
                extracted_topic=msg,
            )
        if has_search:
            return IntentResult(
                intent=IntentType.SEARCH,
                workflow_mode=WorkflowMode.SEARCH,
                confidence=0.6,
                reasoning=f"keyword fallback (search): {err}",
                extracted_topic=msg,
            )
        if has_abstract:
            return IntentResult(
                intent=IntentType.GENERATE_ABSTRACT,
                workflow_mode=WorkflowMode.NONE,
                confidence=0.7,
                reasoning=f"keyword fallback (abstract): {err}",
                extracted_topic=msg,
            )
        if has_intro:
            return IntentResult(
                intent=IntentType.GENERATE_INTRODUCTION,
                workflow_mode=WorkflowMode.NONE,
                confidence=0.7,
                reasoning=f"keyword fallback (introduction): {err}",
                extracted_topic=msg,
            )
        if has_conclusion:
            return IntentResult(
                intent=IntentType.GENERATE_CONCLUSION,
                workflow_mode=WorkflowMode.NONE,
                confidence=0.7,
                reasoning=f"keyword fallback (conclusion): {err}",
                extracted_topic=msg,
            )
        # 默认完整流程（保守：不漏掉用户的综述需求）
        return IntentResult(
            intent=IntentType.FULL_RESEARCH,
            workflow_mode=WorkflowMode.FULL,
            confidence=0.4,
            reasoning=f"keyword fallback (default full): {err}",
            extracted_topic=msg,
        )


def create_intent_agent(config: Optional[SciraConfig] = None) -> IntentAgent:
    """创建意图识别 Agent。"""
    return IntentAgent(config)
