"""把 ``data/source`` 里尚未抽取的 PDF 全部抽成可检索文本（课程大纲 / 专业介绍 / 年度报告 / 论文）。

    python scripts/import_extra_text.py --dry-run
    python scripts/import_extra_text.py

覆盖范围（只抽文本，不改写任何人工材料）——即包内规范结构 ``data/source``：

* ``课程大纲/<院校>/**/*.pdf``（658 份，单课大纲与院系大纲合集）
* ``专业介绍/<院校>/*.pdf``（24 份）
* ``年度报告/<院校>/{就业质量报告,教学质量报告}/*.pdf``（463 份）
* ``文献/TSI指标构建文献/*.pdf``（方法论文献）

产物：

* `data/raw/pdf_text/<学校>/<类别>/<文件名>.txt` —— 供 `Dataset.school_text()` 检索引用；
* `data/processed/extra_text_manifest.json` —— 逐份文件的抽取状态与字符数（可复现）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.ingest.pdf_reader import extract_pdf  # noqa: E402
from edumatch.ingest.plan_tables import sanitize_text  # noqa: E402

TEXT_ROOT = ROOT / "data" / "raw" / "pdf_text"
MANIFEST = ROOT / "data" / "processed" / "extra_text_manifest.json"

SOURCE = ROOT / "data" / "source"


def _targets() -> list[tuple[str, str, Path]]:
    """返回 (学校/来源, 类别, PDF 路径) 列表。"""
    out: list[tuple[str, str, Path]] = []
    if SOURCE.exists():
        for category in ("课程大纲", "专业介绍", "培养方案"):
            base = SOURCE / category
            if not base.exists():
                continue
            for school_dir in sorted(p for p in base.iterdir() if p.is_dir()):
                out += [(school_dir.name, category, pdf)
                        for pdf in sorted(school_dir.rglob("*.pdf"))]
        reports = SOURCE / "年度报告"
        if reports.exists():
            for school_dir in sorted(p for p in reports.iterdir() if p.is_dir()):
                # 年度报告里有 .pdf / .docx / .doc：docx 能直接读（stdlib 解析），
                # 老式二进制 .doc 读不了，交给覆盖审计如实记为"未解析"。
                out += [(school_dir.name, "年度报告", doc)
                        for doc in sorted(school_dir.rglob("*"))
                        if doc.is_file() and doc.suffix.lower() in {".pdf", ".docx"}]
        lit = SOURCE / "文献" / "TSI指标构建文献"
        if lit.exists():
            out += [("归档文献", "TSI指标构建文献", pdf) for pdf in sorted(lit.glob("*.pdf"))]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把剩余 PDF 抽成可检索文本")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-mb", type=float, default=40.0, help="跳过超过该体积的 PDF")
    args = ap.parse_args(argv)

    manifest: list[dict] = []
    n_ok = n_skip = n_fail = 0
    for source, category, pdf in _targets():
        size_mb = pdf.stat().st_size / 1024 / 1024
        entry = {"source": source, "category": category, "file": pdf.name,
                 "size_mb": round(size_mb, 1)}
        out_path = TEXT_ROOT / source / category / f"{pdf.stem}.txt"
        entry["text_path"] = out_path.relative_to(ROOT).as_posix()
        if out_path.exists() and out_path.stat().st_size > 0:
            entry.update(status="cached", chars=out_path.stat().st_size)
            manifest.append(entry)
            n_skip += 1
            continue
        if size_mb > args.max_mb:
            entry.update(status="skipped", reason=f"体积 {size_mb:.1f} MB 超过阈值（多为扫描合集）")
            manifest.append(entry)
            n_skip += 1
            continue
        if args.dry_run:
            entry.update(status="dry_run")
            manifest.append(entry)
            continue
        if pdf.suffix.lower() == ".docx":
            from edumatch.ingest.docx_reader import read_docx_text  # noqa: PLC0415

            try:
                body = read_docx_text(pdf)
                entry.update(status="ok", chars=len(body), kind="docx")
            except Exception as exc:  # noqa: BLE001
                entry.update(status="fail", reason=f"{type(exc).__name__}: {exc}")
                manifest.append(entry)
                n_fail += 1
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(sanitize_text(body), encoding="utf-8")
            manifest.append(entry)
            n_ok += 1
            continue
        text = extract_pdf(pdf)
        if text.text_status != "ok":
            entry.update(status=text.text_status, chars=text.char_count, error=text.error)
            manifest.append(entry)
            n_fail += 1
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(sanitize_text(text.text), encoding="utf-8")
        entry.update(status="ok", chars=text.char_count, pages=text.n_pages)
        manifest.append(entry)
        n_ok += 1

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_files": len(manifest), "n_extracted": n_ok, "n_cached_or_skipped": n_skip,
        "n_failed": n_fail, "files": manifest,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"抽取 {n_ok} 份 / 复用或跳过 {n_skip} 份 / 失败 {n_fail} 份；清单 {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
