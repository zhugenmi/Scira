"""KB 问答 Agent。

封装 KB 问答流程中的两次 LLM 调用：
- synthesize：基于精读结果做信息抽取与整合（阶段 2）
- final_merge：合并补读 PDF 的内容到最终答案（阶段 4）

经 BaseAgent.invoke 调用，token 用量自动计入 TokenTracker。
"""
import json
from typing import Any, Dict, List

from src.agents.base import BaseAgent
from src.agents.prompts import KB_QA_SYNTHESIS_PROMPT, KB_QA_FINAL_PROMPT
from src.utils.logger import get_logger

logger = get_logger("kb_qa")


class KBQAAgent(BaseAgent):
    """KB 问答 Agent。"""

    def __init__(self):
        super().__init__(
            name="kb_qa",
            system_prompt="你是一位科研助手，负责基于知识库论文回答用户的事实性问题。",
        )

    def synthesize(
        self,
        question: str,
        papers_readings: List[Dict[str, Any]],
        kb_name: str = "",
    ) -> Dict[str, Any]:
        """阶段 2：基于精读结果做信息抽取与整合。

        Args:
            question: 用户问题
            papers_readings: [{paper_id, title, markdown, error?}]
            kb_name: 知识库名称（用于 prompt 上下文）

        Returns:
            {synthesis: str, incomplete_papers: List[Dict], search_keywords: List[str]}
            LLM 返回非法 JSON 时降级。
        """
        papers_block = self._format_papers_block(papers_readings)
        prompt = KB_QA_SYNTHESIS_PROMPT.format(
            question=question,
            kb_name=kb_name or "未知",
            paper_count=len(papers_readings),
            papers_block=papers_block,
        )

        try:
            raw = self.invoke(prompt)
        except Exception as e:
            logger.error(f"KBQAAgent.synthesize invoke failed: {e}", exc_info=True)
            return {
                "synthesis": f"整合分析失败：{e}",
                "incomplete_papers": [],
                "search_keywords": [],
            }

        return self._parse_synthesis_response(raw)

    def final_merge(
        self,
        synthesis: str,
        supplementary: List[Dict[str, Any]],
        question: str,
    ) -> str:
        """阶段 4：合并补读 PDF 内容到最终答案。

        Args:
            synthesis: 阶段 2 的初步答案
            supplementary: [{paper_id, title, excerpts: [str], status?}]
                status 可为 "ok" / "not_found" / "no_hit" / "failed"
            question: 用户问题

        Returns:
            合并后的最终答案纯文本。
        """
        supplementary_block = self._format_supplementary_block(supplementary)
        prompt = KB_QA_FINAL_PROMPT.format(
            question=question,
            synthesis=synthesis,
            supplementary_block=supplementary_block,
        )

        try:
            return self.invoke(prompt)
        except Exception as e:
            logger.error(f"KBQAAgent.final_merge invoke failed: {e}", exc_info=True)
            return synthesis

    def _format_papers_block(self, papers_readings: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for i, p in enumerate(papers_readings, 1):
            pid = p.get("paper_id", "")
            title = p.get("title", "")
            md = p.get("markdown", "")
            err = p.get("error")
            if err:
                parts.append(f"--- 论文 {i} ---\npaper_id: {pid}\ntitle: {title}\n精读失败: {err}\n")
            else:
                parts.append(f"--- 论文 {i} ---\npaper_id: {pid}\ntitle: {title}\n精读结果:\n{md}\n")
        return "\n".join(parts)

    def _format_supplementary_block(self, supplementary: List[Dict[str, Any]]) -> str:
        if not supplementary:
            return "（无补读内容）"
        parts: List[str] = []
        for s in supplementary:
            pid = s.get("paper_id", "")
            title = s.get("title", "")
            status = s.get("status", "ok")
            excerpts = s.get("excerpts", [])
            if status == "not_found":
                parts.append(f"--- {title} ({pid}) ---\nPDF 不存在，补读失败。\n")
            elif status == "no_hit":
                parts.append(f"--- {title} ({pid}) ---\n关键词未命中，无补读内容。\n")
            elif status == "failed":
                parts.append(f"--- {title} ({pid}) ---\nPDF 解析失败。\n")
            elif not excerpts:
                parts.append(f"--- {title} ({pid}) ---\n无补读内容。\n")
            else:
                joined = "\n...\n".join(excerpts)
                parts.append(f"--- {title} ({pid}) ---\n{joined}\n")
        return "\n".join(parts)

    def _parse_synthesis_response(self, raw: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON，失败时降级。"""
        text = raw.strip()
        # 处理 markdown 代码块
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        text = text.strip()

        try:
            data = json.loads(text)
            return {
                "synthesis": str(data.get("synthesis", "")),
                "incomplete_papers": list(data.get("incomplete_papers", [])),
                "search_keywords": list(data.get("search_keywords", [])),
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"KBQAAgent synthesize JSON parse failed: {e}, raw={raw[:200]}")
            return {
                "synthesis": raw,
                "incomplete_papers": [],
                "search_keywords": [],
            }