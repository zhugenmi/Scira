"""
Scira Orchestrator Agent

Orchestrator 负责：
1. 分析用户消息意图
2. 决策响应策略
3. 协调其他组件完成任务
"""

import json
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from src.agents.base import BaseAgent
from src.agents.intent import IntentAgent, IntentType as RecognizedIntent, WorkflowMode
from config.settings import get_config, SciraConfig


class IntentType(str, Enum):
    """用户意图类型"""
    GREETING = "greeting"           # 问候
    KNOWLEDGE_QUERY = "knowledge_query"  # 知识查询
    NEW_RESEARCH = "new_research"   # 新研究主题（兼容旧值，等价于 full_research）
    FULL_RESEARCH = "full_research"  # 完整调研 + 生成综述
    SEARCH = "search"               # 检索 + 下载论文（不生成综述）
    # 子任务：只生成对应章节，由 Orchestrator 直连生成器，不走工作流
    GENERATE_ABSTRACT = "generate_abstract"
    GENERATE_INTRODUCTION = "generate_introduction"
    GENERATE_CONCLUSION = "generate_conclusion"
    LIST_KB = "list_kb"             # 询问系统知识库本身（有哪些/包含哪些论文）
    CLARIFICATION = "clarification" # 需要澄清
    HELP = "help"                   # 帮助请求
    UNKNOWN = "unknown"             # 未知


@dataclass
class IntentResult:
    """意图分析结果"""
    intent: IntentType
    confidence: float
    reasoning: str
    extracted_topic: Optional[str] = None
    requires_workflow: bool = False
    workflow_mode: str = "full"  # full / search_only / search_download / none


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent - 多轮对话协调器

    分析用户输入，决定如何响应：
    - 简单问候 → 直接回复
    - 知识查询 → 搜索知识库
    - 新研究主题 → 触发工作流
    - 需要澄清 → 提问用户
    """

    def __init__(self, config: Optional[SciraConfig] = None):
        super().__init__(
            name="orchestrator",
            system_prompt="""你是一个智能研究助手协调器。你的职责是：
1. 分析用户消息的意图
2. 根据意图决定最佳响应策略
3. 协调其他组件（知识库、工作流）完成任务

决策规则：
- 如果用户发送问候语（你好、Hi、Hello、早上好等）→ 直接友好回复
- 如果用户询问之前研究过的主题或知识库中的内容 → 搜索知识库后回复
- 如果用户提出新的研究问题或主题 → 触发研究工作流
- 如果用户请求帮助或说明 → 提供帮助信息
- 如果消息不明确需要澄清 → 询问用户

