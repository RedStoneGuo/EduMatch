"""按「院校 + 专业」定位本地原始材料，并说明解析/入库情况与下一步动作。

这是给 Agent 用的**原始文件检索入口**：当模型解析不到某项信息时，可以先用它把
「这个院校专业在本地到底有哪些材料、正文抽出来了没有、结构化入库了没有」查清楚，
再决定是"去读原文补数据"、"修解析规则"，还是"联网补采"。

    python scripts\\find_source.py --school 北京理工大学 --major 会计学
    python scripts\\find_source.py --school 清华大学 --major 软件工程 --json out.json

约定：只读，不改数据；找不到就如实说"没有"，不猜路径、不编内容。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))

#: 材料类型 → 关键内容提示（用于判断"正文里到底有没有课程表/就业表"）
COURSE_HINTS = ("课程代码", "课程名", "学分", "学时", "必修", "选修")
EMPLOYMENT_HINTS = ("就业率", "落实率", "签约率", "深造率", "毕业生")


def _find(root: Path, school: str, major: str, pattern: str = "*") -> list[Path]:
    base = root / school
    if not base.exists():
        return []
    out = [p for p in base.rglob(pattern) if p.is_file()]
    if major:
        hits = [p for p in out if major in p.name or major in str(p.parent)]
        if hits:
            return sorted(hits)
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按院校+专业定位本地原始材料与入库情况")
    ap.add_argument("--school", required=True)
    ap.add_argument("--major", default="")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    source = CORE / "data" / "source"
    text_root = CORE / "data" / "raw" / "pdf_text"
    payload: dict[str, object] = {"school": args.school, "major": args.major,
                                  "materials": {}, "parsed": {}, "actions": []}

    # ① 原始材料（data/source）
    materials: dict[str, list[str]] = {}
    for kind in ("培养方案", "课程大纲", "专业介绍", "年度报告"):
        found = _find(source / kind, args.school, args.major)
        materials[kind] = [p.relative_to(CORE).as_posix() for p in found]
    payload["materials"] = materials

    # ② 正文缓存 + 内容线索
    texts: dict[str, list[dict[str, object]]] = {}
    for kind in ("培养方案", "课程大纲", "专业介绍", "年度报告"):
        entries: list[dict[str, object]] = []
        for doc in _find(text_root / args.school / kind, "", args.major, "*.txt"):
            body = doc.read_text(encoding="utf-8", errors="ignore")
            entries.append({
                "text": doc.relative_to(CORE).as_posix(),
                "chars": len(body),
                "has_course_table": all(h in body for h in ("学分", "课程")),
                "has_employment_table": any(h in body for h in EMPLOYMENT_HINTS),
            })
        texts[kind] = entries
    payload["texts"] = texts

    # ③ 结构化入库情况
    from edumatch.dataset import Dataset, major_matches

    ds = Dataset.build(with_policies=False)
    courses = ds.course_set(school=args.school, major=args.major, include_template=False) \
        if args.major else ds.course_set(school=args.school, include_template=False)
    facts = [f for f in ds.facts if f.school == args.school and f.value is not None
             and (not args.major or major_matches(str(f.major or ""), args.major))]
    scoped_jobs = ds.major_scope_jobs(args.major) if args.major else []
    payload["parsed"] = {
        "courses": len(courses),
        "courses_sample": [c.get("name") for c in courses[:8]],
        "employment_facts": len(facts),
        "employment_fact_types": sorted({f.fact_type for f in facts}),
        "major_scoped_jobs": len(scoped_jobs),
    }

    # ④ 动作建议（只基于事实判断，不猜）
    plans = materials.get("培养方案") or []
    plan_texts = texts.get("培养方案") or []
    if args.major and not courses:
        if any(t["has_course_table"] for t in plan_texts):
            payload["actions"].append(
                "培养方案正文里**有课程表**但引擎没解析出来 → 先修 "
                "edumatch/ingest/plan_tables.py 的版式适配（或直接读上面的 text 路径补数据）")
        elif plan_texts:
            payload["actions"].append(
                "培养方案正文里**没有课程表**（多为培养目标/毕业要求）→ 需要补采含课程表的完整版"
                "（或读课程大纲/专业介绍里的课程信息）")
        elif plans:
            payload["actions"].append("有培养方案 PDF 但没有正文 → 先跑 scripts\\import_extra_text.py")
        else:
            payload["actions"].append("本地没有该专业的培养方案 → 走联网补采（analyze.ps1 默认开启）")
    if args.major and not facts:
        payload["actions"].append(
            "该校该专业没有就业事实 → 查 年度报告/就业质量报告 是否含分专业表；"
            "没有就补采《毕业生就业质量报告》")
    if args.major and not scoped_jobs:
        payload["actions"].append(
            "该专业没有按专业导出的岗位语料 → 系统会退回全量招聘表按专业关键词切片"
            "（口径已在报告 demand_scope 披露）；要更准可导出该专业岗位表")
    if not payload["actions"]:
        payload["actions"].append("材料齐备：可直接跑 analyze.ps1 出报告")

    print(f"== {args.school} · {args.major or '（全部专业）'} ==")
    for kind, files in materials.items():
        print(f"[原始材料] {kind}: {len(files)} 份")
        for path in files[:6]:
            print(f"    {path}")
        if len(files) > 6:
            print(f"    … 其余 {len(files) - 6} 份")
    for kind, entries in texts.items():
        if entries:
            print(f"[正文缓存] {kind}: {len(entries)} 份（含课程表线索 "
                  f"{sum(1 for e in entries if e['has_course_table'])} 份）")
            for e in entries[:4]:
                print(f"    {e['text']}  {e['chars']} 字")
    print("[结构化入库] " + json.dumps(payload["parsed"], ensure_ascii=False))
    print("[建议动作]")
    for action in payload["actions"]:
        print(f"    - {action}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
