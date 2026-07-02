"""
知识库上下文构建模块。

供 AI 报告编辑流程与 Orchestrator 普通对话路径共用，把 KB 状态注入 LLM 上下文。
"""
import re as _re
from typing import Any, Dict, List

from src.core.knowledge import list_knowledge_bases, search_papers
from src.core.workflow import format_bibliography
from src.utils.logger import get_logger

logger = get_logger("kb_context")


def build_kb_directory_summary() -> str:
    """轻量 KB 目录摘要，常驻注入。

    返回单行文本，约 200 token 内。读取失败/空库返回空串，不阻塞调用方。
    """
    try:
        listing = list_knowledge_bases()
    except Exception as e:
        logger.warning(f"build_kb_directory_summary: list_knowledge_bases failed: {e}")
        return ""

    cats = listing.get("categories", []) or []
    if not cats:
        return ""

    total_papers = listing.get("total_papers", 0)
    parts = [f"{c.get('topic') or c.get('name', '')}({c.get('count', 0)})" for c in cats]
    return (f"系统知识库：{len(cats)} 个分类 / {total_papers} 篇论文。"
            f"分类：{'、'.join(parts)}。")


def search_papers_for_citation(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """包装 search_papers，返回带 index 的结构化候选清单。

    异常时返回空列表，不抛出。
    """
    try:
        raw = search_papers(query, top_k=top_k)
    except Exception as e:
        logger.warning(f"search_papers_for_citation: search_papers failed: {e}")
        return []

    result: List[Dict[str, Any]] = []
    for i, p in enumerate(raw, 1):
        authors = p.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        result.append({
            "index": i,
            "paper_id": p.get("paper_id", ""),
            "title": p.get("title", ""),
            "authors": authors,
            "published_date": p.get("published_date", ""),
            "topic": p.get("topic", ""),
            "pdf_url": p.get("pdf_url", ""),
        })
    return result


def format_citation_candidates(papers: List[Dict[str, Any]]) -> str:
    """格式化为 LLM 易读的编号清单。

    格式：'[1] 标题 — 作者1, 作者2 — 2024 — paper_id=xxx'
    """
    if not papers:
        return ""
    lines: List[str] = []
    for p in papers:
        authors = p.get("authors", []) or []
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += ", 等"
        date = p.get("published_date", "") or ""
        year = date[:4] if date else ""
        pid = p.get("paper_id", "")
        lines.append(f"[{p.get('index', '?')}] {p.get('title', '')} — {author_str} — {year} — paper_id={pid}")
    return "\n".join(lines)


def _to_bib_entry(p: Dict[str, Any]) -> Dict[str, Any]:
    """把候选 paper dict 适配成 format_bibliography 期望的 schema。"""
    authors = p.get("authors", []) or []
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(";") if a.strip()]
    date_str = p.get("published_date", "") or ""
    year = ""
    m = _re.search(r"\d{4}", str(date_str))
    if m:
        year = m.group(0)
    return {
        "paper_id": p.get("paper_id", ""),
        "title": p.get("title", ""),
        "authors": authors,
        "year": year,
        "source": p.get("topic", ""),
    }


def format_bibliography_gbt7714(papers: List[Dict[str, Any]]) -> str:
    """GB/T 7714-2015 格式化参考文献目录，复用 workflow.format_bibliography。"""
    if not papers:
        return ""
    entries = [_to_bib_entry(p) for p in papers]
    return format_bibliography(entries)
