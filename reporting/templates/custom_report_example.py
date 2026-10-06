# -*- coding: utf-8 -*-
"""自定义报告页模板：复用 Core 主题与构件，只写你需要的章节。

运行（在 EduMatch 目录下）：

    python reporting/templates/custom_report_example.py --result <result.json> --out custom.html

约定：外壳用 `theme.CSS`/`theme.JS` 与 `components.nav_html`，图表用
`components` 里的构件；**不要另写 CSS**。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from reporting import components as C  # noqa: E402
from reporting.theme import CSS, JS  # noqa: E402


def build_sections(result: dict) -> str:
    """在这里写你自己的章节。下面给出两个最小示例。"""
    plan = result.get("plan") or {}
    primary = result.get("primary_tsi") or {}
    gaps = result.get("skill_gaps") or {}

    stats = (
        '<div class="stats">'
        + C.stat_card(C.f2(primary.get("primary_tsi")), "", "Primary TSI（唯一正式总分）",
                      f"覆盖率 {C.pct(primary.get('weighted_coverage'), 0)}%")
        + C.stat_card(str(len(gaps.get("rows") or [])), "项", "参与比对技能", "")
        + "</div>"
    )
    rows = "".join(
        f'<tr><td>{C.e(r.get("skill"))}</td><td class="n">{C.f2(r.get("demand"))}</td>'
        f'<td class="n">{C.f2(r.get("supply"))}</td><td class="n">{C.f2(r.get("gap"))}</td></tr>'
        for r in (gaps.get("rows") or [])[:15])
    return (
        '<section class="view on" id="custom"><div class="wrap">'
        '<div class="sec-head"><div><div class="eyebrow">自定义章节</div>'
        f'<h2>{C.e(plan.get("school") or "")}{C.e(plan.get("major") or "")}</h2></div></div>'
        + stats
        + '<div class="src-block"><h3>缺口明细</h3><table class="tbl">'
        '<thead><tr><th>技能</th><th class="n">需求</th><th class="n">供给</th>'
        f'<th class="n">缺口</th></tr></thead><tbody>{rows}</tbody></table></div>'
        + C.retrieval_ledger_html({"retrieval_ledger": result.get("retrieval_ledger")})
        + "</div></section>"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="自定义报告模板")
    ap.add_argument("--result", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    payload = json.loads(Path(args.result).read_text(encoding="utf-8"))
    result = payload.get("data") or payload
    body = C.nav_html("all") + build_sections(result)
    html = ("<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">\n"
            f"<title>EduMatch 自定义报告</title><style>{CSS}</style></head>\n"
            f"<body>{body}<script>{JS}</script></body></html>\n")
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"[ok] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
