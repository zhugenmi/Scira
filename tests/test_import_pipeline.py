"""End-to-end tests for the paper import pipeline: PDF text extraction + LLM info extraction.

Tests the full pipeline:
  1. Create a digital PDF with an embedded text layer
  2. Extract text via PaperTextExtractor
  3. Extract structured metadata via PaperInfoExtractor (with mocked LLM)
  4. Verify scanned (text-empty) PDFs are correctly flagged for OCR
"""

import json
from unittest.mock import MagicMock

import fitz
import pytest

from src.tools.text_extractor import PaperTextExtractor


def create_test_pdf(path: str, text: str = "Test Paper Title\nAuthor Name\nAbstract content here."):
    """Create a test PDF with an embedded text layer (digital, not scanned).

    Uses china-s font so CJK characters render correctly in PyMuPDF.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontname="china-s")
    doc.save(path)
    doc.close()


def test_full_import_pipeline_digital_pdf(tmp_path):
    """E2E: digital PDF -> text extraction -> structured LLM extraction."""
    from src.tools.paper_info_extractor import PaperInfoExtractor

    # Create a test PDF with known content (Chinese + English to verify encoding)
    pdf_path = tmp_path / "test.pdf"
    create_test_pdf(
        str(pdf_path),
        "深度学习在自然语言处理中的应用\n张三 (清华大学)\n摘要：本文综述了深度学习在NLP中的最新进展。",
    )

    # Step 1: Text extraction from digital PDF
    extractor = PaperTextExtractor()
    text = extractor.extract(str(pdf_path))
    assert len(text) > 10
    assert "深度学习" in text or "Deep" in text

    # Step 2: Structured info extraction with mocked LLM (no real API calls)
    info_extractor = PaperInfoExtractor()

    class MockResponse:
        content = json.dumps({
            "title": "深度学习在自然语言处理中的应用",
            "authors": ["张三 (清华大学)"],
            "abstract": "本文综述了深度学习在NLP中的最新进展。",
            "keywords": ["深度学习", "NLP"],
            "doi": None,
            "journal": None,
            "year": 2024,
            "volume": None,
            "issue": None,
            "pages": None,
        })
        usage_metadata = {}

    info_extractor.llm = MagicMock()
    info_extractor.llm.invoke = MagicMock(return_value=MockResponse())

    result = info_extractor.extract(text)
    assert result["title"] == "深度学习在自然语言处理中的应用"
    assert result["metadata_quality"] == "llm_extracted"


def test_full_import_pipeline_scanned_pdf_detection(tmp_path):
    """Scanned (text-layer-free) PDF should be detected as needing OCR fallback."""
    # A blank page simulates a scanned PDF (no text layer whatsoever)
    pdf_path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    extractor = PaperTextExtractor()
    assert extractor._should_use_ocr(str(pdf_path)) is True
