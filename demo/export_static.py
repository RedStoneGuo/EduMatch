"""Export a fully offline HTML demo page (no CDN, no JavaScript requirement).

    python demo/export_static.py --out demo/output/index.html --simulate

Useful when the competition venue has no reliable network or when Streamlit is
unavailable; the numbers are identical because both use ResearchEngine.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.core import TalentSupplyDemandAgent  # noqa: E402

CSS = """
:root { color-scheme: light; }
body { font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; margin: 0;
       background: #f6f7fb; color: #1c2333; }
header { background: linear-gradient(120deg,#1c3faa,#3b82f6); color: #fff; padding: 28px 40px; }
header h1 { margin: 0 0 6px; font-size: 26px; }
main { max-width: 1180px; margin: -18px auto 60px; padding: 0 20px; }
section { background: #fff; border-radius: 12px; padding: 20px 24px; margin: 18px 0;
          box-shadow: 0 2px 10px rgba(20,30,60,.06); }
h2 { font-size: 18px; margin-top: 0; border-left: 4px solid #3b82f6; padding-left: 10px; }
h3 { font-size: 15px; color: #374151; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }
th, td { border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #f3f6ff; }
.cards { display: flex; gap: 14px; flex-wrap: wrap; }
.card { flex: 1 1 180px; background: #f8faff; border: 1px solid #e2e8ff; border-radius: 10px; padding: 14px; }
.card .k { font-size: 12px; color: #5b6478; }
.card .v { font-size: 24px; font-weight: 700; color: #1c3faa; }
.warn { background: #fff7ed; border-left: 4px solid #f59e0b; padding: 10px 14px; border-radius: 6px; }
.ok { background: #f0fdf4; border-left: 4px solid #22c55e; padding: 10px 14px; border-radius: 6px; }
.bad { background: #fef2f2; border-left: 4px solid #ef4444; padding: 10px 14px; border-radius: 6px; }
.bar { height: 14px; background: #e5e7eb; border-radius: 7px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: linear-gradient(90deg,#3b82f6,#22c55e); }
small { color: #6b7280; }
"""


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def bar_row(label: str, value: float | None) -> str:
    width = 0 if value is None else max(0.0, min(float(value), 1.0)) * 100
    text = "—" if value is None else f"{value:.3f}"
    return (f"<div style='margin:6px 0'><small>{esc(label)}　{text}</small>"
            f"<div class='bar'><span style='width:{width:.1f}%'></span></div></div>")


def build_html(data: dict) -> str:
    plan, tsi, matching, gaps = data["plan"], data["tsi_v2"], data["matching"], data["skill_gaps"]
    primary = data.get("primary_tsi") or {}
    scope = data.get("course_scope") or {}
    parts: list[str] = [f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
                        "<title>EduMatch 演示</title>", f"<style>{CSS}</style></head><body>",
                        "<header><h1>EduMatch｜高校人才供需适配研究 Agent</h1>",
                        "<div>从培养方案到就业市场的智能供需诊断与培养优化 · Evidence-driven</div></header>",
                        "<main>"]

    parts.append("<section><h2>① 研究任务</h2>")
    parts.append(f"<p><b>问题</b>：{esc(data['query'])}<br><b>模式</b>：{esc(data['mode'])}　"
                 f"<b>专业</b>：{esc(plan['major'])}　<b>学校</b>：{esc(plan['school'] or '北京 211 同类专业样本')}　"
                 f"<b>运行编号</b>：{esc(data['run_id'])}</p>")
    parts.append(table(["步", "Skill", "动作"], [[s["id"], s["skill"], s["action"]] for s in plan["steps"]]))
    parts.append("</section>")

    parts.append("<section><h2>② 核心指标</h2><div class='cards'>")
    for k, v in (("Primary TSI（正式）", primary.get("primary_tsi")),
                 ("Skill Fit", matching["matching_score_100"]),
                 ("Skill Gap Index", gaps["skill_gap_index"]),
                 ("主指标覆盖率", f"{(primary.get('weighted_coverage') or 0) * 100:.0f}%"),
                 ("TSI 2.0（研究对照）", tsi["tsi_v2"]),
                 ("证据条目", len(data["evidence"])), ("工具调用", len(data["tool_calls"]))):
        parts.append(f"<div class='card'><div class='k'>{esc(k)}</div><div class='v'>{esc(v)}</div></div>")
    parts.append("</div>")
    parts.append(f"<p class='warn'><b>Skill Fit 口径</b>：{esc(scope.get('used_for_fit'))}　"
                 f"{esc(scope.get('reason') or '')}</p>")
    parts.append(f"<p class='warn'><b>缺失指标（记 null，不记 0）</b>：{esc(', '.join(tsi['missing_indicators']) or '无')}</p>")
    parts.append("</section>")

    parts.append("<section><h2>③ Agent 工作流</h2>")
    parts.append(table(["工具", "状态", "耗时(ms)", "参数"],
                       [[t["tool"], t["status"], t["elapsed_ms"], str(t["arguments"])[:60]] for t in data["tool_calls"]]))
    parts.append("</section>")

    parts.append("<section><h2>④ 技能供给与需求</h2>")
    for row in matching["per_skill"][:12]:
        parts.append(bar_row(f"{row['skill']}｜需求 {row['demand']} 供给 {row['supply']}", row["supply"]))
    parts.append("</section>")

    parts.append("<section><h2>⑤ Skill Gap</h2>")
    parts.append(table(["技能", "需求", "供给", "缺口", "判定", "置信度", "证据等级"],
                       [[r["skill"], r["demand"], r["supply"], r["gap"], r["status"], r["confidence"],
                         r["evidence_level"]] for r in gaps["rows"][:15]]))
    cross = gaps.get("reported_gap_crosscheck") or {}
    if cross.get("rows"):
        parts.append("<h3>与归档旧结论交叉核对</h3>")
        parts.append(table(["归档记录缺口", "映射技能", "模型计算缺口", "是否一致"],
                           [[r["archive_reported"], r["mapped_skill"], r["computed_gap"],
                             r["agreement"]] for r in cross["rows"]]))
    parts.append("</section>")

    parts.append("<section><h2>⑥ TSI 2.0</h2>")
    parts.append(table(["维度", "得分", "覆盖率", "可用指标", "缺失指标"],
                       [[v["name"], v["score"], f"{v['coverage'] * 100:.0f}%",
                         f"{v['n_available']}/{v['n_total']}", ", ".join(v["missing_indicators"]) or "无"]
                        for v in tsi["dimensions"].values()]))
    if data.get("legacy_comparison"):
        lc = data["legacy_comparison"]
        parts.append("<h3>旧版 Coze 逻辑对比</h3>")
        parts.append(f"<p class='bad'>旧版公式复算 <b>{esc(lc['tsi_v1_replayed'])}</b>，"
                     f"旧报告写出的分数 <b>{esc(lc['tsi_v1_stated_by_legacy_llm'])}</b>；"
                     f"旧版把 {esc(lc['missing_as_zero']['n_zero'])}/{esc(lc['missing_as_zero']['n_indicators'])} "
                     f"个“信息不足”指标记为 0 分。</p>")
    parts.append("</section>")

    sim = data.get("simulation")
    if sim:
        c = sim["combined_scenario"]
        parts.append("<section><h2>⑦ 培养方案模拟</h2>")
        parts.append(f"<p class='ok'>组合方案：匹配度 {esc(c['matching_before']['matching_score_100'])} → "
                     f"{esc(c['matching_after']['matching_score_100'])}；TSI {esc(c.get('tsi_before'))} → "
                     f"{esc(c.get('tsi_after'))}（Δ {esc(c.get('tsi_delta'))}）</p>")
        parts.append(table(["技能", "改动前缺口", "改动后缺口", "变化", "方向"],
                           [[g["skill"], g["gap_before"], g["gap_after"], g["change"], g["direction"]]
                            for g in c["gaps_changed"]]))
        parts.append(f"<p class='warn'>{esc(sim['disclaimer'])}</p>")
        parts.append("</section>")

    parts.append("<section><h2>⑧ Evidence Chain</h2>")
    parts.append(table(["证据ID", "等级", "类型", "标题", "定位"],
                       [[e["evidence_id"], e["evidence_level"], e["source_type"], e["title"],
                         e["locator"]] for e in data["evidence"]]))
    parts.append("</section>")
    parts.append("</main></body></html>")
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export offline EduMatch demo HTML")
    ap.add_argument("--out", default=str(ROOT / "demo" / "output" / "index.html"))
    ap.add_argument("--query", default="分析北京市重点高校人工智能专业与 2025 年 AI 招聘市场的人才供需适配情况，并找出最关键的技能缺口。")
    ap.add_argument("--simulate", action="store_true", default=True)
    ap.add_argument("--no-template", dest="template", action="store_false")
    ap.set_defaults(template=True)
    args = ap.parse_args(argv)

    agent = TalentSupplyDemandAgent()
    result = agent.research(args.query, include_template=args.template, simulate=args.simulate)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(result.data), encoding="utf-8")
    print(f"[ok] wrote {out} ({out.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
