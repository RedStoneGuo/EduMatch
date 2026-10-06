"""诊断"为什么这个专业/院校出不了有用结论"（只读）。

    python scripts/diagnose_analysis_quality.py
    python scripts/diagnose_analysis_quality.py --school 北京工业大学 --major 机械工程

逐环节量化数据在管道里的损耗：

1. 培养方案 PDF → 课程记录（版式解析命中率）
2. 课程 → 技能（词表覆盖率：供给侧有多少课程根本没映射到任何技能）
3. 供需词表重叠（结构性问题：两侧是否在同一套技能空间里比较）
4. 插件产物的利用情况（下载的 PDF / 只登记链接的 HTML 材料页 / 未被使用的字段）
5. 规模量纲（宏观尺度必需的毕业生人数、岗位数）是否可得

每一项都给出"损耗在哪里、能不能补、怎么补"，不做无根据的推测。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def plan_yield(ds) -> dict:
    plans = sorted((ROOT / "data" / "source" / "培养方案").rglob("*.pdf"))
    by_src: Counter = Counter()
    sets = [ROOT / "data" / "raw" / "supplementary_courses.json"]
    sets += sorted((ROOT / "data" / "harvest").glob("*/courses.json"))
    for path in sets:
        if not path.exists():
            continue
        try:
            for row in json.loads(path.read_text(encoding="utf-8")):
                by_src[str(row.get("source_document") or "")] += 1
        except json.JSONDecodeError:
            continue
    per_school: dict[str, list[int]] = {}
    for path in plans:
        key = _rel(path)
        school = path.parent.name
        bucket = per_school.setdefault(school, [0, 0])
        bucket[0] += 1
        bucket[1] += 1 if by_src.get(key, 0) else 0
    rows = [{"school": s, "plans": n, "with_courses": y,
             "rate": round(y / n, 3) if n else 0.0}
            for s, (n, y) in sorted(per_school.items())]
    total = sum(r["plans"] for r in rows)
    ok = sum(r["with_courses"] for r in rows)
    return {"n_plans": total, "n_with_courses": ok,
            "yield_rate": round(ok / total, 4) if total else 0.0,
            "by_school": rows}


def course_skill_yield(ds) -> dict:
    """课程 → 技能：多少课程一门外语都没映射到（供给向量里的空洞）。"""
    unmapped = 0
    per_school: dict[str, list[int]] = {}
    for course in ds.courses:
        skills = ds._skills_from_text(f"{course.name} {course.description}")
        bucket = per_school.setdefault(course.school, [0, 0])
        bucket[0] += 1
        if skills:
            bucket[1] += 1
        else:
            unmapped += 1
    rows = [{"school": s, "courses": n, "mapped": y, "rate": round(y / n, 3) if n else 0.0}
            for s, (n, y) in sorted(per_school.items())]
    return {"n_courses": len(ds.courses), "n_unmapped": unmapped,
            "map_rate": round(1 - unmapped / len(ds.courses), 4) if ds.courses else 0.0,
            "by_school": rows}


def vocabulary_overlap(ds, school: str, major: str) -> dict:
    """供需两侧是否在同一套技能空间里——结构性可比性的核心检查。"""
    from edumatch.engine import ResearchEngine, build_plan

    courses = ds.course_set(school=school, major=major)
    if not courses:
        courses = ds.course_set(major=major)
    engine = ResearchEngine(ds)
    plan = build_plan(f"分析{school}{major}专业", ds)
    vocabulary, stats = engine._build_skill_vocabulary(plan, courses, ds)
    ds.major_vocabulary = vocabulary
    ds.vocabulary_mode = "data_driven"
    engine._active_major, engine._active_school = major, school

    demands = ds.demand_vector(major=major)
    demand_skills = {d.skill_name for d in demands}
    supply_vocab = {
        s for c in courses
        for s in engine._resolve_skill_names(c.get("name") or "", c.get("description") or "")
    }
    inter = demand_skills & supply_vocab
    return {
        "major": major, "school": school,
        "n_courses": len(courses),
        "vocabulary_stats": stats,
        "n_supply_terms": len(supply_vocab),
        "n_demand_skills": len(demand_skills),
        "n_overlap": len(inter),
        "overlap_ratio": round(len(inter) / len(demand_skills), 3) if demand_skills else 0.0,
        "demand_only_samples": sorted(demand_skills - supply_vocab)[:12],
        "supply_only_samples": sorted(supply_vocab - demand_skills)[:12],
        "note": ("两侧使用同一套数据驱动词表；需求独有=市场要但课程没教（真缺口），"
                 "供给独有=教了但市场没提。"),
    }


def plugin_html_usage() -> dict:
    """插件采回来的数据用了多少、漏了多少。"""
    rows: list[dict] = []
    harvest = ROOT / "data" / "harvest" / "收割"
    html_total = html_used = 0
    if harvest.exists():
        for school_dir in sorted(p for p in harvest.iterdir() if p.is_dir()):
            html_path = school_dir / "html_links.json"
            cand = school_dir / "candidates.md"
            records = school_dir / "records.json"
            n_html = 0
            if html_path.exists():
                try:
                    payload = json.loads(html_path.read_text(encoding="utf-8"))
                    n_html = len(payload) if isinstance(payload, list) else len(payload or {})
                except json.JSONDecodeError:
                    n_html = 0
            html_total += n_html
            rows.append({
                "school": school_dir.name,
                "has_records": records.exists(),
                "html_material_pages": n_html,
                "has_candidates": cand.exists(),
                "text_cache_dir": (ROOT / "data" / "harvest" / school_dir.name / "texts").exists(),
            })
    return {
        "n_harvest_dirs": len(rows),
        "html_material_pages": html_total,
        "html_material_pages_used": html_used,
        "rows": rows,
        "note": ("插件对「纯 HTML 材料页」只登记链接、不下载正文（其设计原则）。"
                 "本包目前只用下载回来的 PDF，HTML 材料页的正文没有被抓取利用——"
                 "这正是「能不能用上网页数据」的缺口。"),
    }


def scale_dimension(ds) -> dict:
    """宏观尺度必需的"规模量纲"是否可得。"""
    fact_types = Counter(f.fact_type for f in ds.facts)
    graduates = fact_types.get("graduates_total", 0) + fact_types.get("graduates_level", 0) \
        + fact_types.get("graduates", 0)
    scoped = [j for j in ds.jobs if j.get("corpus") == "major_export"]
    majors = {m for j in scoped for m in (j.get("major_scopes") or [])}
    return {
        "graduates_facts": graduates,
        "has_per_major_graduates": fact_types.get("graduates", 0) > 0,
        "n_jobs_total": len(ds.jobs),
        "n_jobs_major_scoped": len(scoped),
        "n_majors_with_jobs": len(majors),
        "note": ("宏观尺度 = 全部高校某专业总供给 × 岗位大类总需求。当前缺「毕业生人数 × 专业」的"
                 "连续口径（只有零散校级/分专业人数事实），因此宏观「数量缺口」还不能可靠计算；"
                 "技能维度的宏观聚合已具备（课程池 + 专业作用域岗位）。"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="诊断分析质量与数据损耗")
    ap.add_argument("--school", default="北京工业大学")
    ap.add_argument("--major", default="机械工程")
    args = ap.parse_args(argv)

    from edumatch.dataset import Dataset

    ds = Dataset.build()
    report = {
        "plan_to_courses": plan_yield(ds),
        "course_to_skill": course_skill_yield(ds),
        "vocabulary_overlap": vocabulary_overlap(ds, args.school, args.major),
        "plugin_html_usage": plugin_html_usage(),
        "scale_dimension": scale_dimension(ds),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
