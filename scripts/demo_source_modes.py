"""演示三种供给端数据来源模式（离线，使用已有插件收割产物）。

    python scripts/demo_source_modes.py                          # local / plugin / hybrid
    python scripts/demo_source_modes.py --school 北京工业大学 --major 人工智能

前置：``data/harvest/<院校>/`` 下已有收割产物（跑过 ``--harvest``），否则
``plugin`` 模式会如实记"目标校供给证据不足"。没有收割产物时先执行：

    python scripts/build_harvest_replay.py        # 离线夹具（北京工业大学 2024 人工智能）
    python -c "from edumatch.harvest import HarvestClient,HarvestImporter; \
HarvestImporter('.').import_outcome(HarvestClient.replay('demo/harvest_replay/北京工业大学'))"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.core import TalentSupplyDemandAgent  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="演示 local / plugin / hybrid 三种数据来源模式")
    ap.add_argument("--school", default="北京工业大学")
    ap.add_argument("--major", default="人工智能")
    ap.add_argument("--occupation", default="大模型算法工程师")
    args = ap.parse_args(argv)

    query = f"分析{args.school}{args.major}专业与{args.occupation}岗位的匹配度"
    agent = TalentSupplyDemandAgent()
    print(f"问题：{query}\n")
    header = f"{'模式':<8}{'供给课程':>8}{'岗位匹配度':>12}{'Primary TSI':>14}{'本地课程':>10}{'收割课程':>10}"
    print(header)
    print("-" * len(header.encode("gbk", errors="ignore")))
    for mode in ("local", "plugin", "hybrid"):
        result = agent.research(query, target_occupation=args.occupation,
                                source_mode=mode, explain=False)
        data = result.data
        source = data.get("data_source") or {}
        occupation = data.get("occupation_match") or {}
        primary = data.get("primary_tsi") or {}
        print(f"{mode:<8}{len(data.get('courses') or []):>8}"
              f"{str(occupation.get('match_100') or '—'):>12}"
              f"{str(primary.get('primary_tsi') or '—'):>14}"
              f"{source.get('local_courses', 0):>10}{source.get('harvest_courses', 0):>10}")
        for note in source.get("notes") or []:
            print(f"         · {note}")
    print("\n说明：需求侧（招聘语料）三种模式一致；local 只用本地库，plugin 只用插件收割数据，")
    print("      hybrid 合并两者。缺失一律记 null，不补 0、不用其它口径顶替。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
