"""
Scira Conversation Memory Management

多轮对话记忆管理系统，负责：
- 会话历史存储
- Token 计数
- 上下文压缩
"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from src.utils.logger import get_logger

logger = get_logger("memory")


# ==================== 配置 ====================

MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "60000"))
CONTEXT_COMPRESSION_THRESHOLD = float(os.getenv("CONTEXT_COMPRESSION_THRESHOLD", "0.8"))
COMPRESSION_KEEP_RECENT = int(os.getenv("COMPRESSION_KEEP_RECENT", "5"))

# 会话持久化配置
SESSION_STORAGE_DIR = os.path.join(os.getenv("DATA_DIR", "data"), "sessions")


# ==================== 数据模型 ====================

@dataclass
class ChatMessage:
    """单条聊天消息"""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationContext:
    """会话上下文（包含研究结果）"""
    research_topics: List[str] = field(default_factory=list)
    research_results: Dict[str, Any] = field(default_factory=dict)  # {topic: result}
    paper_ids: List[str] = field(default_factory=list)


@dataclass
class ChatSession:
    """会话数据模型"""
    session_id: str
    created_at: str
    updated_at: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    context: ConversationContext = field(default_factory=ConversationContext)
    context_tokens: int = 0
    compressed: bool = False
    summary: Optional[str] = None  # 压缩后的摘要


# ==================== Token 计数 ====================

def count_tokens(text: str) -> int:
    """
    估算 token 数量

    简单估算：中文约 1.5 字符/token，英文约 4 字符/token
    更准确的实现可以使用 tiktoken 库
    """
    if not text:
        return 0

    # 简单估算：中文按字符数，英文按空格分词
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    english_words = len(text.split())

    # 中文 token ≈ 字符数 / 1.5，英文 token ≈ 词数
    tokens = chinese_chars // 1.5 + english_words

    return int(tokens)


def count_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """计算消息列表的总 token 数"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        total += count_tokens(content)
    return total


# ==================== 上下文压缩 ====================

def should_compress(session: ChatSession) -> bool:
    """判断是否需要压缩上下文"""
    if session.compressed:
        return False

    threshold = int(MAX_CONTEXT_TOKENS * CONTEXT_COMPRESSION_THRESHOLD)
    return session.context_tokens >= threshold


def compress_context(session: ChatSession, llm_client: Optional[Any] = None) -> ChatSession:
    """
    压缩上下文策略：
    1. 保留系统提示
    2. 保留最近 N 轮对话 (COMPRESSION_KEEP_RECENT)
    3. 中间部分生成摘要
    4. 保留研究主题和关键结论
    """
    if not session.messages:
        return session

    # 按时间排序
    sorted_messages = sorted(session.messages, key=lambda x: x.get("timestamp", ""))

    # 分离系统消息、保留消息和可压缩消息
    system_messages = [m for m in sorted_messages if m.get("role") == "system"]
    recent_messages = sorted_messages[-COMPRESSION_KEEP_RECENT * 2:] if len(sorted_messages) > COMPRESSION_KEEP_RECENT * 2 else []
    middle_messages = sorted_messages[len(system_messages):-COMPRESSION_KEEP_RECENT * 2] if len(sorted_messages) > COMPRESSION_KEEP_RECENT * 2 else []

    # 生成中间部分的摘要
    summary = ""
    if middle_messages:
        if llm_client:
            # 使用 LLM 生成摘要
            middle_text = "\n".join([f"{m.get('role')}: {m.get('content', '')[:200]}..." for m in middle_messages])
            try:
                summary_prompt = f"""请为以下对话生成简洁摘要（不超过100字），保留关键信息：
{middle_text}
摘要："""
                summary = llm_client.generate(summary_prompt).strip()
            except Exception as e:
                logger.warning(f"LLM summary failed: {e}")
                summary = _generate_simple_summary(middle_messages)
        else:
            summary = _generate_simple_summary(middle_messages)

    # 构建压缩后的消息
    compressed_messages = system_messages.copy()

    # 添加摘要消息
    if summary:
        compressed_messages.append({
            "role": "system",
            "content": f"[历史摘要] {summary}",
            "timestamp": datetime.now().isoformat(),
            "metadata": {"type": "summary"}
        })

    # 添加最近的消息
    compressed_messages.extend(recent_messages)

    # 更新会话
    session.messages = compressed_messages
    session.context_tokens = count_messages_tokens(compressed_messages)
    session.compressed = True
    session.summary = summary

    logger.info(f"Compressed session {session.session_id}: {len(middle_messages)} messages summarized")

    return session


