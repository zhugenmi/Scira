"""
Scira Chat Tools

把知识库查询与论文精读功能暴露为 LangChain tools，让 LLM 自主决策调用时机。
替代早期基于关键词/正则匹配的 `_detect_paper_reading_request` 硬编码路由。

设计要点：
- `list_knowledge_bases` / `list_papers_in_kb` 是纯查询工具，返回 JSON 字符串供 LLM
  组织自然语言回复。
- `read_paper` / `batch_read_papers_in_kb` 是流式工具：tool 函数本身在 tools.py 里
  只做参数校验与论文定位，真正的精读流式由 server.py 的路由层拦截后调用
  `_stream_paper_reading_in_chat` / `_stream_batch_reading_in_chat` 完成。这样既能
  把 markdown token 直接推到 SSE（不经 LLM 二次加工，避免上下文膨胀），又能让
  LLM 知道"工具已执行完毕"从而给出收尾文本。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from src.core.knowledge import list_knowledge_bases as _list_knowledge_bases
from src.utils.logger import get_logger

logger = get_logger("tools")


# ==================== KB 查询工具 ====================

@tool
def list_knowledge_bases() -> str:
    """列出系统中所有知识库及其论文数量。

    当用户问"有哪些知识库"、"知识库列表"、"系统里都装了什么论文"等枚举性问题时调用。
    返回 JSON 字符串，包含 categories（每个分类含 name/topic/count/papers 前 5 篇）、
    total_papers、total_categories。
    """
    try:
        result = _list_knowledge_bases()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"list_knowledge_bases tool failed: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def list_papers_in_kb(kb_name: str) -> str:
    """列出指定知识库中的所有论文信息（标题、作者、发表日期、paper_id 等）。

    当用户问"X 知识库有哪些论文"、"列举 X 知识库的论文"、"X 里都装了什么"时调用。
    支持中文 topic 名（如"多源数据融合"）或英文目录名（如"knowledge_graph"），
    大小写不敏感、子串匹配。未匹配到时返回 suggestions 列出所有可用 KB 名供用户选择。

    Args:
        kb_name: 知识库名称，支持中文 topic 或英文目录名
    """
    if not kb_name or not kb_name.strip():
        return json.dumps(
            {"matched": False, "error": "kb_name 不能为空", "suggestions": []},
            ensure_ascii=False,
        )

    try:
        listing = _list_knowledge_bases()
    except Exception as e:
        logger.error(f"list_papers_in_kb: list_knowledge_bases failed: {e}", exc_info=True)
        return json.dumps({"matched": False, "error": str(e)}, ensure_ascii=False)

    cats = listing.get("categories", []) or []
    query = kb_name.strip().lower()

    # 优先精确匹配（topic 或 name），其次子串匹配
    exact_match: Optional[Dict[str, Any]] = None
    fuzzy_matches: List[Dict[str, Any]] = []
    for c in cats:
        topic = (c.get("topic") or "").lower()
        name = (c.get("name") or "").lower()
        if topic == query or name == query:
            exact_match = c
            break
        if query in topic or query in name or topic in query or name in query:
            fuzzy_matches.append(c)

    target = exact_match or (fuzzy_matches[0] if fuzzy_matches else None)
    if target is None:
        suggestions = [
            {"name": c.get("name", ""), "topic": c.get("topic", ""), "count": c.get("count", 0)}
            for c in cats
        ]
        return json.dumps(
            {
                "matched": False,
                "kb_name": kb_name,
                "error": f"未找到名为「{kb_name}」的知识库",
                "suggestions": suggestions,
            },
            ensure_ascii=False,
        )

    papers: List[Dict[str, Any]] = []
    for p in target.get("papers") or []:
        authors = p.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        papers.append({
            "paper_id": p.get("paper_id", ""),
            "title": p.get("title", ""),
            "authors": authors,
            "published_date": p.get("published_date", ""),
        })

    return json.dumps(
        {
            "matched": True,
            "kb_name": kb_name,
            "name": target.get("name", ""),
            "topic": target.get("topic", ""),
            "count": len(papers),
            "papers": papers,
        },
        ensure_ascii=False,
    )


# ==================== 论文精读工具（流式，由路由层拦截执行） ====================

@tool
def read_paper(title_or_id: str, mode: str = "snap", language: str = "zh") -> str:
    """以指定模式精读单篇论文，返回结构化 markdown 分析。

    当用户问"用 X 模式阅读论文 Y"、"精读一下 Y"、"速览 Y"时调用。论文标题支持模糊
    匹配（不要求完整标题），也可传 paper_id 精确定位。

    Args:
        title_or_id: 论文标题（支持模糊匹配）或 paper_id
        mode: 阅读模式 - "snap"(30秒速览) / "lens"(深度精读) / "sphere"(研究全景)
        language: 输出语言 - "zh" / "en"
    """
    # 此函数仅做参数校验。实际精读流式由 server.py 的 tool-calling 路由拦截后调用
    # _stream_paper_reading_in_chat 完成，markdown token 直接推到 SSE。
    # 工具返回值仅用于 LLM 收尾（已被路由层替换为执行结果摘要）。
    if mode not in ("snap", "lens", "sphere", "qa"):
        return json.dumps(
            {"error": f"无效的 mode: {mode}，支持 snap/lens/sphere/qa"},
            ensure_ascii=False,
        )
    return json.dumps(
        {"status": "streaming", "title_or_id": title_or_id, "mode": mode, "language": language},
        ensure_ascii=False,
    )


@tool
def batch_read_papers_in_kb(kb_name: str, mode: str = "snap") -> str:
    """批量精读指定知识库中所有有 PDF 的论文，逐篇生成 markdown 分析。

    当用户问"用 X 模式阅读 Y 知识库所有论文"、"批量精读 Y"、"给 Y 知识库的论文都做个速览"时调用。
    逐篇流式推送结果到聊天界面，自动跳过没有 PDF 的论文并报告数量。

    Args:
        kb_name: 知识库名称，支持中文 topic 或英文目录名
        mode: 阅读模式 - "snap" / "lens" / "sphere"
    """
    if mode not in ("snap", "lens", "sphere"):
        return json.dumps(
            {"error": f"无效的 mode: {mode}，批量精读支持 snap/lens/sphere"},
            ensure_ascii=False,
        )
    return json.dumps(
        {"status": "streaming", "kb_name": kb_name, "mode": mode},
        ensure_ascii=False,
    )


@tool
def generate_section_from_kb(
    kb_name: str,
    section_topic: str,
    constraints: str = "",
) -> str:
    """基于指定知识库的所有论文撰写某个学术章节，强制引用全部论文。

    当用户说"根据 X 知识库写 Y 章节"、"基于 X 库写 Y"、"用 X 库的论文写 Y"
    （Y 可以是"国内外研究现状"/"研究背景"/"相关工作"/"技术路线"等任意章节）时调用。
    会强制引用 KB 中所有论文，正文用 [1][2][3]... 角标按序引用，文末附 GB/T 7714
    参考文献目录。**不要**在用户想要新检索/调研时调用此工具（那应走研究工作流）。

    Args:
        kb_name: 知识库名称，支持中文 topic 或英文目录名
        section_topic: 章节主题/名称，如"国内外研究现状"、"研究背景"、"相关工作"
        constraints: 写作约束，如"不超过3段文字"、"500字以内"。无约束时传空字符串
    """
    if not section_topic or not section_topic.strip():
        return json.dumps(
            {"error": "section_topic 不能为空，需指明要写的章节/主题"},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "status": "streaming",
            "kb_name": kb_name,
            "section_topic": section_topic,
            "constraints": constraints or "",
        },
        ensure_ascii=False,
    )


@tool
def answer_question_from_kb(kb_name: str, question: str) -> str:
    """针对知识库内容的事实性问答。

    当用户针对某个已有知识库提问，且不是要求"阅读/精读/写章节/列举清单"时调用。
    内部流程：全库 lens 精读 -> LLM 整合抽取 -> 信息不全时补读 PDF -> 合并输出。
    只返回最终整合答案，不逐篇展示精读结果。

    例：
    - "X 知识库里哪些论文用了公开数据集"
    - "X 库中 Y 论文用了什么方法"
    - "X 知识库哪些论文是 2023 年的"

    Args:
        kb_name: 知识库名称，支持中文 topic 或英文目录名
        question: 用户针对该知识库内容提出的问题
    """
    if not question or not question.strip():
        return json.dumps(
            {"error": "question 不能为空，需指明要问的问题"},
            ensure_ascii=False,
        )
    return json.dumps(
        {"status": "streaming", "kb_name": kb_name, "question": question},
        ensure_ascii=False,
    )


# ==================== 工具注册表 ====================

def get_kb_reading_tools() -> List[Any]:
    """返回聊天路由用的全部工具列表，供 BaseAgent.invoke_with_tools() 绑定到 LLM。"""
    return [
        list_knowledge_bases,
        list_papers_in_kb,
        read_paper,
        batch_read_papers_in_kb,
        generate_section_from_kb,
        answer_question_from_kb,
    ]


# 路由层用：根据 tool name 拿到可执行函数
_TOOL_FUNCTIONS = {
    "list_knowledge_bases": list_knowledge_bases,
    "list_papers_in_kb": list_papers_in_kb,
    "read_paper": read_paper,
    "batch_read_papers_in_kb": batch_read_papers_in_kb,
    "generate_section_from_kb": generate_section_from_kb,
    "answer_question_from_kb": answer_question_from_kb,
}


def get_tool_by_name(name: str):
    """根据工具名拿到 LangChain tool 对象，找不到返回 None。"""
    return _TOOL_FUNCTIONS.get(name)
