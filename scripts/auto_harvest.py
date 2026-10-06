"""CLI：按插件流程自动补采（点名院校 + 同类院校 × 全部材料类型）。

    python scripts\\auto_harvest.py --school 北京工业大学 --major 信息管理与信息系统
    python scripts\\auto_harvest.py --school 北京工业大学 --major 信息管理与信息系统 \
        --peer-max 4 --kinds 培养方案,专业介绍,课程大纲 --json data/processed/auto_harvest.json

离线复现（不联网，只看要不要采、采哪些）：加 ``--offline``。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from edumatch.auto_harvest import ALL_KINDS, auto_harvest, render_auto_harvest_markdown  # noqa: E402
from edumatch.config import load_settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="EduMatch 自动补采（插件流程）")
    ap.add_argument("--school", required=True)
    ap.add_argument("--major", default=None)
    ap.add_argument("--peer-max", type=int, default=3, help="同类院校数量上限")
    ap.add_argument("--mode", default="target", choices=["target", "region"],
                    help="target=点名院校+同类院校；region=该地区高校按批推进（多次调用累积）")
    ap.add_argument("--region", default="北京市")
    ap.add_argument("--batch-size", type=int, default=None, help="region 模式每轮采几所（默认 3）")
    ap.add_argument("--kinds", default=None, help="逗号分隔；缺省=全部材料类型")
    ap.add_argument("--timeout", type=int, default=None, help="单次采集超时秒数")
    ap.add_argument("--offline", action="store_true", help="不联网，只输出采集计划与缺口")
    ap.add_argument("--domain-candidate", action="append", default=[],
                    metavar="校名=URL",
                    help="你自己联网检索到的候选官网 URL（可多次）；系统核验通过后写入台账并采集")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    settings = load_settings()
    candidates: dict[str, list[str]] = {}
    for item in args.domain_candidate:
        if "=" not in item:
            raise SystemExit(f"[错误] --domain-candidate 需要 校名=URL 形式：{item}")
        name, url = item.split("=", 1)
        candidates.setdefault(name.strip(), []).append(url.strip())
    payload = auto_harvest(
        settings, school=args.school, major=args.major, peer_max=args.peer_max,
        kinds=([k.strip() for k in args.kinds.split(",") if k.strip()] if args.kinds else None),
        timeout_s=args.timeout, allow_network=not args.offline,
        domain_candidates=candidates,
        mode=args.mode, region=args.region, batch_size=args.batch_size,
    )
    print("\n".join(render_auto_harvest_markdown(payload)))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"台账已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
