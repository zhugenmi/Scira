"""Tests for PaperTextExtractor."""

import fitz
import pytest

from src.tools.text_extractor import PaperTextExtractor


def test_extract_digital_pdf(tmp_path):
    """数字 PDF：应通过 PyMuPDF 直接提取文字。"""
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # 使用 china-s 字体确保中文正常渲染
    page.insert_text((72, 72), "Hello World 人工智能", fontname="china-s")
    page.insert_text((72, 100), "Machine Learning and Deep Learning", fontname="china-s")
    page.insert_text((72, 128), "This is additional text to ensure enough content.", fontname="china-s")
    page.insert_text((72, 156), "More filler text to push past the 100-char threshold.", fontname="china-s")
    doc.save(str(pdf_path))
    doc.close()

    extractor = PaperTextExtractor()
    text = extractor.extract(str(pdf_path))
    assert "Hello World" in text
    assert "人工智能" in text


def test_extract_nonexistent_file():
    """不存在的文件应抛出 FileNotFoundError。"""
    extractor = PaperTextExtractor()
    with pytest.raises(FileNotFoundError):
        extractor.extract("/nonexistent/path.pdf")


def test_should_use_ocr_empty_pdf(tmp_path):
    """空 PDF（无文本层）应判定为需要 OCR。"""
    pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    extractor = PaperTextExtractor()
    assert extractor._should_use_ocr(str(pdf_path)) is True


def test_should_not_use_ocr_rich_pdf(tmp_path):
    """有丰富文本的 PDF 不应走 OCR。"""
    pdf_path = tmp_path / "rich.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # 多行插入超过 MIN_TOTAL_CHARS (100) 避免触发 OCR
    page.insert_text((72, 72), "A" * 80)
    page.insert_text((72, 100), "B" * 80)
    page.insert_text((72, 128), "C" * 80)
    doc.save(str(pdf_path))
    doc.close()

    extractor = PaperTextExtractor()
    assert extractor._should_use_ocr(str(pdf_path)) is False
