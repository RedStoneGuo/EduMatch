"""诊断：三个策展专业总结文档（data/raw/majors_*.txt）还剩哪些依赖。

    python scripts/check_curated_dependency.py

回答的问题是："能否抛弃 AI竞赛数据归档 的策展文档，完全基于本地数据库分析？"
脚本只读，不改任何数据；输出各来源对课程/专业族/金标准的贡献，以及去掉策展文档后
各环节的实际行为（哪些专业还能分析、哪些会直接拒绝作答）。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.dataset import Dataset  # noqa: E402
from edumatch.engine import ResearchEngine, build_plan  # noqa: E402


def _source_of(doc: str) -> str:
    name = str(doc).replace("/", "\\").rsplit("\\", 1)[-1]
    return name.split("#")[0]


def main() -> int:
    ds = Dataset.build()
    n_curated = sum(1 for c in ds.courses if _source_of(c.source_document).startswith("majors_"))
    by_source = Counter(_source_of(c.source_document) for c in ds.courses)
    plan_courses = [c for c in ds.courses if ".pdf" in str(c.source_document).lower()]

    print("== 1. 课程来源构成 ==")
    for name, count in by_source.most_common():
        mark = "  <- 策展文档" if name.startswith("majors_") else ""
        print(f"  {name:<52} {count:>6}{mark}")
    print(f"  合计 {len(ds.courses)} 门；其中策展文档 {n_curated} 门、培养方案 PDF {len(plan_courses)} 门")

    print("\n== 2. 专业族注册表 ==")
    print(f"  available_families 来自：{sorted(ds.available_families)}")
    print(f"  由课程/事实可推导的族：{sorted({c.family for c in ds.courses if c.family})}")

    print("\n== 3. 其他数据源（与策展文档无关）==")
    print(f"  教育事实 {len(ds.facts)} 条（PDF 抽取 + 分专业行）；政策 {len(ds.policies)} 份；"
          f"岗位 {len(ds.jobs)} 条；校级事实覆盖 {len({f.school for f in ds.facts if f.family == 'school'})} 校")
    print(f"  金标准（仅用于校核，不参与分析）：{len(ds.golden_facts)} 条"
          if ds.golden_facts else "  金标准：未加载")

    # ---- 模拟：去掉策展文档 ----
    ds2 = Dataset.build(with_golden=False)
    ds2.courses = [c for c in ds2.courses if not _source_of(c.source_document).startswith("majors_")]
    ds2.available_families = {}
    ds2._course_cache.clear()
    engine2 = ResearchEngine(ds2)

    print("\n== 4. 去掉策展文档后的实际行为 ==")
    print(f"  剩余课程 {len(ds2.courses)} 门；available_families={ds2.available_families or '空'}")
    for query in ("分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度",
                  "分析北京理工大学会计学专业的供需适配",
                  "分析北京工业大学软件工程专业的就业情况"):
        plan = build_plan(query, ds2)
        print(f"  [{plan.mode}] {plan.major} / family={plan.family or '无'}  <- {query[:28]}")

    # 保留族注册表、只去掉课程内容的对照
    ds3 = Dataset.build(with_golden=False)
    ds3.courses = [c for c in ds3.courses if not _source_of(c.source_document).startswith("majors_")]
    ds3._course_cache.clear()
    engine3 = ResearchEngine(ds3)
    print("\n== 5. 只去掉策展课程内容、保留族注册表 ==")
    for query, occ in (
        ("分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度", "大模型算法工程师"),
        ("分析北京工业大学人工智能专业与人工智能相关岗位的匹配度", "人工智能相关岗位"),
        ("分析北京理工大学会计学专业的供需适配", None),
        ("分析北京工业大学软件工程专业的就业情况", None),
    ):
        result = engine3.run(query, include_template=True, target_occupation=occ)
        occ_match = result.get("occupation_match") or {}
        print(f"  {result['plan']['major']:<8} family={result['plan']['family'] or '无':<5} "
              f"状态={result.get('status', 'ok'):<20} "
              f"目标校课程={((result.get('supply') or {}).get('target') or {}).get('n_courses')} "
              f"岗位匹配度={occ_match.get('match_100')} "
              f"PrimaryTSI={(result.get('primary_tsi') or {}).get('primary_tsi')}")

    payload = {
        "courses_total": len(ds.courses),
        "courses_from_curated": n_curated,
        "courses_from_plan_pdf": len(plan_courses),
        "by_source": dict(by_source),
        "available_families": sorted(ds.available_families),
        "without_curated": {
            "courses": len(ds2.courses),
            "families": sorted(ds2.available_families),
        },
    }
    out = ROOT / "data" / "processed" / "curated_dependency.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] 写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
