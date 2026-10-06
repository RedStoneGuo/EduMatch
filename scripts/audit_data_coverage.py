"""数据利用覆盖审计（只读）：data/source 的每份材料是否真的进入了分析链路。

    python scripts/audit_data_coverage.py

审计口径与 ``edumatch/local_supply.py`` 完全一致——不再扫描包外的历史目录：

* ``培养方案``  → 课程库（学分/学时/必修，A 级）
* ``课程大纲 / 专业介绍 / 年度报告`` → 可检索正文；年度报告另出就业/教学事实
* ``政策文件`` → 政策库（docx 与 pdf 都走真实文本抽取）
* ``招聘数据`` → 岗位库（需求侧）
* ``文献``     → 方法论依据（D 级）

输出：``data/processed/data_coverage_audit.json`` + 终端报表。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.local_supply import LocalSupplyIndex  # noqa: E402
from edumatch.source_modes import harvest_status  # noqa: E402

PROCESSED = ROOT / "data" / "processed"


def main() -> int:
    index = LocalSupplyIndex.load(ROOT)
    coverage = index.coverage()
    by_type: dict[str, dict] = defaultdict(lambda: {"files": 0, "linked": 0, "unparsed": 0, "kb": 0.0})
    for record in index.records:
        bucket = by_type[record.material_type]
        bucket["files"] += 1
        bucket["kb"] += record.size_kb
        if not record.in_analysis:
            continue
        if record.derived or index.links_for(record.rel_path):
            bucket["linked"] += 1
        else:
            bucket["unparsed"] += 1

    print("== data/source 材料利用审计 ==")
    print(f"  文件 {coverage['n_files_total']} 份；分析口径 {coverage['n_files_analysis']} 份；"
          f"已连到结构化产物/正文 {coverage['n_files_linked']} 份"
          f"（利用率 {coverage['link_rate']:.1%}）；院校 {coverage['n_schools']} 所")
    print("")
    print(f"  {'材料类型':<12}{'文件':>6}{'已利用':>8}{'未解析':>8}{'体积MB':>10}")
    for name, bucket in sorted(by_type.items(), key=lambda kv: -kv[1]["files"]):
        print(f"  {name:<12}{bucket['files']:>6}{bucket['linked']:>8}{bucket['unparsed']:>8}"
              f"{bucket['kb'] / 1024:>10.1f}")
    if coverage["unparsed_by_type"]:
        print("")
        print("  未解析明细（如实说明，不静默）：")
        for item in coverage["unparsed_samples"][:10]:
            print(f"    - {item['path']}：{item['reason']}")

    harvest = harvest_status(ROOT)
    print("")
    print("== 插件收割产物（data/harvest）==")
    if not harvest["schools"]:
        print("  暂无：用 `--source-mode plugin|hybrid --harvest` 联网采集。")
    for item in harvest["schools"]:
        print(f"  - {item['school']}：来源材料 {item.get('n_source_materials')} 份，"
              f"课程 {item.get('n_courses')}，正文 {item.get('n_texts')}，事实 {item.get('n_facts')}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "data/source（规范结构：数据类型 → 院校）",
        "coverage": coverage,
        "by_material_type": {k: dict(v) for k, v in by_type.items()},
        "harvest": harvest,
    }
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "data_coverage_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("")
    print(f"[ok] 写入 {PROCESSED / 'data_coverage_audit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
