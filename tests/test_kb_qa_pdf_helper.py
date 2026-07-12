"""_filter_papers_with_pdfs 辅助函数测试。"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def fake_kb_with_pdfs(tmp_path, monkeypatch):
    """构造临时 KB，2 篇有 PDF，1 篇无 PDF。"""
    from src.mcp import server as srv

    cat_name = "test_cat"
    cat_dir = tmp_path / "data" / "papers" / cat_name
    cat_dir.mkdir(parents=True)

    # p1: 有 pdf_path 字段
    p1_pdf = cat_dir / "p1" / "p1.pdf"
    p1_pdf.parent.mkdir()
    p1_pdf.write_bytes(b"%PDF-1.4 fake")
    # p2: 无 pdf_path 字段，但有标准路径 <cat>/<pid>/<pid>.pdf
    p2_pdf = cat_dir / "p2" / "p2.pdf"
    p2_pdf.parent.mkdir()
    p2_pdf.write_bytes(b"%PDF-1.4 fake")
    # p3: 无 PDF
    p3_dir = cat_dir / "p3"
    p3_dir.mkdir()

    papers = [
        {"paper_id": "p1", "title": "Paper 1", "pdf_path": f"data/papers/{cat_name}/p1/p1.pdf"},
        {"paper_id": "p2", "title": "Paper 2"},  # 靠 fallback 解析
        {"paper_id": "p3", "title": "Paper 3"},  # 无 PDF
    ]
    (cat_dir / f"{cat_name}.json").write_text(
        json.dumps({"category": cat_name, "topic": "测试", "papers": papers}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(srv, "PROJECT_ROOT", tmp_path)
    return {
        "name": cat_name,
        "topic": "测试",
        "papers": papers,
    }


def test_filter_returns_only_papers_with_pdfs(fake_kb_with_pdfs):
    from src.mcp.server import _filter_papers_with_pdfs
    result = _filter_papers_with_pdfs(fake_kb_with_pdfs)
    ids = [p["paper_id"] for p in result]
    assert "p1" in ids
    assert "p2" in ids
    assert "p3" not in ids


def test_filter_fills_pdf_path_via_fallback(fake_kb_with_pdfs):
    """p2 没有 pdf_path 字段，应通过 fallback 路径填上。"""
    from src.mcp.server import _filter_papers_with_pdfs
    result = _filter_papers_with_pdfs(fake_kb_with_pdfs)
    p2 = next(p for p in result if p["paper_id"] == "p2")
    assert p2.get("pdf_path"), "p2 pdf_path should be filled by fallback"


def test_filter_preserves_existing_pdf_path(fake_kb_with_pdfs):
    from src.mcp.server import _filter_papers_with_pdfs
    result = _filter_papers_with_pdfs(fake_kb_with_pdfs)
    p1 = next(p for p in result if p["paper_id"] == "p1")
    assert p1["pdf_path"] == "data/papers/test_cat/p1/p1.pdf"