"""
Scira Knowledge Base Query

知识库查询模块，负责：
- 搜索会话历史中的研究内容
- 搜索本地论文知识库
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.utils.logger import get_logger

logger = get_logger("knowledge")


# ==================== 配置 ====================

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PAPERS_DIR = DATA_DIR / "papers"
OUTPUTS_DIR = DATA_DIR / "outputs"


# ==================== 知识库查询 ====================

def search_knowledge(query: str, session_id: str = None, top_k: int = 5) -> Dict[str, Any]:
    """
    搜索知识库

    查询优先级：
    1. 会话历史中的研究结果
    2. 本地论文知识库

    Args:
        query: 查询关键词
        session_id: 会话 ID（可选）
        top_k: 返回结果数量

    Returns:
        搜索结果字典
    """
    results = {
        "query": query,
        "session_results": [],
        "paper_results": [],
        "output_results": []
    }

    # 1. 搜索会话历史
    if session_id:
        from src.core.memory import memory_manager
        session = memory_manager.get_session(session_id)
        if session:
            # 搜索研究主题
            for topic in session.context.research_topics:
                if query.lower() in topic.lower():
                    results["session_results"].append({
                        "type": "research_topic",
                        "topic": topic,
                        "result": session.context.research_results.get(topic, {})
                    })

            # 搜索历史消息
            history = memory_manager.search_history(session_id, query, top_k)
            results["session_results"].extend(history)

    # 2. 搜索论文知识库
    paper_results = search_papers(query, top_k)
    results["paper_results"] = paper_results

    # 3. 搜索输出报告
    output_results = search_outputs(query, top_k)
    results["output_results"] = output_results

    return results


def search_papers(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    搜索论文知识库

    搜索 data/papers/ 目录下的论文 JSON 文件
    """
    results = []

    if not PAPERS_DIR.exists():
        logger.warning(f"Papers directory not found: {PAPERS_DIR}")
        return results

    # 收集所有论文
    all_papers = []

    # 方法1: 搜索 topic 子目录
    for topic_dir in PAPERS_DIR.iterdir():
        if topic_dir.is_dir():
            topic_name = topic_dir.name
            for json_file in topic_dir.glob("*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        papers = data.get("papers", [])
                        for paper in papers:
                            paper["_topic"] = topic_name
                            paper["_source"] = str(json_file.name)
                            all_papers.append(paper)
                except Exception as e:
                    logger.warning(f"Failed to read {json_file}: {e}")

    # 搜索匹配
    query_lower = query.lower()
    for paper in all_papers:
        title = paper.get("title", "").lower()
        abstract = paper.get("abstract", "").lower()
        authors = paper.get("authors", "")

        # 检查是否匹配
        if (query_lower in title or
            query_lower in abstract or
            (isinstance(authors, str) and query_lower in authors.lower())):
            results.append({
                "type": "paper",
                "paper_id": paper.get("paper_id"),
                "title": paper.get("title"),
                "authors": paper.get("authors"),
                "abstract": paper.get("abstract", "")[:300],
                "published_date": paper.get("published_date"),
                "topic": paper.get("_topic", "general"),
                "pdf_url": paper.get("pdf_url", "")
            })

    return results[:top_k]


def search_outputs(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    搜索生成的研究报告

    搜索 data/outputs/ 目录下的报告文件
    """
    results = []

    if not OUTPUTS_DIR.exists():
        logger.warning(f"Outputs directory not found: {OUTPUTS_DIR}")
        return results

    query_lower = query.lower()

    for output_file in OUTPUTS_DIR.glob("*.md"):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # 简单匹配
                if query_lower in content.lower():
                    # 提取标题（文件名前缀）
                    title = output_file.stem.replace("_", " ").title()

                    # 提取相关片段
                    lines = content.split("\n")
                    relevant_lines = []
                    for line in lines:
                        if query_lower in line.lower():
                            relevant_lines.append(line.strip())

                    snippet = "\n".join(relevant_lines[:3])

                    results.append({
                        "type": "report",
                        "title": title,
                        "filename": output_file.name,
                        "snippet": snippet[:500] if snippet else content[:300]
                    })
        except Exception as e:
            logger.warning(f"Failed to read {output_file}: {e}")

    return results[:top_k]


def format_knowledge_response(search_results: Dict[str, Any]) -> str:
    """
    格式化知识库搜索结果为可读文本

    Args:
        search_results: search_knowledge() 的返回结果

    Returns:
        格式化的响应文本
    """
    parts = []

    # 会话研究结果
    if search_results.get("session_results"):
        parts.append("📚 会话历史中的相关研究：")
        for item in search_results["session_results"][:3]:
            if item.get("type") == "research_topic":
                parts.append(f"  • 主题：{item.get('topic')}")
            else:
                content = item.get("content", "")[:200]
                parts.append(f"  • {item.get('role')}: {content}...")

    # 论文结果
    if search_results.get("paper_results"):
        parts.append("\n📄 相关论文：")
        for paper in search_results["paper_results"][:3]:
            title = paper.get("title", "Untitled")
            authors = paper.get("authors", "Unknown")
            date = paper.get("published_date", "")
            parts.append(f"  • {title}")
            parts.append(f"    作者：{authors} | 发表：{date}")

    # 报告结果
    if search_results.get("output_results"):
        parts.append("\n📝 相关研究报告：")
        for report in search_results["output_results"][:3]:
            title = report.get("title", "Untitled")
            snippet = report.get("snippet", "")[:150]
            parts.append(f"  • {title}")
            parts.append(f"    {snippet}...")

    if not parts:
        return "未在知识库中找到相关内容。"

    return "\n".join(parts)
