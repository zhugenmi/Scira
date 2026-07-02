"""
Scira Paper Text Extractor

从 PDF 中提取纯文本，优先使用 PyMuPDF 直接提取文字层；
文字量过少时降级到 PaddleOCR 识别扫描版页面。
"""

import os

import fitz

from src.utils.logger import logger

# 文本量阈值：全文低于此字符数或页均低于此字符数则触发 OCR
MIN_TOTAL_CHARS = 100
MIN_CHARS_PER_PAGE = 20
# OCR 最大处理页数
MAX_OCR_PAGES = 50
# OCR 每页超时（秒）
OCR_PAGE_TIMEOUT = 120


class TextExtractionError(Exception):
    """文本提取失败时抛出。"""


class PaperTextExtractor:
    """从 PDF 中提取纯文本，OCR 作为兜底。"""

    def __init__(self, ocr_lang: str = "ch"):
        """
        Args:
            ocr_lang: OCR 语言代码，"ch" 为中英混合，"en" 为纯英文。
        """
        self._ocr_lang = ocr_lang
        self._ocr = None

    def extract(self, pdf_path: str) -> str:
        """
        提取 PDF 全文文本。

        1. PyMuPDF 提取文字层
        2. 文字量不足 → PaddleOCR 降级
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        text = self._extract_with_pymupdf(pdf_path)

        if self._should_use_ocr(pdf_path, text=text):
            logger.info(f"文本量不足（{len(text)} 字符），降级到 OCR")
            try:
                text = self._extract_with_ocr(pdf_path)
            except Exception as e:
                logger.warning(f"OCR 提取失败，回退到 PyMuPDF 文本: {e}")
                # 保持 text 为 PyMuPDF 提取结果

        return text

    def _extract_with_pymupdf(self, pdf_path: str) -> str:
        """PyMuPDF 逐页提取文字。"""
        doc = fitz.open(pdf_path)
        parts = []
        try:
            for page in doc:
                parts.append(page.get_text())
        finally:
            doc.close()
        return "\n".join(parts)

    def _should_use_ocr(self, pdf_path: str, text: str | None = None) -> bool:
        """检测文本量是否太少（疑似扫描版 PDF）。

        如果已提前提取文本可传入避免重复提取。
        """
        if text is None:
            text = self._extract_with_pymupdf(pdf_path)
        total = len(text.strip())
        if total < MIN_TOTAL_CHARS:
            return True

        doc = fitz.open(pdf_path)
        page_count = max(doc.page_count, 1)
        doc.close()
        if total / page_count < MIN_CHARS_PER_PAGE:
            return True

        return False

    def _extract_with_ocr(self, pdf_path: str) -> str:
        """PaddleOCR 逐页识别。"""
        ocr = self._get_ocr()
        doc = fitz.open(pdf_path)
        parts = []
        try:
            pages = list(doc)[:MAX_OCR_PAGES]
            for page in pages:
                pix = page.get_pixmap(dpi=300)
                # PaddleOCR 接受 numpy array
                import numpy as np

                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )
                if img.shape[2] == 4:
                    img = img[:, :, :3]  # RGBA → RGB

                result = ocr.ocr(img)
                if result and result[0]:
                    page_text = "\n".join(
                        line[1][0] for line in result[0]
                    )
                    parts.append(page_text)
        finally:
            doc.close()

        return "\n".join(parts)

    def _get_ocr(self):
        """懒加载 PaddleOCR 实例。"""
        if self._ocr is not None:
            return self._ocr

        try:
            from paddleocr import PaddleOCR
        except ImportError:
            logger.info("PaddleOCR 未安装，正在自动安装...")
            self._install_paddleocr()
            from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(lang=self._ocr_lang, use_angle_cls=True)
        return self._ocr

    def _install_paddleocr(self):
        """自动安装 PaddleOCR。"""
        import subprocess
        import sys

        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "paddlepaddle", "paddleocr"],
                capture_output=True, text=True, timeout=300,
                check=True,
            )
            logger.info("PaddleOCR 安装成功")
        except Exception as e:
            raise TextExtractionError(
                "PaddleOCR 自动安装失败，请手动安装：\n"
                "  pip install paddlepaddle paddleocr\n"
                f"错误详情: {e}"
            )