重要：所有回复请使用纯文本格式，不要使用 Markdown 语法（如 ##、**、*、- 等）。直接输出文本内容即可。""",
            config=config,
        )
        # 意图识别委托给专用 IntentAgent
        self.intent_agent = IntentAgent(config=config)

    def analyze_intent(
        self,
        user_message: str,
        session_context: Optional[Dict[str, Any]] = None,
        message_history: Optional[List[Dict[str, Any]]] = None,
    ) -> IntentResult:
        """
        分析用户消息意图（委托给 IntentAgent）。

        Args:
            user_message: 用户消息
            session_context: 会话上下文（可选，包含之前的研究主题等）
            message_history: 历史消息列表（可选，用于提供对话上下文）

        Returns:
            IntentResult: 意图分析结果（含 workflow_mode）
        """
        recognized = self.intent_agent.analyze(
            user_message=user_message,
            session_context=session_context,
            message_history=message_history,
        )

        # 把 IntentAgent 的意图枚举映射回 Orchestrator 的 IntentType
        intent_map = {
            RecognizedIntent.GREETING: IntentType.GREETING,
            RecognizedIntent.KNOWLEDGE_QUERY: IntentType.KNOWLEDGE_QUERY,
            RecognizedIntent.FULL_RESEARCH: IntentType.FULL_RESEARCH,
            RecognizedIntent.SEARCH: IntentType.SEARCH,
            RecognizedIntent.GENERATE_ABSTRACT: IntentType.GENERATE_ABSTRACT,
            RecognizedIntent.GENERATE_INTRODUCTION: IntentType.GENERATE_INTRODUCTION,
            RecognizedIntent.GENERATE_CONCLUSION: IntentType.GENERATE_CONCLUSION,
            RecognizedIntent.LIST_KB: IntentType.LIST_KB,
            RecognizedIntent.CLARIFICATION: IntentType.CLARIFICATION,
            RecognizedIntent.HELP: IntentType.HELP,
            RecognizedIntent.UNKNOWN: IntentType.UNKNOWN,
        }
        intent = intent_map.get(recognized.intent, IntentType.UNKNOWN)

        # 是否需要启动工作流：mode != none 即需要
        requires_workflow = recognized.workflow_mode != WorkflowMode.NONE

        return IntentResult(
            intent=intent,
            confidence=recognized.confidence,
            reasoning=recognized.reasoning,
            extracted_topic=recognized.extracted_topic,
            requires_workflow=requires_workflow,
            workflow_mode=recognized.workflow_mode.value,
        )

    def generate_greeting_response(self, user_message: str) -> str:
        """
        生成问候回复

        Args:
            user_message: 用户消息

        Returns:
            友好的回复文本
        """
        # 检测语言
        has_chinese = any('一' <= c <= '鿿' for c in user_message)

        prompt = f"""用户向你打招呼："{user_message}"

请生成一个友好、专业的回复：
- 简短热情
- 介绍你可以帮助做什么（文献调研、论文写作、研究分析等）
- 询问用户需要什么帮助

请用纯文本格式回复，不要使用任何 Markdown 语法。
{"请用中文回复" if has_chinese else "请用英文回复"}"""

        return self.invoke(prompt)

    def generate_knowledge_response(
        self,
        user_message: str,
        search_results: Dict[str, Any],
    ) -> str:
        """
        基于知识库搜索结果生成回复

        Args:
            user_message: 用户消息
            search_results: 知识库搜索结果

        Returns:
            生成的回复
        """
        # 格式化搜索结果
        from src.core.knowledge import format_knowledge_response

        knowledge_text = format_knowledge_response(search_results)

        prompt = f"""用户询问："{user_message}"

知识库搜索结果：
{knowledge_text}

请基于搜索结果生成回复：
- 如果找到相关内容，总结关键信息
- 如果未找到，诚实地说明并建议用户可以进行新的研究
- 保持专业、友好的语气
- 请用纯文本格式回复，不要使用任何 Markdown 语法"""

        return self.invoke(prompt)

    def generate_clarification_response(self, user_message: str) -> str:
        """
        生成需要澄清的回复

        Args:
            user_message: 用户消息

        Returns:
            询问澄清的问题
        """
        prompt = f"""用户的消息需要更多澄清："{user_message}"

请生成一个问题来帮助澄清用户的意图：
- 询问具体的研究方向
- 询问期望的输出形式（报告、论文、摘要等）
- 询问是否有特定的时间范围或领域偏好

请用纯文本格式回复，保持友好和专业。"""

        return self.invoke(prompt)

    def process_message(
        self,
        user_message: str,
        session_id: str,
        session_context: Optional[Dict[str, Any]] = None,
        message_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        处理用户消息的主要入口

        Args:
            user_message: 用户消息
            session_id: 会话 ID
            session_context: 会话上下文
            message_history: 历史消息列表

        Returns:
            处理结果字典
        """
        # 1. 分析意图
        intent_result = self.analyze_intent(user_message, session_context, message_history)

        result = {
            "session_id": session_id,
            "intent": intent_result.intent.value,
            "confidence": intent_result.confidence,
            "reasoning": intent_result.reasoning,
            "workflow_mode": intent_result.workflow_mode,
        }

        # 2. 根据意图处理
        if intent_result.intent == IntentType.GREETING:
            # 直接回复问候
            response = self.generate_greeting_response(user_message)
            result["response"] = response
            result["action"] = "direct_response"

        elif intent_result.intent == IntentType.KNOWLEDGE_QUERY:
            # 搜索知识库
            from src.core.knowledge import search_knowledge
            search_results = search_knowledge(
                query=user_message,
                session_id=session_id,
            )
            response = self.generate_knowledge_response(user_message, search_results)
            result["response"] = response
            result["search_results"] = search_results
            result["action"] = "knowledge_query"

        elif intent_result.intent == IntentType.NEW_RESEARCH:
            # 触发工作流（兼容旧意图，按完整流程处理）
            topic = intent_result.extracted_topic or user_message
            result["response"] = f"好的，我将帮您研究「{topic}」。这需要一些时间，请稍候..."
            result["research_topic"] = topic
            result["action"] = "start_workflow"
            result["requires_workflow"] = True
            result["workflow_mode"] = "full"

        elif intent_result.intent == IntentType.FULL_RESEARCH:
            # 完整调研 + 生成综述
            topic = intent_result.extracted_topic or user_message
            result["response"] = f"好的，我将调研「{topic}」并生成综述论文。这需要一些时间，请稍候..."
            result["research_topic"] = topic
            result["action"] = "start_workflow"
            result["requires_workflow"] = True
            result["workflow_mode"] = "full"

        elif intent_result.intent == IntentType.SEARCH:
            # 检索 + 下载论文（检索到后自动下载 PDF，不生成综述）
            topic = intent_result.extracted_topic or user_message
            result["response"] = f"好的，我将为您检索并下载「{topic}」相关论文。请确认检索条件后开始..."
            result["research_topic"] = topic
            result["action"] = "start_workflow"
            result["requires_workflow"] = True
            result["workflow_mode"] = "search"

        elif intent_result.intent == IntentType.GENERATE_ABSTRACT:
            # 子任务：只生成摘要，不触发工作流
            topic = intent_result.extracted_topic or user_message
            result["response"] = f"好的，我将为您生成摘要，请稍候..."
            result["research_topic"] = topic
            result["action"] = "generate_abstract"
            result["requires_workflow"] = False
            result["workflow_mode"] = "none"

        elif intent_result.intent == IntentType.GENERATE_INTRODUCTION:
            # 子任务：只生成引言，不触发工作流
            topic = intent_result.extracted_topic or user_message
            result["response"] = f"好的，我将为您生成引言，请稍候..."
            result["research_topic"] = topic
            result["action"] = "generate_introduction"
            result["requires_workflow"] = False
            result["workflow_mode"] = "none"

        elif intent_result.intent == IntentType.GENERATE_CONCLUSION:
            # 子任务：只生成结论/总结，不触发工作流
            topic = intent_result.extracted_topic or user_message
            result["response"] = f"好的，我将为您生成结论，请稍候..."
            result["research_topic"] = topic
            result["action"] = "generate_conclusion"
            result["requires_workflow"] = False
            result["workflow_mode"] = "none"

        elif intent_result.intent == IntentType.LIST_KB:
            # 询问系统知识库本身：直接列出 data/papers 下的知识库与论文清单
            from src.core.knowledge import list_knowledge_bases, format_knowledge_base_listing
            listing = list_knowledge_bases()
            response = format_knowledge_base_listing(listing)
            result["response"] = response
            result["action"] = "list_kb"
            result["kb_listing"] = listing

        elif intent_result.intent == IntentType.CLARIFICATION:
            # 需要澄清
            response = self.generate_clarification_response(user_message)
            result["response"] = response
            result["action"] = "clarification"

        elif intent_result.intent == IntentType.HELP:
            # 帮助请求
            response = self.generate_help_response()
            result["response"] = response
            result["action"] = "help"

        else:
            # 未知意图，默认触发完整工作流（保守：不漏综述需求）
            result["response"] = "我理解您需要进行研究，让我帮您处理..."
            result["action"] = "start_workflow"
            result["requires_workflow"] = True
            result["workflow_mode"] = "full"

        return result

    def generate_help_response(self) -> str:
        """生成帮助信息"""
        help_text = """我可以帮助您进行学术研究：

文献调研
- 输入研究主题，自动搜索和整理相关论文
- 提取论文核心信息，进行聚类分析

论文写作
- 基于文献分析生成论文大纲
- 分章节自动撰写，支持多轮修订

智能问答
- 询问已研究的主题，我会从知识库中查找
- 简单问候可直接回复

使用示例
- "帮我研究大语言模型在医疗领域的应用"
- "之前的研究进展如何？"
- "深度强化学习的研究现状"

请告诉我您想做什么？"""
        return help_text


# 便捷函数
def create_orchestrator(config: Optional[SciraConfig] = None) -> OrchestratorAgent:
    """创建 Orchestrator Agent"""
    return OrchestratorAgent(config)