def _generate_simple_summary(messages: List[Dict[str, Any]]) -> str:
    """简单的摘要生成（无需 LLM）"""
    topics = []
    for msg in messages:
        content = msg.get("content", "")
        # 提取研究主题关键词
        if "研究" in content or "主题" in content:
            topics.append(content[:50])

    if topics:
        return f"讨论了 {len(topics)} 个研究主题"
    return f"包含 {len(messages)} 条历史对话"


# ==================== 会话管理 ====================

class ConversationMemory:
    """会话记忆管理器（支持持久化存储）"""

    def __init__(self):
        self.sessions: Dict[str, ChatSession] = {}
        # 确保存储目录存在
        os.makedirs(SESSION_STORAGE_DIR, exist_ok=True)
        # 启动时加载所有会话
        self._load_all_sessions()

    def _get_session_file_path(self, session_id: str) -> str:
        """获取会话文件路径"""
        return os.path.join(SESSION_STORAGE_DIR, f"{session_id}.json")

    def _load_session(self, session_id: str) -> Optional[ChatSession]:
        """从文件加载单个会话"""
        file_path = self._get_session_file_path(session_id)
        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 重建 ChatSession 对象
            context_data = data.get("context", {})
            context = ConversationContext(
                research_topics=context_data.get("research_topics", []),
                research_results=context_data.get("research_results", {}),
                paper_ids=context_data.get("paper_ids", []),
            )

            session = ChatSession(
                session_id=data["session_id"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                messages=data.get("messages", []),
                context=context,
                context_tokens=data.get("context_tokens", 0),
                compressed=data.get("compressed", False),
                summary=data.get("summary"),
            )
            logger.info(f"Loaded session from disk: {session_id}")
            return session

        except Exception as e:
            logger.warning(f"Failed to load session {session_id}: {e}")
            return None

    def _load_all_sessions(self) -> None:
        """从文件系统加载所有会话"""
        if not os.path.exists(SESSION_STORAGE_DIR):
            os.makedirs(SESSION_STORAGE_DIR, exist_ok=True)
            return

        for filename in os.listdir(SESSION_STORAGE_DIR):
            if filename.endswith('.json'):
                session_id = filename[:-5]  # 去掉 .json 后缀
                session = self._load_session(session_id)
                if session:
                    self.sessions[session_id] = session

        logger.info(f"Loaded {len(self.sessions)} sessions from disk")

    def _save_session(self, session: ChatSession) -> None:
        """将会话保存到文件"""
        file_path = self._get_session_file_path(session.session_id)

        try:
            data = {
                "session_id": session.session_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "messages": session.messages,
                "context": {
                    "research_topics": session.context.research_topics,
                    "research_results": session.context.research_results,
                    "paper_ids": session.context.paper_ids,
                },
                "context_tokens": session.context_tokens,
                "compressed": session.compressed,
                "summary": session.summary,
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved session to disk: {session.session_id}")

        except Exception as e:
            logger.warning(f"Failed to save session {session.session_id}: {e}")

    def _delete_session_file(self, session_id: str) -> bool:
        """删除会话文件"""
        file_path = self._get_session_file_path(session_id)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Deleted session file: {session_id}")
                return True
            except Exception as e:
                logger.warning(f"Failed to delete session file {session_id}: {e}")
        return False

    def create_session(self, session_id: Optional[str] = None) -> ChatSession:
        """创建新会话"""
        if session_id is None:
            session_id = str(uuid.uuid4())

        now = datetime.now().isoformat()
        session = ChatSession(
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        self.sessions[session_id] = session
        # 持久化保存
        self._save_session(session)
        logger.info(f"Created session: {session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """获取会话"""
        return self.sessions.get(session_id)

    def get_or_create_session(self, session_id: Optional[str] = None) -> ChatSession:
        """获取或创建会话"""
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        return self.create_session(session_id)

    def add_message(self, session_id: str, role: str, content: str, metadata: Dict[str, Any] = None) -> ChatSession:
        """添加消息到会话"""
        session = self.get_or_create_session(session_id)

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        session.messages.append(message)
        session.updated_at = datetime.now().isoformat()

        # 重新计算 token
        session.context_tokens = count_messages_tokens(session.messages)

        # 检查是否需要压缩
        if should_compress(session):
            session = compress_context(session)

        # 持久化保存
        self._save_session(session)

        return session

    def update_research_context(self, session_id: str, topic: str, result: Dict[str, Any]) -> None:
        """更新研究上下文"""
        session = self.get_or_create_session(session_id)

        if topic not in session.context.research_topics:
            session.context.research_topics.append(topic)

        session.context.research_results[topic] = result
        session.updated_at = datetime.now().isoformat()

        # 持久化保存
        self._save_session(session)

    def update_last_assistant_message_metadata(self, session_id: str, metadata: Dict[str, Any]) -> bool:
        """
        合并写入会话最后一条 assistant 消息的 metadata。

        用于把检索条件 / 下载确认等结构化信息持久化，使刷新页面后前端能还原卡片。
        返回是否找到并更新了消息。
        """
        session = self.get_session(session_id)
        if not session:
            return False
        for msg in reversed(session.messages):
            if msg.get("role") == "assistant":
                existing = msg.get("metadata") or {}
                existing.update(metadata or {})
                msg["metadata"] = existing
                session.updated_at = datetime.now().isoformat()
                self._save_session(session)
                return True
        return False

    def update_last_assistant_message_content(self, session_id: str, content: str) -> bool:
        """
        用真实完成结果覆盖会话最后一条 assistant 消息的 content。

        修复刷新后仍显示占位符"这需要一些时间..."的问题：占位符在 orchestrator
        阶段落盘，SSE complete 只更新前端 React state，不回写 session。本方法让
        后端在工作流完成后把真实结果写回磁盘。
        """
        session = self.get_session(session_id)
        if not session:
            return False
        for msg in reversed(session.messages):
            if msg.get("role") == "assistant":
                msg["content"] = content
                msg["timestamp"] = datetime.now().isoformat()
                session.updated_at = datetime.now().isoformat()
                self._save_session(session)
                return True
        return False

    def search_history(self, session_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """搜索历史消息"""
        session = self.get_session(session_id)
        if not session:
            return []

        # 简单关键词匹配
        results = []
        for msg in session.messages:
            content = msg.get("content", "")
            if query.lower() in content.lower():
                results.append(msg)

        return results[-top_k:]

    def get_research_topics(self, session_id: str) -> List[str]:
        """获取会话的研究主题"""
        session = self.get_session(session_id)
        if not session:
            return []
        return session.context.research_topics

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            # 删除持久化文件
            self._delete_session_file(session_id)
            logger.info(f"Deleted session: {session_id}")
            return True
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话"""
        return [
            {
                "session_id": s.session_id,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "message_count": len(s.messages),
                "context_tokens": s.context_tokens,
                "research_topics": s.context.research_topics
            }
            for s in self.sessions.values()
        ]


# 全局单例
memory_manager = ConversationMemory()
