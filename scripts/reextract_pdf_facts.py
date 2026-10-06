"""从已抽取的正文重跑教育事实抽取（不重新解析 PDF）。

    python scripts\\reextract_pdf_facts.py                 # 全部类别
    python scripts\\reextract_pdf_facts.py --category 教学质量报告

为什么需要它：新增抽取规则（师资/实践学分/满意度…）后，要能把**整批**正文
几秒内重新过一遍，而不是重解析几百份 PDF。它按来源文件替换旧事实，其它来源的事实保留。

产出：``data/processed/pdf_facts.json``（校级口径事实：就业率/满意度/师资/实践学分等）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.config import load_settings  # noqa: E402
from edumatch.ingest.pdf_facts import extract_pdf_facts, infer_school_year  # noqa: E402
from edumatch.ingest.pdf_reader import pdftext_from_file, source_pdf_for_text  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用缓存正文重跑教育事实抽取")
    ap.add_argument("--category", help="只处理路径里含该词的文件，如 教学质量报告")
    args = ap.parse_args(argv)

    settings = load_settings()
    root = settings.project_root
    text_root = root / "data" / "raw" / "pdf_text"
    source_root = root / "data" / "source"
    if not text_root.exists():
        print(f"[warn] 没有正文缓存 {text_root}；先跑 scripts\\import_extra_text.py")
        return 1

    files = sorted(text_root.rglob("*.txt"))
    if args.category:
        files = [f for f in files if args.category in str(f)]

    facts_path = settings.processed_dir / "pdf_facts.json"
    existing: dict[str, dict] = {}
    if facts_path.exists():
        for row in json.loads(facts_path.read_text(encoding="utf-8")):
            existing[row["fact_id"]] = row

    started = time.time()
    touched_sources: set[str] = set()
    new_rows: list[dict] = []
    for path in files:
        pdf = pdftext_from_file(path)
        pdf.path = str(source_pdf_for_text(path, text_root=text_root,
                                           archive_root=settings.archive_dir,
                                           source_root=source_root))
        school, year = infer_school_year(path.with_suffix(".pdf"))
        rows = extract_pdf_facts(pdf, school=school, year=year)
        touched_sources.add(pdf.path)
        new_rows.extend(r.to_dict() for r in rows)

    touched_stems = {Path(p).stem for p in touched_sources}
    merged = {k: v for k, v in existing.items()
              if Path(str(v.get("source_document") or "")).stem not in touched_stems}
    for row in new_rows:
        merged[row["fact_id"]] = row
    facts_path.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2),
                          encoding="utf-8")

    print(json.dumps({
        "text_files": len(files),
        "facts_regenerated": len(new_rows),
        "facts_total": len(merged),
        "fact_types": dict(Counter(r["fact_type"] for r in new_rows).most_common()),
        "schools": len({r.get("school") for r in new_rows if r.get("school")}),
        "elapsed_s": round(time.time() - started, 1),
        "output": str(facts_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
