"""培养方案课程覆盖率核对：防止"原表有课、引擎没解析到"导致技能被记 0。

背景（真实案例）：北京工业大学 2024 版《信息管理与信息系统》培养方案原表里有
``0007159 C语言程序设计``、``0003774 Java语言II``、``0009923 Python语言``，
但入库课程表只有 61 门、**恰好缺这 3 门语言课**，于是 Python / Java / C 的供给被记 0，
下游缺口看起来是"专业没教"，其实是**解析漏行**。

本脚本对指定院校/专业：
  1. 从培养方案正文里抽出所有"课程代码 + 课程名 + 考试/考查"行（原表口径）；
  2. 从引擎课程库（``data/raw/supplementary_courses.json`` + 收割课程）取该校该专业课程；
  3. 逐条比对，列出**原表有、库里没有**的课程与代码。

用法：
    python scripts\\audit_course_coverage.py --school 北京工业大学 --major 信息管理与信息系统
    python scripts\\audit_course_coverage.py --school 北京工业大学 --major 信息管理与信息系统 --year 2024 --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

ROW = re.compile(r"^(\d{6,7})\s+([^\s，。；、]{2,40}?)\s+(考试|考查)\b")
_PAREN = re.compile(r"[（(][^）)]*[）)]")


def norm_name(name: str) -> str:
    """归一化课程名：去括号后缀/罗马数字/空白，避免"线性代数" vs "线性代数(工)"这类假漏行。"""
    text = _PAREN.sub("", str(name or ""))
    text = re.sub(r"[\sⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX]+$", "", text.strip())
    return text.replace(" ", "")


def source_texts(project_root: Path, school: str, major: str, year: int | None) -> list[Path]:
    patterns = [f"*{major}*.txt"] if not year else [f"{year}_*{major}*.txt", f"*{year}*{major}*.txt"]
    found: list[Path] = []
    for base in (project_root / "data" / "raw" / "pdf_text" / school / "培养方案",
                 project_root / "data" / "source" / "培养方案" / school):
        if not base.exists():
            continue
        for pattern in patterns:
            found.extend(sorted(base.glob(pattern)))
    return sorted(set(found))


def rows_from_text(text: str) -> dict[str, str]:
    """原表口径：课程代码 → 课程名（同名去重，保留代码）。"""
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = ROW.match(line.strip())
        if match:
            out.setdefault(match.group(1), match.group(2).strip())
    return out


def library_courses(project_root: Path, school: str, major: str) -> dict[str, str]:
    """引擎课程库口径：课程名 → 来源文件（含该院校+专业的行）。"""
    path = project_root / "data" / "raw" / "supplementary_courses.json"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for row in json.loads(path.read_text(encoding="utf-8")):
        doc = str(row.get("source_document") or "")
        if school and school not in doc:
            continue
        if major and major not in doc:
            continue
        name = str(row.get("name") or "").strip()
        if name:
            out.setdefault(name, doc)
    return out


def audit(project_root: Path, school: str, major: str, year: int | None = None) -> dict[str, Any]:
    texts = source_texts(project_root, school, major, year)
    raw: dict[str, str] = {}
    for path in texts:
        if path.suffix.lower() == ".txt":
            raw.update(rows_from_text(path.read_text(encoding="utf-8", errors="ignore")))
    lib = library_courses(project_root, school, major)
    lib_norm = {norm_name(name) for name in lib}
    raw_norm = {norm_name(name) for name in raw.values()}
    missing = [{"code": code, "name": name} for code, name in sorted(raw.items())
               if norm_name(name) not in lib_norm]
    extra = sorted(name for name in lib if norm_name(name) not in raw_norm)
    # 语言类课程单独点名（历史高发漏行）
    languages = [m for m in missing if re.search(r"Python|C语言|C\+\+|Java|SQL", m["name"], re.I)]
    return {
        "school": school, "major": major, "year": year,
        "source_files": [str(p.relative_to(project_root).as_posix()) for p in texts],
        "n_raw_rows": len(raw), "n_library": len(lib),
        "coverage": round(len(raw) - len(missing), 0) / len(raw) if raw else None,
        "missing": missing, "missing_count": len(missing),
        "missing_language_courses": languages,
        "extra_in_library": extra[:20],
        "verdict": ("OK：原表课程都在库里" if raw and not missing
                    else ("无法核对：没有原表正文" if not raw else
                          f"警告：原表 {len(raw)} 门中有 {len(missing)} 门未入库，"
                          f"相关技能供给可能被误记为 0")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="培养方案课程覆盖率核对")
    ap.add_argument("--school", required=True)
    ap.add_argument("--major", required=True)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    payload = audit(CORE, args.school, args.major, args.year)
    print(f"{payload['school']} · {payload['major']}"
          f"{' · ' + str(payload['year']) + '版' if payload['year'] else ''}")
    print(f"原表课程 {payload['n_raw_rows']} 门 / 引擎库 {payload['n_library']} 门"
          f"；未入库 {payload['missing_count']} 门")
    print(payload["verdict"])
    if payload["missing_language_courses"]:
        print("语言类漏行（会直接导致 Python/Java/C/SQL 供给记 0）：")
        for row in payload["missing_language_courses"]:
            print(f"  - {row['code']} {row['name']}")
    for row in payload["missing"][:20]:
        print(f"  缺：{row['code']} {row['name']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入 {args.json}")
    return 0 if payload["missing_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
