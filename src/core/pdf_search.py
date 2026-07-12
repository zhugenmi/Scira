"""PDF 关键词全文搜索模块。

用于 KB 问答工具的「补读 PDF」阶段：当 lens 精读结果信息不全时，
按 LLM 生成的关键词在 PDF 全文搜索，定位相关段落补读。
"""
from pathlib import Path
from typing import List

from src.utils.logger import get_logger

logger = get_logger("pdf_search")


def _extract_pdf_text(pdf_path: Path) -> str:
    """用 pymupdf (fitz) 提取 PDF 全文文本。失败返回空串。"""
    try:
        import fitz
    except ImportError:
        logger.error("pymupdf not installed")
        return ""
    try:
        parts: List[str] = []
        doc = fitz.open(str(pdf_path))
        for page in doc:
            text = page.get_text() or ""
            parts.append(text)
        doc.close()
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"pymupdf failed on {pdf_path}: {e}")
        return ""


def search_pdf_for_keywords(
    pdf_path: Path,
    keywords: List[str],
    window: int = 500,
    max_excerpts: int = 5,
) -> List[str]:
    """按关键词在 PDF 全文搜索，返回命中段落。

    每个命中位置取前后各 window 字符作为 excerpt，多个命中合并去重，
    最多返回 max_excerpts 个。无命中或 PDF 不可读时返回空列表。

    Args:
        pdf_path: PDF 文件路径
        keywords: 关键词列表，大小写不敏感
        window: 每个命中位置前后保留的字符数
        max_excerpts: 最多返回的 excerpt 数量
    """
    if not keywords:
        return []
    if not Path(pdf_path).exists():
        logger.warning(f"PDF not found: {pdf_path}")
        return []

    text = _extract_pdf_text(Path(pdf_path))
    if not text:
        return []

    text_lower = text.lower()
    keywords_lower = [kw.lower() for kw in keywords if kw.strip()]
    if not keywords_lower:
        return []

    hits: List[int] = []
    for kw in keywords_lower:
        start = 0
        while True:
            idx = text_lower.find(kw, start)
            if idx == -1:
                break
            hits.append(idx)
            start = idx + len(kw)

    if not hits:
        return []

    hits.sort()
    excerpts: List[str] = []
    seen_ranges: List[tuple] = []
    for idx in hits:
        lo = max(0, idx - window)
        hi = min(len(text), idx + window)
        # 跟既有 excerpt 重叠则合并（跳过）
        overlapped = False
        for (elo, ehi) in seen_ranges:
            if lo < ehi and hi > elo:
                overlapped = True
                break
        if overlapped:
            continue
        seen_ranges.append((lo, hi))
        excerpts.append(text[lo:hi])
        if len(excerpts) >= max_excerpts:
            break

    return excerpts