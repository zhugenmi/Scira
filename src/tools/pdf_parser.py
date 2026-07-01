"""
Scira PDF Parser Module

Provides PDF parsing and information extraction functionality.
Supports multiple PDF libraries and text extraction strategies.
"""

import os
import re
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass
from enum import Enum

import fitz  # PyMuPDF
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from langsmith import traceable

# Import logging
from src.utils.logger import logger


class ParserBackend(str, Enum):
    """PDF parser backend options."""
    PYMUPDF = "pymupdf"  # Faster, better for text extraction
    PYPDF = "pypdf"      # More compatible


@dataclass
class ParsedPaper:
    """Parsed paper content structure."""
    paper_id: str
    title: str
    authors: List[str]
    abstract: str
    sections: Dict[str, str]
    references: List[str]
    tables: List[Dict[str, Any]]
    figures: List[Dict[str, Any]]
    raw_text: str
    word_count: int
    metadata: Dict[str, Any]


class PDFParser:
    """
    PDF parser for scientific papers.

    Features:
    - Multi-backend support (PyMuPDF, pypdf)
    - Section extraction
    - Reference parsing
    - Table and figure extraction
    - Text cleaning and normalization
    """

    def __init__(
        self,
        backend: ParserBackend = ParserBackend.PYMUPDF,
        cache_dir: str = "data/cache",
    ):
        """
        Initialize PDF parser.

        Args:
            backend: PDF parsing backend
            cache_dir: Directory for caching parsed results
        """
        self.backend = backend
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        logger.debug(f"PDFParser initialized | Backend: {backend}")

    @traceable(name="pdf_parse")
    def parse(
        self,
        pdf_path: str,
        paper_id: str,
        extract_sections: bool = True,
    ) -> ParsedPaper:
        """
        Parse a PDF file.

        Args:
            pdf_path: Path to PDF file
            paper_id: Paper identifier
            extract_sections: Whether to extract sections

        Returns:
            ParsedPaper object
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        if self.backend == ParserBackend.PYMUPDF:
            return self._parse_pymupdf(pdf_path, paper_id, extract_sections)
        else:
            return self._parse_pypdf(pdf_path, paper_id, extract_sections)

    def _parse_pymupdf(
        self,
        pdf_path: str,
        paper_id: str,
        extract_sections: bool,
    ) -> ParsedPaper:
        """Parse using PyMuPDF."""
        doc = fitz.open(pdf_path)

        # Extract metadata
        metadata = doc.metadata
        # 优先用字号分析提取标题；PDF info dict 的 title 常为文件名或空，仅作兜底
        title = self._extract_title_from_first_page(doc)
        if title == "Unknown":
            meta_title = (metadata.get("title") or "").strip()
            if meta_title and "_" not in meta_title and not re.search(r"\.pdf$", meta_title, re.I):
                title = meta_title
        authors = self._extract_authors(doc)

        # Extract text
        all_text = ""
        for page in doc:
            all_text += page.get_text()

        # Extract abstract
        abstract = self._extract_abstract(all_text)

        # Extract sections
        sections = {}
        if extract_sections:
            sections = self._extract_sections(all_text)

        # Extract references
        references = self._extract_references(all_text)

        # Extract tables and figures (before closing doc!)
        tables, figures = self._extract_tables_figures(doc)

        # Clean text
        raw_text = self._clean_text(all_text)

        # Close document AFTER all operations
        doc.close()

        return ParsedPaper(
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=abstract,
            sections=sections,
            references=references,
            tables=tables,
            figures=figures,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            metadata=metadata,
        )

    def _parse_pypdf(
        self,
        pdf_path: str,
        paper_id: str,
        extract_sections: bool,
    ) -> ParsedPaper:
        """Parse using pypdf."""
        reader = PdfReader(pdf_path)

        # Extract metadata
        metadata = reader.metadata or {}
        # 优先用 info dict，但 info 里的 title 常为文件名，需校验
        meta_title = (metadata.get("/Title") or "").strip()
        meta_author = (metadata.get("/Author") or "").strip()

        # Extract text
        all_text = ""
        for page in reader.pages:
            all_text += page.extract_text() or ""

        # 标题：info dict 的 title 若不像文件名则用之，否则文本启发式
        def _looks_like_filename(t: str) -> bool:
            return bool(t) and (
                "_" in t or
                re.search(r"\.pdf$", t, re.I) or
                re.fullmatch(r"[\d_\- ]+", t)
            )

        if meta_title and not _looks_like_filename(meta_title):
            title = meta_title
        else:
            lines = [ln.strip() for ln in all_text.split("\n") if ln.strip()]
            title = "Unknown"
            for ln in lines[:8]:
                if len(ln) > 10 and not ln.isupper() and "@" not in ln:
                    title = ln
                    break

        # 作者：info dict 优先，否则文本启发式
        if meta_author and "@" not in meta_author:
            authors = [a.strip() for a in re.split(r"[,;]", meta_author) if a.strip()]
        else:
            authors = self._extract_authors_from_text(all_text)

        # Extract abstract
        abstract = self._extract_abstract(all_text)

        # Extract sections
        sections = {}
        if extract_sections:
            sections = self._extract_sections(all_text)

        # Extract references
        references = self._extract_references(all_text)

        # Tables and figures (limited in pypdf)
        tables = []
        figures = []

        # Clean text
        raw_text = self._clean_text(all_text)

        return ParsedPaper(
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=abstract,
            sections=sections,
            references=references,
            tables=tables,
            figures=figures,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            metadata=metadata,
        )

    def _extract_title_from_first_page(self, doc) -> str:
        """Extract title from first page using font-size analysis.

        标题通常是首页字号最大的文本块。用 get_text("dict") 拿到 span 级别的
        字号信息，按字号分组，取最大字号对应的连续 span 拼接。过滤会议横幅、
        arXiv 预印本标记、邮箱等噪声。
        """
        if len(doc) == 0:
            return "Unknown"

        first_page = doc[0]
        try:
            page_dict = first_page.get_text("dict")
        except Exception:
            page_dict = None

        if page_dict:
            spans = []
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # 0 = 文本块
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue
                        spans.append({
                            "text": text,
                            "size": round(span.get("size", 0), 1),
                            "flags": span.get("flags", 0),
                        })
            if spans:
                # 跳过明显噪声行
                noise_markers = (
                    "@", "arxiv", "arxiv:", "preprint", "submitted to",
                    "vol.", "volume", "proceedings of", "ieee", "acm",
                    "doi:", "http", "www.", ".org", ".edu",
                )
                def _is_noise(t: str) -> bool:
                    tl = t.lower()
                    if any(m in tl for m in noise_markers):
                        return True
                    # 纯数字或纯日期
                    if re.fullmatch(r"[\d\s/\-:.]+", t):
                        return True
                    # 太短
                    if len(t) < 5:
                        return True
                    return False

                candidates = [s for s in spans if not _is_noise(s["text"])]
                if candidates:
                    max_size = max(s["size"] for s in candidates)
                    # 容差 0.5：同一标题不同 span 字号可能略差
                    top = [s for s in candidates if s["size"] >= max_size - 0.5]
                    # 按 y 位置已天然有序（spans 顺序即阅读顺序），直接拼接
                    title = " ".join(s["text"] for s in top)
                    title = re.sub(r"\s+", " ", title).strip()
                    # 去掉尾部多余标点
                    title = title.rstrip(".,;:")
                    if len(title) >= 5:
                        return title

        # 兜底：纯文本启发式（pypdf 路径或 dict 失败时）
        text = first_page.get_text()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        for line in lines[:8]:
            if len(line) > 10 and not line.isupper() and "@" not in line:
                return line
        return "Unknown"

    def _extract_authors(self, doc) -> List[str]:
        """Extract authors from metadata or first-page text heuristics.

        多数 PDF 的 info dict 里 author 字段为空或为机构名。先用 metadata，
        再在首页标题与摘要之间找作者行：含多个逗号分隔的 capitalized token、
        无数字（年份除外）、无 @ 的行最可能是作者列表。
        """
        metadata = doc.metadata or {}
        authors_str = (metadata.get("author") or "").strip()
        if authors_str and "@" not in authors_str:
            authors = [a.strip() for a in re.split(r"[,;]", authors_str) if a.strip()]
            if authors:
                return authors

        if len(doc) == 0:
            return []
        return self._extract_authors_from_text(doc[0].get_text())

    def _extract_authors_from_text(self, text: str) -> List[str]:
        """从首页纯文本里启发式抽取作者列表（pypdf 路径共用）。"""
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        # 在标题之后、摘要之前找候选作者行
        abstract_idx = -1
        for i, ln in enumerate(lines):
            if re.match(r"^(Abstract|ABSTRACT|摘\s*要|Summary)\b", ln):
                abstract_idx = i
                break
        search_end = abstract_idx if abstract_idx > 0 else min(len(lines), 12)
        # 标题一般在第 1-3 行，作者在其下方
        start = 1 if len(lines) > 1 else 0

        for ln in lines[start:search_end]:
            # 跳过含 @ / 纯数字 / arXiv 标记 / 机构关键词
            low = ln.lower()
            if "@" in ln or "arxiv" in low or "preprint" in low:
                continue
            if "university" in low or "institute" in low or "department" in low:
                continue
            if "abstract" in low or "摘" in ln:
                continue
            # 作者行：含至少一个逗号、token 多为 capitalized、数字占比低
            if "," not in ln and " and " not in ln.lower():
                continue
            # 剥离机构标注符号
            cleaned = re.sub(r"[†*†‡\d]", "", ln)
            # 按逗号/分号/and 分割
            parts = re.split(r"[,;]|\band\b", cleaned)
            names = [p.strip() for p in parts if p.strip()]
            # 校验：每个 name 至少 2 字符、首字母大写或中文
            def _looks_like_name(n: str) -> bool:
                if len(n) < 2:
                    return False
                if re.search(r"[一-龥]", n):
                    return True
                # 英文名：首字母大写
                return bool(re.match(r"^[A-Z][A-Za-z.\-'\s]+$", n))

            names = [n for n in names if _looks_like_name(n)]
            if len(names) >= 1:
                return names[:20]
        return []

    def _extract_abstract(self, text: str) -> str:
        """Extract abstract from paper text with extended boundary patterns."""
        # 起始标记：Abstract / ABSTRACT / 摘 要 / 摘要 / Summary
        # 结束标记：Keywords / Index Terms / 1. Introduction / 1 Introduction /
        #          I. Introduction / 1 章节号 / 连续两空行
        start_patterns = [
            r"(?:^|\n)\s*(?:Abstract|ABSTRACT)\s*[:\.。\—\-—]?\s*",
            r"(?:^|\n)\s*摘\s*要\s*[:：]?\s*",
            r"(?:^|\n)\s*Summary\s*[:\.]?\s*",
        ]
        end_patterns = [
            r"\n\s*Keywords?\s*[:：]",
            r"\n\s*Index\s+Terms",
            r"\n\s*(?:1\.?\s*)?Introduction\s*[\.\n]",
            r"\n\s*1\s+Introduction\b",
            r"\n\s*I\.\s+Introduction\b",
            r"\n\s*1\.\s+[A-Z]",   # "1. Methodology"
            r"\n\s*Key\s+words",
            r"\n{2,}\s*[1Ⅰ]\s",     # 章节号
            r"\n\s*引\s*言",
        ]

        for sp in start_patterns:
            sm = re.search(sp, text)
            if not sm:
                continue
            start = sm.end()
            # 从 start 起截取片段找结束标记
            tail = text[start:start + 4000]
            end_idx = len(tail)
            for ep in end_patterns:
                em = re.search(ep, tail)
                if em and em.start() < end_idx:
                    end_idx = em.start()
            abstract = tail[:end_idx].strip()
            # 清理：去掉首尾多余空白、连字符
            abstract = re.sub(r"\s+", " ", abstract).strip()
            abstract = abstract.strip("—-")
            if 100 <= len(abstract) <= 4000:
                return abstract
            # 长度不合适但非空，放宽下限
            if 30 <= len(abstract) < 100:
                return abstract
        return ""

    def _extract_sections(self, text: str) -> Dict[str, str]:
        """Extract paper sections."""
        sections = {}

        # Common section headers
        section_patterns = [
            r"(?:\n|^)\s*(1\.|I\.|A\.)\s*([A-Z][^\n]+)\n",
            r"(?:\n|^)\s*([A-Z][A-Za-z\s]+)\s*\n(?=\n?[A-Z])",
        ]

        # Split by major sections
        major_sections = [
            "Introduction",
            "Related Work",
            "Background",
            "Methodology",
            "Methods",
            "Approach",
            "Experiments",
            "Results",
            "Discussion",
            "Conclusion",
            "References",
        ]

        text_lower = text.lower()
        for section in major_sections:
            pattern = rf"(?:\n|^)\s*{section}[:\.\s]*(?:\n|\d+\.)"
            match = re.search(pattern, text, re.IGNORECASE)

            if match:
                start = match.end()
                # Find next section
                next_section = None
                for next_sec in major_sections:
                    if next_sec.lower() != section.lower():
                        next_pattern = rf"(?:\n|^)\s*{next_sec}[:\.\s]*(?:\n|\d+\.)"
                        next_match = re.search(next_pattern, text[start:], re.IGNORECASE)
                        if next_match:
                            next_section = start + next_match.start()
                            break

                content = text[start:next_section] if next_section else text[start:]
                sections[section] = self._clean_text(content)

        return sections

    def _extract_references(self, text: str) -> List[str]:
        """Extract references section."""
        references = []

        # Find references section
        ref_pattern = r"(?:References|Bibliography|Works Cited)[:\s]*\n(.{5000,})"
        match = re.search(ref_pattern, text, re.IGNORECASE | re.DOTALL)

        if not match:
            return references

        ref_text = match.group(1)

        # Parse individual references
        # Pattern: [1] or (Author, Year) or numbered
        ref_lines = ref_text.split("\n")

        for line in ref_lines:
            line = line.strip()
            if len(line) > 20:
                references.append(line)

        return references[:50]  # Limit to 50 references

    def _extract_tables_figures(
        self,
        doc,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extract tables and figures."""
        tables = []
        figures = []

        for page_num, page in enumerate(doc):
            # Get images
            images = page.get_images()
            for img_idx, img in enumerate(images):
                figures.append({
                    "page": page_num + 1,
                    "index": img_idx,
                    "xref": img[0],
                })

            # Tables detection (heuristic: check for table-like text blocks)
            text = page.get_text()
            if "Table" in text or "tab." in text.lower():
                tables.append({"page": page_num + 1})

        return tables, figures

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        # Remove excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)

        # Remove page numbers
        text = re.sub(r"\n\s*\d+\s*\n", "\n", text)

        # Remove header/footer artifacts
        text = re.sub(r"^[^\n]{1,30}\n$", "", text, flags=re.MULTILINE)

        return text.strip()

    def to_dict(self, parsed: ParsedPaper) -> Dict[str, Any]:
        """Convert to dictionary for GraphState."""
        return {
            "paper_id": parsed.paper_id,
            "title": parsed.title,
            "authors": parsed.authors,
            "abstract": parsed.abstract,
            "sections": parsed.sections,
            "references": parsed.references,
            "tables": parsed.tables,
            "figures": parsed.figures,
            "word_count": parsed.word_count,
            "extracted_content": {
                "raw_text": parsed.raw_text[:5000],  # Limit size
            },
        }


# Helper functions

def parse_pdf(
    pdf_path: str,
    paper_id: str,
    backend: ParserBackend = ParserBackend.PYMUPDF,
) -> ParsedPaper:
    """
    Quick PDF parsing helper.

    Args:
        pdf_path: Path to PDF
        paper_id: Paper ID
        backend: Parser backend

    Returns:
        ParsedPaper object
    """
    parser = PDFParser(backend=backend)
    return parser.parse(pdf_path, paper_id)


def extract_key_info(pdf_path: str, paper_id: str) -> Dict[str, Any]:
    """
    Extract key information from PDF.

    Args:
        pdf_path: Path to PDF
        paper_id: Paper ID

    Returns:
        Dict with key information
    """
    parsed = parse_pdf(pdf_path, paper_id)

    return {
        "paper_id": paper_id,
        "title": parsed.title,
        "authors": parsed.authors,
        "abstract": parsed.abstract,
        "word_count": parsed.word_count,
        "sections": list(parsed.sections.keys()),
        "reference_count": len(parsed.references),
    }
