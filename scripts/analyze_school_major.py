"""Produce a complete analysis (process + result) for one school + major.

    python scripts/analyze_school_major.py --school 北京工业大学 --major 软件工程

Writes the full 18-section report plus a machine-readable JSON into
data/processed/case_reports/<school>_<major>/.
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

from agent.core import TalentSupplyDemandAgent  # noqa: E402
from agent.report import render_markdown  # noqa: E402
from edumatch.dataset import Dataset  # noqa: E402
from edumatch.engine import ResearchEngine, build_plan  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Complete school+major analysis")
    ap.add_argument("--school", required=True)
    ap.add_argument("--major", required=True)
    ap.add_argument("--year", type=int)
    ap.add_argument("--template", action="store_true", default=True)
    ap.add_argument("--no-template", dest="template", action="store_false")
    args = ap.parse_args(argv)

    dataset = Dataset.build()
    query = (f"分析{args.school}{args.major}专业与北京就业市场的供需适配情况，"
             f"识别专业-岗位技能缺口并给出培养方案建议")
    plan = build_plan(query, dataset)
    engine = ResearchEngine(dataset)
    result = engine.run(query, include_template=args.template, simulation=True)
    report = render_markdown(result)
    result["report"] = report

    out_dir = ROOT / "data" / "processed" / "case_reports" / f"{args.school}_{args.major}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    v1 = result.get("tsi_v1") or {}
    summary = {
        "query": query,
        "run_id": result["run_id"],
        "school": args.school,
        "major": args.major,
        "family": plan.family,
        "tsi_v1": v1.get("tsi"),
        "tsi_v1_available": f"{v1.get('n_available')}/{v1.get('n_indicators')}",
        "tsi_v1_dims": {k: v["score"] for k, v in (v1.get("dimensions") or {}).items()},
        "tsi_v2": (result.get("tsi_v2") or {}).get("tsi_v2"),
        "matching": result["matching"]["matching_score_100"],
        "gap_index": result["skill_gaps"]["skill_gap_index"],
        "top_gaps": [{"skill": g["skill"], "demand": g["demand"], "supply": g["supply"],
                      "gap": g["gap"], "severity": g["severity"]}
                     for g in result["skill_gaps"]["rows"] if g["status"] == "gap"][:8],
        "market": {
            "n_target_jobs": result["market"].get("n_target_jobs"),
            "raw_count": result["market"].get("raw_count"),
            "deduplicated_count": result["market"].get("deduplicated_count"),
            "salary_premium": result["market"].get("salary_premium"),
            "bachelor_share": result["market"].get("bachelor_share"),
            "master_plus_share": result["market"].get("master_plus_share"),
        },
        "n_tools": len(result["tool_calls"]),
        "n_evidence": len(result["evidence"]),
        "outputs": {"report": str(out_dir / "report.md"), "result": str(out_dir / "result.json")},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"\n[ok] 报告已写入 {summary['outputs']['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
