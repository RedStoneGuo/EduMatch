"""Print Core TSI V1 (27 indicators, A/B/C) next to TSI 2.0 (4 dimensions).

    python scripts/compare_tsi_versions.py
    python scripts/compare_tsi_versions.py --school 北京工业大学
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.dataset import Dataset  # noqa: E402
from edumatch.engine import ResearchEngine  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare TSI V1 and V2 on the same run")
    ap.add_argument("--school")
    ap.add_argument("--query", default="分析人工智能专业与2025年北京AI招聘市场的人才供需适配情况，并找出最关键的技能缺口")
    args = ap.parse_args(argv)

    query = args.query if not args.school else f"分析{args.school}人工智能专业与2025年北京AI招聘市场的人才供需适配"
    ds = Dataset.build()
    result = ResearchEngine(ds).run(query, include_template=True, simulation=True)
    v1, v2 = result["tsi_v1"], result["tsi_v2"]

    print("=" * 72)
    print("Core TSI Engine V1 —— 27 三级指标 / A·B·C（TSI指标搭建.docx 原体系）")
    print("=" * 72)
    print(f"TSI = {v1['tsi']}    公式 {v1['formula']}")
    print(f"可用指标 {v1['n_available']}/{v1['n_indicators']}    维度权重覆盖 {v1['weighted_coverage']}")
    for key, dim in v1["dimensions"].items():
        print(f"  {key} {dim['name']}：{dim['score']}  权重 {dim['level_weight']}  "
              f"覆盖率 {dim['coverage']}  可用 {dim['n_available']}/{dim['n_total']}")
        if dim["missing_indicators"]:
            print(f"      缺失：{', '.join(dim['missing_indicators'])}")
    rows = [m for m in v1["metrics"]]
    print("  指标明细：")
    for m in rows:
        value = "—" if m["value"] is None else m["value"]
        print(f"    {m['metric_id']:4} {m['name']:22} {value!s:>7}  {m['evidence_level']}  "
              f"{(m['reason'] or '')[:38]}")

    print()
    print("=" * 72)
    print("TSI 2.0 —— 四维 24 指标（A 培养基础 / B 培养过程 / C 培养结果 / D 市场需求）")
    print("=" * 72)
    print(f"TSI = {v2['tsi_v2']}（{v2['band']}）  可用指标 {v2['n_available']}/{v2['n_total']}  "
          f"维度覆盖 {v2['weighted_coverage']}")
    for key, dim in v2["dimensions"].items():
        print(f"  {dim['name']}：{dim['score']}  权重 {dim['weight']}  覆盖率 {dim['coverage']}  "
              f"可用 {dim['n_available']}/{dim['n_total']}")
    print(f"  缺失：{', '.join(v2['missing_indicators'])}")

    print()
    print("运行编号", result["run_id"])
    signals = {k: v for k, v in (v1.get("signals") or {}).items() if v}
    print(f"文本信号（来自教学质量报告，{v1.get('signal_source_chars', 0)} 字符）：{json.dumps(signals, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
