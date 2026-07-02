"""
CAJ parser 测试。

覆盖：
1. 伪装 PDF（文件头 %PDF）的识别与拷贝转换。
2. 真正二进制 CAJ 的转换与错误处理。
3. 内置 caj2pdf 库的导入与使用。
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

    def test_bundled_caj2pdf_imports(self):
        """内置 caj2pdf 库应可正常导入 CAJParser。"""
        from src.tools.caj2pdf import CAJParser
        assert CAJParser is not None

    def test_convert_binary_caj_raises_on_invalid_data(self, tmp_path):
        """二进制 CAJ 但内容无效时应抛出 CAJParseError。"""
        caj_path = tmp_path / "invalid.caj"
        # 写入非 PDF 头但也不是合法 CAJ 的内容
        caj_path.write_bytes(b"CAJFILE\x00\x01\x02" + b"\x00" * 100)
        out_path = tmp_path / "out.pdf"

        with pytest.raises(CAJParseError):
            convert_caj_to_pdf(str(caj_path), str(out_path))

    def test_convert_binary_caj_broken_lib(self, tmp_path, monkeypatch):
        """内置 caj2pdf 导入失败时应抛出 CAJParseError 并附提示。"""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "src.tools.caj2pdf" or name.startswith("src.tools.caj2pdf."):
                raise ImportError("Mocked import failure")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        caj_path = tmp_path / "test.caj"
        caj_path.write_bytes(b"CAJFILE\x00\x01\x02")
        out_path = tmp_path / "out.pdf"

        with pytest.raises(CAJParseError, match="caj2pdf"):
            convert_caj_to_pdf(str(caj_path), str(out_path))

    def test_convert_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            convert_caj_to_pdf(str(tmp_path / "nope.caj"), str(tmp_path / "out.pdf"))
