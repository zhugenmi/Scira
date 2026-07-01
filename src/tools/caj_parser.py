"""
CAJ (China Academic Journals / 知网) 格式支持。

CNKI 下发的 .caj 文件大多其实是改了扩展名的标准 PDF（文件头为 %PDF），
这类文件可直接交给 PDFParser 解析。少数真正的 CAJ 专有二进制格式需要
`caj2pdf` 工具（https://github.com/caj2pdf/caj2pdf）才能转成 PDF，
本模块对该库做惰性导入，缺失时给出明确的安装提示。
"""

import os
import shutil

from src.utils.logger import logger


class CAJParseError(Exception):
    """CAJ 文件无法转换为 PDF 时抛出。"""


def is_disguised_pdf(path: str) -> bool:
    """判断文件内容是否其实是 PDF（文件头 %PDF）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(5)
    except OSError:
        return False
    return head.startswith(b"%PDF")


def convert_caj_to_pdf(caj_path: str, output_pdf_path: str) -> str:
    """
    将 .caj 文件转换为 .pdf。

    1. 若文件实为 PDF（文件头 %PDF），直接拷贝字节——这覆盖了绝大多数
       CNKI 下载的 CAJ 文件。
    2. 否则按真正的 CAJ 二进制格式处理，惰性调用 `caj2pdf` 库；未安装时
       抛出 CAJParseError 并附安装说明。

    Args:
        caj_path: 源 .caj 文件路径。
        output_pdf_path: 转换后 PDF 写入路径。

    Returns:
        output_pdf_path。
    """
    if not os.path.exists(caj_path):
        raise FileNotFoundError(f"CAJ 文件不存在: {caj_path}")

    if is_disguised_pdf(caj_path):
        shutil.copyfile(caj_path, output_pdf_path)
        logger.debug(f"CAJ 实为 PDF，直接拷贝至 {output_pdf_path}")
        return output_pdf_path

    # 真正的 CAJ 二进制格式——需要 caj2pdf
    try:
        from caj2pdf import CAJParser  # type: ignore
    except ImportError:
        raise CAJParseError(
            "该 CAJ 文件为知网专有二进制格式，需安装 caj2pdf 才能转换：\n"
            "  pip install git+https://github.com/caj2pdf/caj2pdf.git\n"
            "详见 https://github.com/caj2pdf/caj2pdf"
        )

    try:
        caj = CAJParser(caj_path)
        caj.convert(output_pdf_path)
    except CAJParseError:
        raise
    except Exception as e:
        raise CAJParseError(f"CAJ 转 PDF 失败: {e}") from e

    if not os.path.exists(output_pdf_path):
        raise CAJParseError("CAJ 转 PDF 失败：未生成输出文件")
    return output_pdf_path
