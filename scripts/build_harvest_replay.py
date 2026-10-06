"""生成一个可离线复现的插件产物夹具（demo/harvest_replay）。

    python scripts/build_harvest_replay.py

夹具内容全部来自本包已有材料与采集台账里的真实来源链接，用于：

* 离线演示 ``--source-mode plugin/hybrid``（不需要联网、不需要插件在跑）；
* 单元测试 ``HarvestClient.replay`` → ``HarvestImporter`` 的完整链路。

它不是伪造数据：培养方案本体取自 ``data/source/培养方案/北京工业大学/``，
来源直链与承载页取自 ``data/source/采集台账`` 的真实记录。
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "demo" / "harvest_replay" / "北京工业大学"
LEDGER = ROOT / "data" / "source" / "采集台账" / "培养方案专业介绍_采集清单.csv"
SOURCE_PDF = ROOT / "data" / "source" / "培养方案" / "北京工业大学" / "2024_人工智能.pdf"


def _ledger_row(desc: str, year: str) -> dict[str, str]:
    if not LEDGER.exists():
        return {}
    for row in csv.DictReader(LEDGER.open(encoding="utf-8-sig")):
        if (row.get("学校") == "北京工业大学" and row.get("材料类型") == "培养方案"
                and row.get("专业/说明") == desc and str(row.get("年份")) == year):
            return row
    return {}


def main() -> int:
    if not SOURCE_PDF.exists():
        raise SystemExit(f"缺少夹具源文件：{SOURCE_PDF}")
    row = _ledger_row("人工智能", "2024")
    target = REPLAY / "新增数据" / "北京工业大学" / "培养方案" / SOURCE_PDF.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_PDF, target)
    records = [{
        "school": "北京工业大学",
        "kind": "培养方案",
        "desc": "2024_人工智能",
        "year": "2024",
        "file": f"北京工业大学/培养方案/{SOURCE_PDF.name}",
        "size_mb": round(SOURCE_PDF.stat().st_size / 1048576, 3),
        "sha1": row.get("sha1") or "",
        "status": "新增",
        "url": row.get("来源直链") or "",
        "page": row.get("承载页") or "",
        "inner": "",
    }]
    (REPLAY / "records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    (REPLAY / "candidates.md").write_text(
        "# 复现夹具：北京工业大学 · 培养方案（2024 人工智能）\n\n"
        "本目录模拟 edu-material-harvest 的一次真实采集产物（``records.json`` +\n"
        "``新增数据/<校>/<材料类型>/``），用于离线演示与测试 plugin / hybrid 模式。\n\n"
        f"- 本体：data/source/培养方案/北京工业大学/{SOURCE_PDF.name}\n"
        f"- 来源直链：{row.get('来源直链') or '（台账缺失）'}\n"
        f"- 承载页：{row.get('承载页') or '（台账缺失）'}\n",
        encoding="utf-8")
    print(json.dumps({"replay_dir": REPLAY.relative_to(ROOT).as_posix(),
                      "file": target.relative_to(ROOT).as_posix(),
                      "url": row.get("来源直链")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
