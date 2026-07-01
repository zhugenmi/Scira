"""
CAJ parser 测试。

覆盖：
1. 伪装 PDF（文件头 %PDF）的识别与拷贝转换。
2. 真正二进制 CAJ 在缺少 caj2pdf 时抛出 CAJParseError。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools.caj_parser import (
    CAJParseError,
    convert_caj_to_pdf,
    is_disguised_pdf,
)


@pytest.fixture
def tmp_caj_disguised(tmp_path):
    """一个内容实为 PDF 的 .caj 文件（模拟 CNKI 下发的多数 CAJ）。"""
    p = tmp_path / "fake.caj"
    p.write_bytes(b"%PDF-1.5\n%fake pdf body\nsome content here")
    return p


@pytest.fixture
def tmp_caj_binary(tmp_path):
    """一个真正的二进制 CAJ 文件头（非 %PDF）。"""
    p = tmp_path / "real.caj"
    p.write_bytes(b"\xca\xfe\xba\xbe" + b"binary caj payload" * 10)
    return p


class TestCAJParser:
    def test_is_disguised_pdf_true(self, tmp_caj_disguised):
        assert is_disguised_pdf(str(tmp_caj_disguised)) is True

    def test_is_disguised_pdf_false(self, tmp_caj_binary):
        assert is_disguised_pdf(str(tmp_caj_binary)) is False

    def test_is_disguised_pdf_missing(self, tmp_path):
        assert is_disguised_pdf(str(tmp_path / "nope.caj")) is False

    def test_convert_disguised_caj_copies_bytes(self, tmp_caj_disguised, tmp_path):
        out = tmp_path / "out.pdf"
        convert_caj_to_pdf(str(tmp_caj_disguised), str(out))
        assert out.exists()
        assert out.read_bytes() == tmp_caj_disguised.read_bytes()

    def test_convert_disguised_caj_parseable_by_pdfparser(self, tmp_path):
        """转换后的 PDF 应能被 PDFParser 打开（用 PyMuPDF 生成真 PDF）。"""
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")

        src_pdf = tmp_path / "real.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello CAJ disguise test")
        doc.save(str(src_pdf))
        doc.close()

        caj = tmp_path / "disguised.caj"
        caj.write_bytes(src_pdf.read_bytes())
        out = tmp_path / "converted.pdf"
        convert_caj_to_pdf(str(caj), str(out))

        from src.tools.pdf_parser import PDFParser
        parsed = PDFParser().parse(str(out), "test")
        assert "Hello CAJ disguise test" in parsed.title

    def test_convert_true_binary_caj_without_lib_raises(self, tmp_caj_binary, tmp_path):
        """caj2pdf 未安装时，真正二进制 CAJ 应抛 CAJParseError。"""
        try:
            import caj2pdf  # noqa: F401
        except ImportError:
            expect_error = True
        else:
            expect_error = False  # 装了 caj2pdf 则不预测错误

        out = tmp_path / "out.pdf"
        if expect_error:
            with pytest.raises(CAJParseError) as exc_info:
                convert_caj_to_pdf(str(tmp_caj_binary), str(out))
            assert "caj2pdf" in str(exc_info.value)
        else:
            # 装了库的 环境：转换要么成功要么抛 CAJParseError，不在此断言细节
            try:
                convert_caj_to_pdf(str(tmp_caj_binary), str(out))
            except CAJParseError:
                pass

    def test_convert_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            convert_caj_to_pdf(str(tmp_path / "nope.caj"), str(tmp_path / "out.pdf"))
