"""一次性迁移脚本：把扁平的 data/papers/<category>/pdfs/<safe_pid>.pdf
迁到 per-paper 子目录 data/papers/<category>/<safe_pid>/<safe_pid>.pdf，
并更新 <category>.json 中每条 paper 的 pdf_path 字段。

迁移完成后删除空的 pdfs/ 子目录与 data/paper_reading/ 整目录。

运行：python scripts/migrate_papers_to_per_paper_dirs.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS_DIR = ROOT / "data" / "papers"
PAPER_READING_DIR = ROOT / "data" / "paper_reading"


def migrate_category(category_dir: Path) -> None:
    pdfs_dir = category_dir / "pdfs"
    if not pdfs_dir.is_dir():
        return

    moved = 0
    for pdf in list(pdfs_dir.glob("*.pdf")):
        safe_pid = pdf.stem
        paper_dir = category_dir / safe_pid
        paper_dir.mkdir(parents=True, exist_ok=True)
        target = paper_dir / f"{safe_pid}.pdf"
        if target.exists():
            print(f"  [skip] target exists: {target}")
            pdf.unlink(missing_ok=True)
            continue
        shutil.move(str(pdf), str(target))
        moved += 1
    print(f"  moved {moved} pdf(s) into per-paper dirs")

    # 更新 <category>.json 的 pdf_path
    cat_json = category_dir / f"{category_dir.name}.json"
    if cat_json.exists():
        try:
            with open(cat_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [warn] read {cat_json} failed: {e}")
            data = None
        if data:
            changed = 0
            for p in data.get("papers", []) or []:
                old = p.get("pdf_path") or ""
                # data/papers/<category>/pdfs/<safe_pid>.pdf -> data/papers/<category>/<safe_pid>/<safe_pid>.pdf
                if "/pdfs/" in old and old.startswith("data/papers/"):
                    parts = old.split("/")
                    # ['data','papers','<category>','pdfs','<safe_pid>.pdf']
                    if len(parts) == 5 and parts[3] == "pdfs":
                        safe_pid = Path(parts[4]).stem
                        new_path = f"data/papers/{parts[2]}/{safe_pid}/{safe_pid}.pdf"
                        # 仅当目标文件真实存在时才更新（避免误改）
                        if (category_dir / safe_pid / f"{safe_pid}.pdf").exists():
                            p["pdf_path"] = new_path
                            changed += 1
            with open(cat_json, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  updated {changed} pdf_path entries in {cat_json.name}")

    # 删除空 pdfs 目录
    try:
        if pdfs_dir.exists() and not any(pdfs_dir.iterdir()):
            pdfs_dir.rmdir()
            print(f"  removed empty {pdfs_dir}")
    except Exception as e:
        print(f"  [warn] remove {pdfs_dir} failed: {e}")


def main() -> None:
    if not PAPERS_DIR.exists():
        print(f"no {PAPERS_DIR}, nothing to do")
        return

    for category_dir in sorted(PAPERS_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        print(f"[category] {category_dir.name}")
        migrate_category(category_dir)

    # 删除 data/paper_reading/ 整目录
    if PAPER_READING_DIR.exists():
        shutil.rmtree(PAPER_READING_DIR)
        print(f"removed {PAPER_READING_DIR}")
    else:
        print(f"no {PAPER_READING_DIR}, skip")

    print("migration done")


if __name__ == "__main__":
    main()
