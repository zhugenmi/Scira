"""
Scira Paper Info Extractor

使用 LLM 从论文全文中提取结构化信息（标题、作者、摘要、DOI 等），
替代原有的字号分析启发式方法。
"""

import json
import re

from src.agents.base import BaseAgent
from src.utils.logger import logger

EXTRACTOR_SYSTEM_PROMPT = """你是一个学术论文信息提取助手。从用户提供的论文全文中提取结构化信息。

规则：
1. 只提取能从文本中确认的信息，不确定的字段填 null，不要编造
2. abstract 保留原文，不要截断或改写
3. authors 数组每项格式："姓名 (机构名)"，机构可从作者脚注或首页标注提取
4. 标题保留原文语言，中文标题填 title 字段，英文标题填 title_en
5. 关键词保留原文"""

EXTRACTOR_USER_PROMPT = """从以下论文全文的前8000字符中提取结构化信息，返回纯JSON（不要markdown代码块）：

{{
  "title": "论文标题",
  "title_zh": "中文译名（英文论文时翻译，中文论文则为null）",
  "title_en": "英文标题（中文论文时翻译，英文论文则为null）",
  "authors": ["作者1 (机构)", "作者2 (机构)"],
  "abstract": "摘要原文，不要截断",
  "keywords": ["关键词1", "关键词2"],
  "doi": "DOI号（没有则为null）",
  "journal": "期刊/会议名称",
  "year": 2024,
  "volume": "卷号",
  "issue": "期号",
  "pages": "页码"
}}

论文文本：
{text}"""


class PaperInfoExtractor:
    """使用 LLM 从论文文本中提取结构化信息。"""

    def __init__(self):
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            self._agent = BaseAgent(
                name="PaperInfoExtractor",
                system_prompt=EXTRACTOR_SYSTEM_PROMPT,
            )
        return self._agent

    @agent.setter
    def agent(self, value):
        self._agent = value

    @property
    def llm(self):
        return self.agent.llm

    @llm.setter
    def llm(self, value):
        self._agent = BaseAgent(
            name="PaperInfoExtractor",
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
        )
        self._agent.llm = value

    def extract(self, full_text: str, max_chars: int = 8000) -> dict:
        """
        从论文全文中提取结构化信息。

        Args:
            full_text: 论文全文文本。
            max_chars: 送入 LLM 的最大字符数（取前 N 字符）。

        Returns:
            dict 包含 title, authors, abstract, keywords, doi,
            journal, year, volume, issue, pages, metadata_quality。
        """
        trimmed = full_text[:max_chars]
        prompt = EXTRACTOR_USER_PROMPT.format(text=trimmed)

        for attempt in range(2):
            try:
                raw = self.agent.invoke(prompt)
                parsed = self._parse_response(raw)
                parsed["metadata_quality"] = "llm_extracted"
                return parsed
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(
                    f"LLM 提取第 {attempt + 1} 次失败: {e}"
                )
                if attempt == 0:
                    # 重试时追加格式提示
                    prompt = prompt + "\n\n请务必只返回纯JSON，不要用markdown代码块包裹。"

        # 两次尝试均失败，返回默认值
        logger.error("LLM 结构化提取失败，返回默认值")
        return {
            "title": "",
            "title_zh": None,
            "title_en": None,
            "authors": [],
            "abstract": "",
            "keywords": [],
            "doi": None,
            "journal": None,
            "year": None,
            "volume": None,
            "issue": None,
            "pages": None,
            "metadata_quality": "partial",
        }

    def _parse_response(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON，处理可能的 markdown 代码块包裹。"""
        # 去掉可能的 markdown 代码块
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        result = json.loads(cleaned)

        # 标准化字段，填入默认值
        return {
            "title": str(result.get("title") or "").strip(),
            "title_zh": result.get("title_zh"),
            "title_en": result.get("title_en"),
            "authors": result.get("authors") or [],
            "abstract": str(result.get("abstract") or "").strip(),
            "keywords": result.get("keywords") or [],
            "doi": result.get("doi"),
            "journal": result.get("journal"),
            "year": result.get("year"),
            "volume": result.get("volume"),
            "issue": result.get("issue"),
            "pages": result.get("pages"),
        }
