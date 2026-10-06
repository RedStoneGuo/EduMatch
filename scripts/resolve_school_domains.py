"""核实院校官方域名并写入域名台账（插件联网收割的前置步骤）。

    python scripts/resolve_school_domains.py --list peers --school 华中科技大学
    python scripts/resolve_school_domains.py --school 武汉大学 --domain whu.edu.cn
    python scripts/resolve_school_domains.py --verify-only --school 武汉大学 --domain whu.edu.cn

edu-material-harvest 的红线是「绝不猜域名」——域名必须来自可核实来源。本脚本的做法是：

1. 候选域名由调用方（人或 Agent 的联网搜索）给出，或在 ``--list peers`` 中列出待补清单；
2. **实测确认**：请求 ``https://<域名>``，要求 HTTP 200、返回 HTML，且页面里出现该校全名
   或其简称（去掉"大学/学院"后的前缀）。任何一项不满足就不入台账；
3. 通过后写入 ``data/harvest/domains.json``，附 ``evidence``（实测状态码、命中词、时间）。

这既守住了"不猜"，也让域名台账可以随分析推进持续扩张。
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DOMAINS = ROOT / "data" / "harvest" / "domains.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _short_name(school: str) -> str:
    name = re.sub(r"[（(].*?[)）]", "", school).strip()
    for suffix in ("大学", "学院", "学校"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def fetch(url: str, timeout: int = 25) -> tuple[int, str, str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
        raw = response.read(400_000)
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        return response.status, text, response.geturl()


def verify(school: str, domain: str) -> dict:
    """实测确认域名归属；返回含 ok/evidence 的结果。"""
    schools = [s for s in {school, _short_name(school)} if s]
    attempts: list[dict] = []
    for url in (f"https://{domain}", f"https://www.{domain}"):
        try:
            status, text, final = fetch(url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ssl.SSLError) as exc:
            attempts.append({"url": url, "status": None, "error": f"{type(exc).__name__}: {exc}"})
            continue
        hits = [s for s in schools if s in text]
        attempts.append({"url": url, "status": status, "final_url": final,
                         "size": len(text), "name_hits": hits})
        if status == 200 and hits:
            return {"ok": True, "domain": domain, "matched_name": hits[0], "attempts": attempts,
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                    "evidence": f"实测 {url} 返回 {status}，页面出现「{hits[0]}」"}
    return {"ok": False, "domain": domain, "attempts": attempts,
            "reason": "未通过实测（状态码非 200 或页面未出现校名）"}


def _load() -> dict:
    if DOMAINS.exists():
        try:
            return json.loads(DOMAINS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _save(payload: dict) -> None:
    DOMAINS.parent.mkdir(parents=True, exist_ok=True)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    DOMAINS.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="核实院校官方域名并写入台账")
    ap.add_argument("--school", default=None)
    ap.add_argument("--domain", default=None)
    ap.add_argument("--list", choices=["peers", "schools"], default=None,
                    help="peers=列出该校同类候选里缺域名的院校；schools=列出台账已有院校")
    ap.add_argument("--max-peers", type=int, default=10)
    ap.add_argument("--verify-only", action="store_true", help="只核实，不写入台账")
    app = ap.parse_args(argv)
    payload = _load()

    if app.list == "schools":
        names = sorted(k for k in payload if not k.startswith("_") and k != "generated_at")
        print(json.dumps({"n": len(names), "schools": names}, ensure_ascii=False, indent=1))
        return 0

    if app.list == "peers":
        if not app.school:
            print("[error] --list peers 需要 --school")
            return 1
        from edumatch.peers import PeerSelector

        selector = PeerSelector.from_project(ROOT)
        peers, _ = selector.resolve(app.school, max_peers=app.max_peers)
        missing = [p.school for p in peers if not p.harvestable]
        print(json.dumps({
            "target": app.school,
            "n_peers": len(peers),
            "missing_domain": missing,
            "action": "用联网搜索确认这些学校官网后，逐个跑 --school <校> --domain <域名> 写入台账",
        }, ensure_ascii=False, indent=1))
        return 0

    if not (app.school and app.domain):
        print("[error] 需要 --school 与 --domain（或 --list peers|schools）")
        return 1
    result = verify(app.school, app.domain)
    print(json.dumps(result, ensure_ascii=False, indent=1)[:1500])
    if result["ok"] and not app.verify_only:
        payload[app.school] = {
            "domain": result["domain"], "all_domains": [result["domain"]],
            "n_source_urls": payload.get(app.school, {}).get("n_source_urls", 0),
            "ledgers": payload.get(app.school, {}).get("ledgers", []),
            "evidence": result["evidence"] + "（resolve_school_domains.py 实测确认）",
            "verified_at": result["verified_at"],
        }
        _save(payload)
        print(f"[ok] 已写入 {DOMAINS.relative_to(ROOT).as_posix()}：{app.school} → {app.domain}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
