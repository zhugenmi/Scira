"""
单章节子任务执行器

当用户只说「生成摘要 / 生成引言 / 生成结论」时，由 Orchestrator 调用本模块，
基于会话内最近一次工作流结果或最近上传的论文，直接产出对应章节，不触发完整
检索→阅读→写作→审查工作流。

设计原则：
- 复用 ReviewerAgent 的 prompt 与引用指令构造逻辑，不重新发明。
- 支持 on_token 回调：SSE 端点传入后，LLM token 边生成边推送，首字延迟≈TTFB。
- 上下文解析失败时抛 ValueError，由调用方友好提示，绝不静默兜底到 full_research。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_config, get_llm_client
from src.utils.logger import logger, record_token_usage
from src.agents.prompts import (
    WRITER_ABSTRACT_PROMPT,
    WRITER_INTRO_PROMPT,
    WRITER_CONCLUSION_PROMPT,
    WRITER_SYSTEM,
)
from src.agents.reviewer import _build_citation_instruction


@dataclass
class WritingContext:
    """子任务生成所需的上下文。"""
    source: str  # "workflow" | "paper"
    topic: str
    paper_content: str
    global_knowledge: Optional[Dict[str, Any]] = None
    reference_list: Optional[list] = None


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _find_paper_pdf(paper_id: Optional[str]) -> Optional[Path]:
    """在 data/papers/ 下按 paper_id 查找论文 PDF。

    结构：data/papers/<category>/<paper_id>/original.pdf 或 <paper_id>.pdf；
    上传论文在 data/papers/_uploads/<paper_id>/original.pdf。
    无 paper_id 时返回最近修改的 PDF。
    """
    papers_dir = _project_root() / "data" / "papers"
    if not papers_dir.exists():
        return None

    if paper_id:
        for topic_dir in papers_dir.iterdir():
            if not topic_dir.is_dir():
                continue
            paper_dir = topic_dir / paper_id
            if not paper_dir.is_dir():
                continue
            for name in ("original.pdf", f"{paper_id}.pdf"):
                cand = paper_dir / name
                if cand.exists():
                    return cand
        return None

    # 无 paper_id：扫所有 per-paper 目录取最近修改的 PDF
    candidates: list = []
    for topic_dir in papers_dir.iterdir():
        if not topic_dir.is_dir():
            continue
        for paper_dir in topic_dir.iterdir():
            if not paper_dir.is_dir():
                continue
            for pdf in paper_dir.glob("*.pdf"):
                if pdf.exists():
                    candidates.append(pdf)
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _try_paper_context(paper_id: Optional[str]) -> Optional[WritingContext]:
    """从 data/papers/<category>/<paper_id>/ 下的 PDF 构建单篇论文上下文。

    无 paper_id 时取最近修改的论文。解析失败返回 None。
    """
    pdf_path = _find_paper_pdf(paper_id)
    if not pdf_path:
        return None

    paper_dir = pdf_path.parent
    title = ""
    meta_path = paper_dir / "metadata.json"
    if meta_path.exists():
        try:
            title = (json.loads(meta_path.read_text(encoding="utf-8")) or {}).get("title", "")
        except Exception:
            pass

    try:
        from src.tools.pdf_parser import PDFParser, ParserBackend
        parser = PDFParser(backend=ParserBackend.PYMUPDF)
        paper_id = paper_id or paper_dir.name
        parsed = parser.parse(str(pdf_path), paper_id, extract_sections=True)
    except Exception as e:
        logger.warning(f"writing_tasks: parse paper failed: {e}")
        return None

    # 拼接主要章节内容作为 paper_content
    parts = []
    if parsed.abstract:
        parts.append(parsed.abstract)
    for name, content in (parsed.sections or {}).items():
        parts.append(f"## {name}\n{content}")
    if not parts and parsed.raw_text:
        parts.append(parsed.raw_text)
    paper_content = "\n\n".join(parts)[:12000]

    if not title:
        title = parsed.title or pdf_path.parent.name

    return WritingContext(
        source="paper",
        topic=title,
        paper_content=paper_content,
        global_knowledge=None,
        reference_list=None,
    )


def _try_workflow_context(session_id: str) -> Optional[WritingContext]:
    """从会话最近一次工作流结果构建上下文。

    依赖 memory_manager.update_research_context 存储的 research_results[topic]，
    其 value 是完整 workflow_result dict（含 final_review / final_paper / outline /
    global_knowledge / reference_list / literature_data）。
    """
    try:
        from src.core.memory import memory_manager
    except Exception:
        return None

    session = memory_manager.get_session(session_id)
    if not session:
        return None

    research_results = (session.context.research_results if hasattr(session.context, "research_results") else {}) or {}
    if not research_results:
        return None

    # 取最后一个 topic 的结果（dict 插入顺序保持）
    topic = next(reversed(research_results))
    result = research_results[topic] or {}

    # 正文优先 final_review，回退 final_paper，再回退 chapter_drafts 拼接
    paper_content = (
        result.get("final_review")
        or result.get("final_paper")
        or ""
    )
    if not paper_content:
        drafts = result.get("chapter_drafts") or {}
        if isinstance(drafts, dict):
            paper_content = "\n\n".join(
                (d.get("content") if isinstance(d, dict) else str(d))
                for d in drafts.values()
            )

    if not paper_content:
        return None

    outline = result.get("outline") or {}
    if isinstance(outline, dict):
        topic_title = outline.get("title") or topic
    else:
        topic_title = topic

    return WritingContext(
        source="workflow",
        topic=topic_title,
        paper_content=paper_content[:12000],
        global_knowledge=result.get("global_knowledge"),
        reference_list=result.get("reference_list"),
    )


def resolve_writing_context(
    session_id: Optional[str] = None,
    paper_id_hint: Optional[str] = None,
) -> WritingContext:
    """
    解析子任务生成上下文。

    优先级：
    1. paper_id_hint 指定的上传论文（聊天里"为这篇论文生成..."）
    2. 会话最近一次工作流结果
    3. 最近上传的论文（无 hint 时扫描 data/papers/ 下 per-paper 目录）

    都没有则抛 ValueError，调用方应回复用户「请先做一次研究或上传一篇论文」。
    """
    if paper_id_hint:
        ctx = _try_paper_context(paper_id_hint)
        if ctx:
            return ctx

    if session_id:
        ctx = _try_workflow_context(session_id)
        if ctx:
            return ctx

    ctx = _try_paper_context(None)
    if ctx:
        return ctx

    raise ValueError("无可用上下文：会话内尚未有工作流结果，也未上传过论文。请先做一次研究或上传一篇 PDF。")


def _build_messages(section: str, ctx: WritingContext):
    """构造 SystemMessage + HumanMessage，复用 ReviewerAgent 的 prompt 逻辑。"""
    global_knowledge_json = (
        json.dumps(ctx.global_knowledge, indent=2, ensure_ascii=False)
        if ctx.global_knowledge else "{}"
    )

    if section == "abstract":
        prompt = WRITER_ABSTRACT_PROMPT.format(
            title=ctx.topic,
            content=ctx.paper_content[:4000],
        )
    elif section == "introduction":
        prompt = WRITER_INTRO_PROMPT.format(
            title=ctx.topic,
            topic=ctx.topic,
            global_knowledge=global_knowledge_json,
        ) + _build_citation_instruction(ctx.reference_list)
    elif section == "conclusion":
        prompt = WRITER_CONCLUSION_PROMPT.format(
            title=ctx.topic,
            content=ctx.paper_content[:4000],
            global_knowledge=global_knowledge_json,
        ) + _build_citation_instruction(ctx.reference_list)
    else:
        raise ValueError(f"unsupported section: {section}")

    return [SystemMessage(content=WRITER_SYSTEM), HumanMessage(content=prompt)]


def generate_partial(
    section: str,
    ctx: WritingContext,
    on_token: Optional[Callable[[str], None]] = None,
) -> str:
    """
    生成单个章节（abstract / introduction / conclusion）。

    Args:
        section: "abstract" | "introduction" | "conclusion"
        ctx: resolve_writing_context 返回的上下文
        on_token: 流式回调，每收到一个 token chunk 调用一次。传入时使用 llm.stream，
                  否则使用 llm.invoke（同步）。

    Returns:
        完整章节文本（已 strip）。
    """
    config = get_config()
    llm = get_llm_client(config)
    model_name = config.model.model_name or "gpt-4o"
    messages = _build_messages(section, ctx)

    pieces: list = []

    if on_token is None:
        response = llm.invoke(messages)
        record_token_usage(response, model_name)
        return response.content.strip()

    # 流式：优先 llm.stream；provider 不支持时降级到 invoke + 单次 on_token
    try:
        for chunk in llm.stream(messages):
            text = getattr(chunk, "content", None)
            if not text:
                continue
            pieces.append(text)
            try:
                on_token(text)
            except Exception as e:
                logger.debug(f"writing_tasks on_token callback error: {e}")
    except (NotImplementedError, AttributeError, TypeError) as e:
        logger.warning(f"writing_tasks: llm.stream unsupported ({e}), fallback to invoke")
        response = llm.invoke(messages)
        record_token_usage(response, model_name)
        text = response.content
        pieces.append(text)
        try:
            on_token(text)
        except Exception:
            pass
        return text.strip()

    full = "".join(pieces)
    # 流式下 record_token_usage 需要一个 AIMessage-like 对象；构造一个轻量载体
    try:
        from langchain_core.messages import AIMessage
        record_token_usage(AIMessage(content=full), model_name)
    except Exception as e:
        logger.debug(f"writing_tasks: record_token_usage on stream failed: {e}")

    return full.strip()
