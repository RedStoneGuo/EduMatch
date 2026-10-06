"""导入 ``data/source/培养方案/<院校>/`` 的培养方案 PDF（一次解析，落成可复用的课程库）。

    python scripts/import_supplementary.py --school 北京工业大学 --major 人工智能
    python scripts/import_supplementary.py --all

产出（全部在工作区内，原始补采目录只读）：

* ``data/raw/supplementary_courses.json``  —— 机读课程库（含来源 PDF/年份/学分/必修选修/实践）
* ``data/raw/pdf_text/<学校>/培养方案/<文件>.txt`` —— 供 school_text() 复用的正文
* ``data/processed/supplementary_import.json``    —— 导入清单（每份 PDF 的解析结果）

数据源就是包内的规范结构 ``data/source``（不再读包外目录）；插件新采的培养方案由
``edumatch/harvest`` 自动落到同一结构，本脚本可一并重解析。

解析只做一次，之后 Dataset 直接读 JSON；重复运行会按 PDF 的 sha1 跳过未变化的文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.dataset import FAMILY_MAJOR, major_family  # noqa: E402
from edumatch.ingest.courses import CourseRecord  # noqa: E402
from edumatch.ingest.pdf_reader import extract_pdf  # noqa: E402
from edumatch.ingest.plan_tables import parse_plan_text, sanitize_text  # noqa: E402

SUPPLEMENT_ROOT = ROOT / "data" / "source"
COURSE_JSON = ROOT / "data" / "raw" / "supplementary_courses.json"
TEXT_ROOT = ROOT / "data" / "raw" / "pdf_text"
MANIFEST = ROOT / "data" / "processed" / "supplementary_import.json"

PLAN_DIR = "培养方案"


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _year_major(stem: str) -> tuple[int | None, str]:
    parts = stem.split("_", 1)
    if parts and parts[0].isdigit():
        return int(parts[0]), (parts[1] if len(parts) > 1 else stem)
    return None, stem


def _family_of(major: str) -> str | None:
    """专业名 → 专业族。只使用项目统一的 major_family 映射（严格）。

    曾用"含智能即 ai"的宽口径，会把智能制造工程/智能建造的课程灌进人工智能专业供给，
    属于跨专业挪用，已废止：映射不出来的专业其课程不进入任何专业族课程池。
    """
    return major_family(major)


def _write_text_cache(pdf_text, school: str, stem: str) -> Path:
    out_dir = TEXT_ROOT / school / PLAN_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.txt"
    path.write_text(sanitize_text(pdf_text.text), encoding="utf-8")
    return path


def _dump(payload, path: Path) -> None:
    """写 JSON 前统一净化，避免 PDF 抽取里的孤立代理项导致写盘失败。"""
    text = sanitize_text(json.dumps(payload, ensure_ascii=False, indent=1))
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导入补采的培养方案 PDF")
    ap.add_argument("--school", default=None, help="只处理该学校（文件夹名）")
    ap.add_argument("--major", default=None, help="只处理课程名包含该关键词的培养方案")
    ap.add_argument("--all", action="store_true", help="处理补采目录下全部院校")
    ap.add_argument("--cache-text", action="store_true", default=True,
                    help="把 PDF 正文写入 data/raw/pdf_text（默认开启）")
    ap.add_argument("--force", action="store_true",
                    help="忽略已有记录，用本次解析结果覆盖（解析规则变更时使用）")
    ap.add_argument("--families", default=None,
                    help="只处理这些专业族，逗号分隔（如 ai,cs）；默认全部")
    ap.add_argument("--max-mb", type=float, default=8.0,
                    help="跳过超过该体积的 PDF（默认 8MB；多为扫描件，抽取不到文本）")
    ap.add_argument("--dry-run", action="store_true", help="只统计将处理的文件，不解析")
    args = ap.parse_args(argv)

    if not SUPPLEMENT_ROOT.exists():
        print(f"[error] 未找到补采目录：{SUPPLEMENT_ROOT}")
        return 1

    plan_root = SUPPLEMENT_ROOT / PLAN_DIR
    schools = ([p.name for p in sorted(plan_root.iterdir()) if p.is_dir()]
               if args.all else [args.school] if args.school else [])
    if not schools:
        print("[error] 请用 --school <学校> 或 --all 指定范围")
        return 1

    known: dict[str, dict] = {}
    if COURSE_JSON.exists() and not args.force:
        try:
            known = {c["course_id"]: c for c in json.loads(COURSE_JSON.read_text(encoding="utf-8"))}
        except json.JSONDecodeError:
            known = {}
    if args.force and COURSE_JSON.exists():
        # 只覆盖本次处理范围，其余院校的记录保留
        try:
            previous = json.loads(COURSE_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = []
        scope = set(schools)
        known = {c["course_id"]: c for c in previous if c["school"] not in scope}

    manifest: list[dict] = []
    n_new = 0
    for school in schools:
        plan_dir = plan_root / school
        if not plan_dir.is_dir():
            continue
        for pdf in sorted(plan_dir.glob("*.pdf")):
            if args.major and args.major not in pdf.stem:
                continue
            year, major = _year_major(pdf.stem)
            family = _family_of(major)
            if args.families and (family or "") not in {f.strip() for f in args.families.split(",")}:
                continue
            if pdf.stat().st_size > args.max_mb * 1024 * 1024:
                manifest.append({"school": school, "file": pdf.name, "year": year, "major": major,
                                 "family": family, "n_courses": 0, "skipped": "file_too_large",
                                 "size_mb": round(pdf.stat().st_size / 1024 / 1024, 1)})
                continue
            if args.dry_run:
                manifest.append({"school": school, "file": pdf.name, "year": year, "major": major,
                                 "family": family, "n_courses": 0, "dry_run": True,
                                 "size_mb": round(pdf.stat().st_size / 1024 / 1024, 1)})
                continue
            text = extract_pdf(pdf)
            entry = {"school": school, "file": pdf.name, "year": year, "major": major,
                     "family": family, "sha1": text.sha1, "text_status": text.text_status,
                     "n_pages": text.n_pages, "chars": text.char_count,
                     "n_courses": 0, "sections": [], "notes": []}
            if text.text_status != "ok":
                entry["notes"].append(f"文本不可用：{text.text_status} {text.error}")
                manifest.append(entry)
                continue
            if args.cache_text:
                _write_text_cache(text, school, pdf.stem)
            parsed = parse_plan_text(
                text.text, school=school, year=year, major=major, family=family,
                source_document=str(pdf), evidence_level="A",
            )
            entry.update(n_courses=len(parsed.courses), n_rows=parsed.n_rows,
                         sections=parsed.sections, notes=parsed.notes)
            for course in parsed.courses:
                key = course.course_id
                if key not in known:
                    n_new += 1
                known[key] = asdict(course)
            manifest.append(entry)

    COURSE_JSON.parent.mkdir(parents=True, exist_ok=True)
    _dump(sorted(known.values(), key=lambda c: (c["school"], c["year"] or 0, c["name"])), COURSE_JSON)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    _dump({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(SUPPLEMENT_ROOT), "files": manifest,
        "n_files": len(manifest), "n_courses_total": len(known), "n_courses_new": n_new,
    }, MANIFEST)

    by_school: dict[str, dict[str, int]] = {}
    for item in manifest:
        bucket = by_school.setdefault(item["school"], {"files": 0, "courses": 0})
        bucket["files"] += 1
        bucket["courses"] += item.get("n_courses", 0)
    print(json.dumps({"courses_total": len(known), "courses_new": n_new,
                      "files": len(manifest), "by_school": by_school},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
