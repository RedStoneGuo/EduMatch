"""从**全部**已抽取的就业质量报告正文里提取"分专业就业行"。

    python scripts\\extract_pdf_major_rows.py

读 ``data/raw/pdf_text/<院校>/年度报告/就业质量报告/*.txt``（含子目录），
写 ``data/processed/pdf_major_rows.json``——专业级就业事实（落实率/签约率/深造率），
这是 O 维与「同类高校就业结果对比」的唯一一手来源。

同一 (院校, 年份, 专业) 可能出现在多张表里（本科/研究生/不同口径）：
优先保留带完整人数—比例一致性校验的 `full7` 版式行，其次保留毕业生人数最大的行。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.config import load_settings  # noqa: E402
from edumatch.ingest.pdf_facts import infer_school_year  # noqa: E402
from edumatch.ingest.pdf_major_tables import extract_major_rows  # noqa: E402
from edumatch.ingest.pdf_reader import pdftext_from_file, source_pdf_for_text  # noqa: E402


def employment_texts(text_root: Path) -> list[Path]:
    """就业质量报告正文：包内结构是 <院校>/年度报告/就业质量报告/…（可能还有子目录）。"""
    found: list[Path] = []
    for path in sorted(text_root.rglob("*.txt")):
        text = str(path).replace("\\", "/")
        if "就业质量报告" in text or "年度报告" in text:
            found.append(path)
    return found


def main() -> int:
    settings = load_settings()
    root = settings.project_root
    text_root = root / "data" / "raw" / "pdf_text"
    files = employment_texts(text_root)
    if not files:
        print(f"[warn] {text_root} 下没有就业质量报告正文；先跑 scripts\\import_extra_text.py")
        return 1

    all_rows: list[dict] = []
    per_file: list[dict] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        school, year = infer_school_year(path.with_suffix(".pdf"))
        doc = pdftext_from_file(path)
        source_pdf = source_pdf_for_text(path, text_root=text_root,
                                         archive_root=settings.archive_dir,
                                         source_root=root / "data" / "source")
        rows = extract_major_rows(text, school=school, year=year,
                                  source_document=str(source_pdf), page_of=doc.page_of)
        all_rows.extend(r.to_dict() for r in rows)
        per_file.append({"file": path.name, "school": school, "year": year, "n_rows": len(rows)})

    best: dict[tuple, dict] = {}
    dropped = 0
    for row in all_rows:
        key = (row["school"], row["year"], row["major"])
        current = best.get(key)
        if current is None:
            best[key] = dict(row, alternatives=0)
            continue
        dropped += 1
        if row["layout"] != current["layout"]:
            row_wins = row["layout"] == "full7"
        else:
            row_wins = row["graduates"] > current["graduates"]
        if row_wins:
            best[key] = dict(row, alternatives=current.get("alternatives", 0) + 1)
        else:
            current["alternatives"] = current.get("alternatives", 0) + 1
    deduped = list(best.values())

    out = settings.processed_dir / "pdf_major_rows.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "files": len(per_file),
        "files_with_rows": sum(1 for f in per_file if f["n_rows"]),
        "major_rows": len(all_rows),
        "major_rows_after_dedup": len(deduped),
        "rows_merged_as_alternatives": dropped,
        "schools": len({r["school"] for r in all_rows if r["school"]}),
        "years": sorted({r["year"] for r in all_rows if r["year"]}),
        "layouts": dict(Counter(r["layout"] for r in all_rows)),
        "top_majors": dict(Counter(r["major"] for r in all_rows).most_common(12)),
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
