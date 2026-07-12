"""PDF 关键词搜索模块单元测试。"""
from pathlib import Path
import pytest

from src.core.pdf_search import search_pdf_for_keywords


def _make_pdf(path: Path, lines: list[str]) -> Path:
    """用 reportlab 造测试 PDF。"""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 750
    for line in lines:
        c.drawString(100, y, line)
        y -= 20
    c.showPage()
    c.save()
    return path


@pytest.fixture
def sample_pdf(tmp_path):
    pdf = tmp_path / "test.pdf"
    _make_pdf(pdf, [
        "Test Paper Title",
        "Abstract: We evaluate on ImageNet and COCO datasets.",
        "Introduction",
        "Our method uses transformer architecture.",
        "Experiments",
        "Dataset: ImageNet-1K with 1.2M images.",
        "We compare against ResNet baseline.",
    ])
    return pdf


def test_single_keyword_hit(sample_pdf):
    excerpts = search_pdf_for_keywords(sample_pdf, ["ImageNet"])
    assert len(excerpts) >= 1
    assert any("ImageNet" in e for e in excerpts)


def test_multiple_keywords_hit(sample_pdf):
    excerpts = search_pdf_for_keywords(sample_pdf, ["ImageNet", "COCO", "transformer"])
    assert len(excerpts) >= 1
    # 至少命中 ImageNet（出现两次）
    joined = "\n---\n".join(excerpts)
    assert "ImageNet" in joined


def test_case_insensitive(sample_pdf):
    excerpts = search_pdf_for_keywords(sample_pdf, ["imagenet"])
    assert len(excerpts) >= 1


def test_no_keyword_hit(sample_pdf):
    excerpts = search_pdf_for_keywords(sample_pdf, ["NonExistentTerm"])
    assert excerpts == []


def test_pdf_not_exist(tmp_path):
    """PDF 不存在时返回空列表，不抛异常。"""
    excerpts = search_pdf_for_keywords(tmp_path / "no.pdf", ["anything"])
    assert excerpts == []


def test_empty_keywords(sample_pdf):
    excerpts = search_pdf_for_keywords(sample_pdf, [])
    assert excerpts == []


def test_max_excerpts_limit(sample_pdf):
    """超过 max_excerpts 的命中应被截断。"""
    excerpts = search_pdf_for_keywords(sample_pdf, ["ImageNet"], max_excerpts=1)
    assert len(excerpts) <= 1