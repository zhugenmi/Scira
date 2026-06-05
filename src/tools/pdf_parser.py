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
        title = metadata.get("title") or self._extract_title_from_first_page(doc)
        authors = self._extract_authors(doc)

        # Extract text
        all_text = ""
        for page in doc:
            all_text += page.get_text()

        doc.close()

        # Extract abstract
        abstract = self._extract_abstract(all_text)

        # Extract sections
        sections = {}
        if extract_sections:
            sections = self._extract_sections(all_text)

        # Extract references
        references = self._extract_references(all_text)

        # Extract tables and figures
        tables, figures = self._extract_tables_figures(doc)

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
        title = metadata.get("/Title") or "Unknown"
        authors = metadata.get("/Author", "").split(", ")

        # Extract text
        all_text = ""
        for page in reader.pages:
            all_text += page.extract_text() or ""

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
        """Extract title from first page text."""
        if len(doc) == 0:
            return "Unknown"

        first_page = doc[0]
        text = first_page.get_text()

        lines = text.split("\n")
        for line in lines[:5]:
            line = line.strip()
            if len(line) > 10 and not line.isupper():
                return line

        return "Unknown"

    def _extract_authors(self, doc) -> List[str]:
        """Extract authors from metadata or text."""
        metadata = doc.metadata
        authors_str = metadata.get("author", "")

        if authors_str:
            return [a.strip() for a in authors_str.split(",")]

        return []

    def _extract_abstract(self, text: str) -> str:
        """Extract abstract from paper text."""
        # Common abstract patterns
        patterns = [
            r"(?:Abstract|BSTRACT)[:\s]*(.{100,2000}?)(?:\n\n|Introduction|I\. |\n1\.)",
            r"Abstract\.?\s*(.{100,2000}?)(?:\n\n|1\.|Introduction)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                abstract = match.group(1).strip()
                return self._clean_text(abstract)

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
