"""清洗本地数据并建立 ``data/source`` 全量索引（本地供给数据层的唯一入口）。

    python scripts/build_source_index.py             # 清洗 + 建索引 + 写报告
    python scripts/build_source_index.py --check     # 只审计覆盖率，不写盘

产出：

* ``data/processed/source_inventory.json``   逐份材料的清单与关联（含利用率审计）
* ``data/raw/local_supply_index.json``       模型可直接调用的本地供给索引
* ``data/processed/source_cleaning_log.json`` 清洗日志（院校名归一/回填/未覆盖清单）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.local_supply import LocalSupplyIndex, clean_structured_schools  # noqa: E402

CLEAN_LOG = ROOT / "data" / "processed" / "source_cleaning_log.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="清洗本地数据并建立 data/source 索引")
    ap.add_argument("--check", action="store_true", help="只审计，不写盘")
    args = ap.parse_args(argv)

    cleaning = clean_structured_schools(ROOT)
    index = LocalSupplyIndex.build(ROOT)
    coverage = index.coverage()

    if not args.check:
        index.save()
        CLEAN_LOG.write_text(json.dumps(cleaning, ensure_ascii=False, indent=1), encoding="utf-8")

    report = {
        "cleaning": cleaning,
        "coverage": coverage,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
