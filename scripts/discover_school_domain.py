"""CLI：核验大模型联网检索到的院校官网 URL，通过后写入域名台账。

    python scripts\\discover_school_domain.py --school 中国石油大学（北京） \
        --candidate https://www.cup.edu.cn/

核验标准（全部满足才算通过）：官方教育域后缀 + HTTP 200 + 页面含院校名。
通过后写入 ``data/harvest/domains.json``（保留原条目），并把证据一并记录；
不通过会打印原因，且**不写台账**。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from edumatch.domain_discovery import discover_domain, verify_candidate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="院校官方域名发现与核验")
    ap.add_argument("--school", required=True)
    ap.add_argument("--candidate", action="append", default=[],
                    help="候选 URL（可多次；通常来自你自己联网检索到的官网/承载页）")
    ap.add_argument("--offline", action="store_true", help="只做格式检查，不发请求")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    if args.candidate and args.offline:
        payload = {"school": args.school, "candidates": [
            verify_candidate(u, args.school, allow_network=False) for u in args.candidate]}
    else:
        payload = discover_domain(CORE, args.school, candidates=args.candidate,
                                  allow_network=not args.offline)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
