"""从本地采集台账（真实来源直链/承载页）提取各校官方域名，生成插件联网收割所需的域名台账。

    python scripts/build_harvest_domains.py            # 写 data/harvest/domains.json
    python scripts/build_harvest_domains.py --check    # 只打印，不写盘

edu-material-harvest 的红线是「绝不猜域名」：域名必须来自可核实的官方来源。本脚本
不联网、不臆测，只把项目**已经采集过**的自有台账里的 ``*.edu.cn`` 域名归并成
``{院校: {domain, sources, evidence}}``，插件与 agent 直接读它。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "source" / "采集台账"
OUT = ROOT / "data" / "harvest" / "domains.json"

URL_FIELDS = ("来源直链", "承载页", "链接", "url", "URL")
SCHOOL_FIELDS = ("学校", "院校", "school")
PAGES = ROOT / "data" / "harvest" / "carrier_pages.json"


def _apex(host: str) -> str:
    host = host.lower().strip()
    if not host or not host.endswith(".edu.cn"):
        return ""
    parts = host.split(".")
    # 取注册域：xxx.edu.cn（含二级学院域名的三级写法也归到 xxx.edu.cn）
    if len(parts) >= 3:
        return ".".join(parts[-3:])
    return host


def collect() -> dict[str, dict]:
    found: dict[str, dict] = defaultdict(lambda: {"domains": defaultdict(set), "sources": set()})
    if not LEDGER_DIR.exists():
        return {}
    for path in sorted(LEDGER_DIR.glob("*.csv")):
        try:
            rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        except (UnicodeDecodeError, OSError):
            continue
        for row in rows:
            school = ""
            for key in SCHOOL_FIELDS:
                if row.get(key):
                    school = str(row[key]).strip()
                    break
            if not school:
                continue
            for key in URL_FIELDS:
                value = str(row.get(key) or "").strip()
                if not value:
                    continue
                host = urlparse(value).hostname or ""
                apex = _apex(host)
                if apex:
                    found[school]["domains"][apex].add(value)
                    found[school]["sources"].add(path.name)
    out: dict[str, dict] = {}
    for school, payload in sorted(found.items()):
        domains = sorted(payload["domains"], key=lambda d: (-len(payload["domains"][d]), d))
        if not domains:
            continue
        out[school] = {
            "domain": domains[0],
            "all_domains": domains,
            "n_source_urls": sum(len(v) for v in payload["domains"].values()),
            "ledgers": sorted(payload["sources"]),
            "evidence": "来自本项目采集台账的真实 *.edu.cn 来源链接（未猜测）",
        }
    return out


def collect_pages() -> dict[str, dict]:
    """按（学校, 材料类型）归并承载页 URL（去重、保序）。"""
    out: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    if not LEDGER_DIR.exists():
        return {}
    for path in sorted(LEDGER_DIR.glob("*.csv")):
        try:
            rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        except (UnicodeDecodeError, OSError):
            continue
        for row in rows:
            school = str(row.get("学校") or "").strip()
            kind = str(row.get("材料类型") or "").strip() or "未分类"
            page = str(row.get("承载页") or "").strip()
            if not school or not page or urlparse(page).hostname is None:
                continue
            if page not in out[school][kind]:
                out[school][kind].append(page)
    return {school: {kind: urls for kind, urls in kinds.items()}
            for school, kinds in sorted(out.items())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从采集台账生成官方域名台账")
    ap.add_argument("--check", action="store_true", help="只打印，不写盘")
    args = ap.parse_args(argv)
    payload = collect()
    pages = collect_pages()
    if not args.check:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "院校官方 *.edu.cn 域名白名单；来源为本项目采集台账的真实链接。",
            **payload,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        PAGES.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": ("承载页直采台账：大站/子域被 WAF 挡住时，把挂着材料的页面交给 "
                     "edu-material-harvest 的 harvest_pages 枚举下载。全部来自本项目采集台账。"),
            "schools": pages,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_schools": len(payload),
                      "schools": {k: v["domain"] for k, v in payload.items()},
                      "n_carrier_pages": sum(len(urls) for kinds in pages.values()
                                             for urls in kinds.values())},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
