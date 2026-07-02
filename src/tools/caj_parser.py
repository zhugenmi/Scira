"""
CAJ (China Academic Journals / 知网) 格式支持。

CNKI 下发的 .caj 文件大多其实是改了扩展名的标准 PDF（文件头为 %PDF），
这类文件可直接交给 PDFParser 解析。少数真正的 CAJ 专有二进制格式需要
caj2pdf 工具（https://github.com/caj2pdf/caj2pdf）才能转成 PDF，
该库已内置于 src/tools/caj2pdf/ 目录。
"""

import os
import shutil
import tempfile

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

    1. 若文件实为 PDF（文件头 %PDF），直接拷贝字节。
    2. 否则按真正的 CAJ 二进制格式处理，使用内置的 caj2pdf 库转换。
    """
    if not os.path.exists(caj_path):
        raise FileNotFoundError(f"CAJ 文件不存在: {caj_path}")

    if is_disguised_pdf(caj_path):
        shutil.copyfile(caj_path, output_pdf_path)
        logger.debug(f"CAJ 实为 PDF，直接拷贝至 {output_pdf_path}")
        return output_pdf_path

    # 真正的 CAJ 二进制格式 —— 使用内置 caj2pdf
    try:
        from src.tools.caj2pdf import CAJParser
    except ImportError as e:
        raise CAJParseError(
            "该 CAJ 文件为知网专有二进制格式，但内置 caj2pdf 库未能导入。\n"
            "请确认 src/tools/caj2pdf/ 目录完整且包含 cajparser.py。\n"
            "详见 https://github.com/caj2pdf/caj2pdf\n"
            f"导入错误: {e}"
        )

    # 写入临时文件供 caj2pdf 处理（caj2pdf 部分版本只接受文件路径）
    # 使用 TemporaryDirectory 避免残留
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_caj = os.path.join(tmpdir, "input.caj")
        tmp_out = os.path.join(tmpdir, "output.pdf")
        shutil.copy2(caj_path, tmp_caj)

        try:
            caj = CAJParser(tmp_caj)
            caj.convert(tmp_out)
        except CAJParseError:
            raise
        except (Exception, SystemExit) as e:
            raise CAJParseError(f"CAJ 转 PDF 失败: {e}") from e

        if not os.path.exists(tmp_out):
            raise CAJParseError("CAJ 转 PDF 失败：未生成输出文件")

        # 移动到目标位置
        shutil.move(tmp_out, output_pdf_path)

    return output_pdf_path
