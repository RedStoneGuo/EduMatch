"""批量预取同类院校材料（先离线采好，分析时直接复用，秒级出结果）。

    python scripts/harvest_peers.py --school 北京工业大学 --major 人工智能 --max-peers 4
    python scripts/harvest_peers.py --school 北京工业大学 --peers 北京邮电大学,北京航空航天大学
    python scripts/harvest_peers.py --school 北京工业大学 --list        # 只看候选与域名缺口

同类院校由 ``edumatch/peers.py`` 按全国高校名单判定（层次 / 地域 / 校型 / 可采集性，
可解释排序，不是排行榜）。只采集**已核实官方域名**的院校；缺域名的会列出来，
由 Agent 联网搜索后用 ``scripts/resolve_school_domains.py`` 写入台账再重跑。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.config import load_settings  # noqa: E402
from edumatch.peers import PeerSelector  # noqa: E402
from edumatch.source_modes import run_plugin_harvest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="批量预取同类院校材料")
    ap.add_argument("--school", required=True, help="目标院校")
    ap.add_argument("--major", default=None, help="目标专业（用于筛出同专业候选）")
    ap.add_argument("--max-peers", type=int, default=4)
    ap.add_argument("--peers", default=None, help="显式指定同类院校（逗号分隔），覆盖自动判定")
    ap.add_argument("--kinds", default="培养方案", help="采集材料类型，逗号分隔")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--list", action="store_true", help="只列出候选，不采集")
    args = ap.parse_args(argv)

    settings = load_settings()
    selector = PeerSelector.from_project(ROOT)
    if args.peers:
        names = [p.strip() for p in args.peers.split(",") if p.strip()]
        candidates = []
        for name in names:
            uni = selector.catalog.get(name)
            candidates.append({
                "school": name, "domain": selector.domains.get(name, ""),
                "province": uni.province if uni else "", "city": uni.city if uni else "",
                "tiers": list(uni.tiers) if uni else [], "reasons": ["调用方指定"], "score": 0.0,
            })
        note = {"note": "调用方显式指定"}
    else:
        peers, note = selector.resolve(args.school, major=args.major, max_peers=args.max_peers)
        candidates = [c.to_dict() for c in peers]

    missing = [c["school"] for c in candidates if not c.get("domain")]
    print(json.dumps({
        "target": args.school, "note": note.get("note"),
        "candidates": [{k: c.get(k) for k in ("school", "province", "tiers", "domain", "score")}
                       for c in candidates],
        "missing_domain": missing,
    }, ensure_ascii=False, indent=1))
    if args.list:
        return 0

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    results = []
    for item in candidates:
        name = str(item["school"])
        if (ROOT / "data" / "harvest" / name / "courses.json").exists():
            results.append({"school": name, "status": "cached"})
            print(f"[cached] {name}")
            continue
        if not item.get("domain"):
            results.append({"school": name, "status": "missing_domain"})
            print(f"[skip]   {name}：未核实官方域名（用 scripts/resolve_school_domains.py 补）")
            continue
        try:
            outcome, imported = run_plugin_harvest(
                settings, name, domain=str(item["domain"]), kinds=kinds, timeout_s=args.timeout)
            (ROOT / "data" / "processed").mkdir(parents=True, exist_ok=True)
            ok = (ROOT / "data" / "harvest" / name / "courses.json").exists()
            results.append({"school": name, "status": "harvested" if ok else "no_courses",
                            "downloaded": outcome.n_materials,
                            "installed": len(imported.installed)})
            print(f"[{'ok' if ok else 'warn'}]     {name}：下载 {outcome.n_materials} 份，"
                  f"入库 {len(imported.installed)} 份，解析课程 {imported.n_courses}")
        except Exception as exc:  # noqa: BLE001
            results.append({"school": name, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            print(f"[error]  {name}：{type(exc).__name__}: {exc}")
    print(json.dumps({"results": results}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
