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


def list_knowledge_bases() -> Dict[str, Any]:
    """
    列出系统中所有知识库及其论文清单，供"系统中有哪些知识库"类查询使用。

    读取 data/papers/all_papers.json 索引 + 各分类 JSON 论文清单，返回：
    {
        "categories": [{"name", "topic", "count", "papers": [{paper_id,title,authors,published_date}]}],
        "total_papers": int,
        "total_categories": int,
    }
    缺索引或分类文件时尽可能降级返回，不抛异常。
    """
    result: Dict[str, Any] = {"categories": [], "total_papers": 0, "total_categories": 0}
    if not PAPERS_DIR.exists():
        return result

    # 1) 优先用 all_papers.json 索引拿 categories 顺序与 topic/count
    index: Dict[str, Any] = {}
    all_papers_file = PAPERS_DIR / "all_papers.json"
    if all_papers_file.exists():
        try:
            with open(all_papers_file, "r", encoding="utf-8") as f:
                index = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read all_papers.json: {e}")

    categories_index = index.get("categories", {}) or {}

    # 2) 若索引为空，扫目录兜底
    if not categories_index:
        for d in sorted(PAPERS_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and not d.name.startswith("."):
                categories_index[d.name] = {"path": str(d / f"{d.name}.json"), "topic": d.name, "count": 0}

    total_papers = 0
    cat_entries: List[Dict[str, Any]] = []
    for cat_name, entry in categories_index.items():
        if isinstance(entry, str):
            # 旧格式：entry 是 path 字符串
            cat_path = entry
            cat_topic = cat_name
            cat_count = 0
        else:
            cat_path = entry.get("path", "")
            cat_topic = entry.get("topic", "") or cat_name
            cat_count = int(entry.get("count", 0) or 0)

        papers: List[Dict[str, Any]] = []
        # 优先读分类 JSON 拿论文清单
        cat_file = Path(cat_path) if cat_path else (PAPERS_DIR / cat_name / f"{cat_name}.json")
        if cat_file.exists():
            try:
                with open(cat_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for p in data.get("papers", []) or []:
                    authors = p.get("authors", [])
                    if isinstance(authors, str):
                        authors = [a.strip() for a in authors.split(";") if a.strip()]
                    papers.append({
                        "paper_id": p.get("paper_id", ""),
                        "title": p.get("title", ""),
                        "authors": authors,
                        "published_date": p.get("published_date", ""),
                    })
                # 文件内实际论文数比索引 count 更可信
                if papers:
                    cat_count = len(papers)
            except Exception as e:
                logger.warning(f"Failed to read category file {cat_file}: {e}")

        total_papers += cat_count
        cat_entries.append({
            "name": cat_name,
            "topic": cat_topic,
            "count": cat_count,
            "papers": papers,
        })

    cat_entries.sort(key=lambda c: c.get("name", ""))
    result["categories"] = cat_entries
    result["total_papers"] = total_papers
    result["total_categories"] = len(cat_entries)
    return result


def format_knowledge_base_listing(listing: Dict[str, Any]) -> str:
    """
    把 list_knowledge_bases() 的结果格式化为纯文本回复（不用 markdown 语法，
    遵循 Orchestrator 纯文本回复约定）。
    """
    cats = listing.get("categories", []) or []
    if not cats:
        return "当前系统中还没有任何知识库。您可以输入研究主题，我会为您检索并建立新的知识库。"

    lines: List[str] = []
    lines.append(f"系统中共有 {len(cats)} 个知识库，收录 {listing.get('total_papers', 0)} 篇论文：")
    lines.append("")
    for i, c in enumerate(cats, 1):
        topic = c.get("topic") or c.get("name", "")
        name = c.get("name", "")
        count = c.get("count", 0)
        # 优先展示 topic（中文友好），括号内附目录名
        label = topic if topic and topic != name else name
        lines.append(f"{i}. {label}（目录：{name}，{count} 篇）")
        for p in (c.get("papers") or [])[:5]:
            title = (p.get("title") or "Untitled").strip()
            authors = p.get("authors") or []
            if isinstance(authors, list):
                author_str = ", ".join(authors[:3])
                if len(authors) > 3:
                    author_str += " 等"
            else:
                author_str = str(authors)
            date = (p.get("published_date") or "")[:4]
            year = f"({date})" if date else ""
            lines.append(f"   - {title} — {author_str}{year}")
        if c.get("count", 0) > 5:
            lines.append(f"   … 还有 {c['count'] - 5} 篇，可在「知识库」页面查看完整列表。")
        lines.append("")
    lines.append("您可以让我基于这些知识库生成综述（点击输入框旁的「从知识库生成」按钮），或输入新主题进行检索。")
    return "\n".join(lines)


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
