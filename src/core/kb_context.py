"""
知识库上下文构建模块。

供 AI 报告编辑流程与 Orchestrator 普通对话路径共用，把 KB 状态注入 LLM 上下文。
"""
from src.core.knowledge import list_knowledge_bases
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
