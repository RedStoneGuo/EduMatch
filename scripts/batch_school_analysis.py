"""Run the same school+major analysis for several schools and compare them.

    python scripts/batch_school_analysis.py --major 软件工程 \
        --schools 北京理工大学 北京航空航天大学 中国地质大学 中国矿业大学 中国石油大学

Writes one full report per school plus a comparison table.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from agent.report import render_markdown  # noqa: E402
from edumatch.dataset import Dataset  # noqa: E402
from edumatch.engine import ResearchEngine, build_plan  # noqa: E402


def analyse(engine: ResearchEngine, school: str, major: str,
            occupation: str | None = None) -> tuple[dict, str, dict]:
    query = (f"分析{school}{major}专业与{occupation or '北京就业市场'}的匹配度，"
             f"识别专业-岗位技能缺口并给出培养方案建议")
    plan = build_plan(query, engine.dataset)
    result = engine.run(query, include_template=True, simulation=True,
                        target_occupation=occupation)
    report = render_markdown(result)
    result["report"] = report
    # 指定目标岗位时把岗位写进目录名，便于同一院校专业对比多个岗位
    suffix = f"_{occupation}" if occupation else ""
    out_dir = ROOT / "data" / "processed" / "case_reports" / f"{school}_{major}{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    v1 = result.get("tsi_v1") or {}
    summary = {
        "school": school,
        "major": major,
        "target_occupation": occupation,
        "occupation_match": (result.get("occupation_match") or {}).get("match_100"),
        "occupation_band": (result.get("occupation_match") or {}).get("band"),
        "family": plan.family,
        "run_id": result["run_id"],
        "tsi_v1": v1.get("tsi"),
        "available": f"{v1.get('n_available')}/{v1.get('n_indicators')}",
        "dims": {k: v["score"] for k, v in (v1.get("dimensions") or {}).items()},
        "tsi_v2": (result.get("tsi_v2") or {}).get("tsi_v2"),
        "matching": result["matching"]["matching_score_100"],
        "recall": result["matching"].get("recall"),
        "gap_index": result["skill_gaps"]["skill_gap_index"],
        "top_gaps": [g["skill"] for g in result["skill_gaps"]["rows"] if g["status"] == "gap"][:4],
        "missing_v1": v1.get("missing_indicators") or [],
        "report": str(out_dir / "report.md"),
    }
    return summary, report, result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Batch school+major analysis")
    ap.add_argument("--major", default="软件工程")
    ap.add_argument("--schools", nargs="+", required=True)
    ap.add_argument("--occupation", default=None,
                    help="目标岗位（如“大模型算法工程师”）；给出后输出岗位匹配度")
    args = ap.parse_args(argv)

    dataset = Dataset.build()
    engine = ResearchEngine(dataset)
    summaries = []
    for school in args.schools:
        print(f"\n=== {school} · {args.major} ===")
        summary, _, _ = analyse(engine, school, args.major, args.occupation)
        summaries.append(summary)
        print(f"  V1 {summary['tsi_v1']} ({summary['available']})  V2 {summary['tsi_v2']}  "
              f"匹配度 {summary['matching']}  缺口 {summary['gap_index']}")
        if summary.get("target_occupation"):
            print(f"  目标岗位「{summary['target_occupation']}」匹配度 "
                  f"{summary['occupation_match']}/100（{summary['occupation_band']}）")
        print(f"  缺口: {summary['top_gaps'] or '无'}")
        print(f"  报告: {summary['report']}")

    out_dir = ROOT / "data" / "processed" / "case_reports"
    (out_dir / f"_comparison_{args.major}.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    header = ("| 学校 | 目标岗位 | 岗位匹配度 | 匹配带 | TSI V1 | V1可用 | TSI V2 | "
              "Skill Fit | 召回 | 缺口指数 | 主要缺口 |\n"
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
    body = ""
    for s in summaries:
        dims = s["dims"]
        body += (f"| {s['school']} | {s.get('target_occupation') or '—'} | "
                 f"**{s.get('occupation_match') if s.get('occupation_match') is not None else '—'}** | "
                 f"{s.get('occupation_band') or '—'} | {s['tsi_v1']} | {s['available']} | "
                 f"{s['tsi_v2']} | {s['matching']} | {s['recall']} | {s['gap_index']} | "
                 f"{'、'.join(s['top_gaps']) or '无'} |\n")
    table = header + body
    (out_dir / f"_comparison_{args.major}.md").write_text(
        f"# {args.major} 专业多校对比\n\n{table}", encoding="utf-8")
    print("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
