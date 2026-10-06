"""CLI entry point: run one research task end to end.

    python -m agent.runner --query "分析北京工业大学人工智能专业..."
    python -m agent.runner --query "..." --simulate --template --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:  # allow running as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.core import TalentSupplyDemandAgent  # noqa: E402

DEFAULT_QUERY = (
    "分析北京市重点高校人工智能专业与 2025 年 AI 招聘市场的人才供需适配情况，"
    "并找出最关键的技能缺口。"
)

#: 本次运行自动补采的台账（交给分析结果，供报告引用）
_AUTO_HARVEST_PAYLOAD: list[dict] = []


def _parse_domain_candidates(items: list[str]) -> dict[str, list[str]]:
    """把 ``--domain-candidate 校名=URL`` 解析成 {校名: [URL, …]}。"""
    out: dict[str, list[str]] = {}
    for item in items or []:
        if "=" not in item:
            continue
        name, url = item.split("=", 1)
        out.setdefault(name.strip(), []).append(url.strip())
    return out


def _recommend_harvest(data: dict, args) -> None:
    """本地数据不足且没联网采过时，明确提示"下一步要用插件联网"。

    规则：source_mode 是 local（或未指定）且没用 --harvest，并且出现下列任一情况：
      · 目标校供给缺失（supply.target 为空 / course_scope 记 insufficient_evidence）
      · 培养目标是 need_online（本地/归档/采集都没有可核查原文）
      · 需求向量为空
    就打印可复制的插件采集命令（域名必须已核实）。
    """
    if getattr(args, "harvest", False):
        return
    mode = (getattr(args, "source_mode", None) or "local")
    if mode != "local":
        return
    plan = data.get("plan") or {}
    supply = data.get("supply") or {}
    teaching = data.get("teaching") or {}
    reasons: list[str] = []
    if plan.get("school") and not supply.get("target"):
        reasons.append("目标校课程供给缺失")
    if teaching.get("objective_source_state") == "need_online":
        reasons.append("本专业培养目标只在联网侧，本地/归档/采集都未命中")
    if not (data.get("demand_vector") or {}).get("n_skills"):
        reasons.append("需求向量为空（岗位语料不覆盖该专业）")
    if not reasons:
        return
    school = plan.get("school") or "<院校>"
    print("\n[提示] 本地数据不足：" + "；".join(reasons))
    print("       按项目规范，出报告前应先用**自带插件**联网补采（不要用 urllib/curl/浏览器手抓）：")
    print(f'       python scripts\\resolve_school_domains.py --list peers --school "{school}"')
    print(f'       python -m agent.runner --query "<同一问题>" --occupation "<目标岗位>" '
          f'--source-mode hybrid --harvest --json result.json')
    print("       采完再渲染 HTML；仍然取不到就如实写「未获取」，并给出联网补采计划。")


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    ap = argparse.ArgumentParser(description="EduMatch research agent")
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--simulate", action="store_true", help="运行培养方案模拟")
    ap.add_argument("--template", action="store_true", help="把模板课程纳入供给计算（标注 E 级证据）")
    ap.add_argument("--occupation", default=None,
                    help="目标岗位（如“大模型算法工程师”）；给出后输出该岗位匹配度")
    ap.add_argument("--list-occupations", action="store_true", help="列出可用的目标岗位族")
    ap.add_argument("--json", help="把完整结果写入该 JSON 文件")
    ap.add_argument("--save-run", action="store_true", help="把运行记录写入 SQLite")
    ap.add_argument("--explain", action="store_true", help="启用解释层（默认开启，--no-explain 关闭）")
    ap.add_argument("--no-explain", dest="explain", action="store_false")
    ap.add_argument("--source-mode", default=None, choices=["local", "plugin", "hybrid"],
                    help="教育供给端数据来源：local=本地库(默认)；plugin=只用插件联网收割；"
                         "hybrid=本地+插件合并")
    ap.add_argument("--harvest", action="store_true",
                    help="按 --source-mode 联网跑 edu-material-harvest 收割目标院校材料")
    ap.add_argument("--domain", default=None,
                    help="目标院校官方 *.edu.cn 域名（插件绝不猜域名；缺省读 data/harvest/domains.json）")
    ap.add_argument("--harvest-kinds", default=None,
                    help="收割材料类型，逗号分隔（培养方案,专业介绍,课程大纲,年度报告）")
    ap.add_argument("--harvest-page", action="append", default=[],
                    help="承载页直采 URL（可重复）。大站/子域被挡时用：先联网搜到挂着材料的页面，"
                         "再交给插件枚举下载")
    ap.add_argument("--harvest-kind", default="auto",
                    help="配合 --harvest-page 指定这些页面的材料类型（默认 auto 自判）")
    ap.add_argument("--harvest-timeout", type=int, default=None, help="收割超时秒数")
    ap.add_argument("--peers", default=None,
                    help="同类院校：auto=按全国名单自动判定；none=不用同类基准；"
                         "或逗号分隔的校名列表（显式指定）")
    ap.add_argument("--peer-max", type=int, default=3, help="自动判定的同类院校数量上限（默认 3）")
    ap.add_argument("--peer-kinds", default=None,
                    help="同类院校采集的材料类型（默认只采培养方案）")
    ap.add_argument("--micro-text", default=None,
                    help="个人画像自然语言描述（微观尺度）；例：\"我学过 Python、机器学习…\"")
    ap.add_argument("--micro-file", default=None,
                    help="从 UTF-8 文本文件读入个人画像（与 --micro-text 二选一）")
    ap.add_argument("--scope", default=None, choices=["macro", "meso", "micro", "all"],
                    help="只输出该层级的报告/HTML（默认按 query 推断；可用交互确认）")
    ap.add_argument("--html", default=None,
                    help="把所选层级的报告写成自包含 HTML 文件")
    ap.add_argument("--interactive", dest="interactive", action="store_true",
                    help="强制开启问询（选层级 + 是否要三视角完整版）")
    ap.add_argument("--no-interactive", dest="interactive", action="store_false",
                    help="关闭问询，直接用 --scope 或推断结果")
    ap.set_defaults(interactive=None)
    ap.add_argument("--auto-harvest", dest="auto_harvest", action="store_true",
                    help="先按插件流程自动补采（点名院校 + 同类院校 × 全部材料类型），再分析")
    ap.add_argument("--no-auto-harvest", dest="auto_harvest", action="store_false",
                    help="关闭自动补采（批处理默认关闭；交互默认开启）")
    ap.add_argument("--auto-harvest-peer-max", type=int, default=2,
                    help="自动补采时最多再采几所同类院校（默认 2）")
    ap.add_argument("--auto-harvest-kinds", default=None,
                    help="自动补采的材料类型（逗号分隔；缺省=插件支持的全部类型）")
    ap.add_argument("--auto-harvest-timeout", type=int, default=None,
                    help="单校采集超时秒数")
    ap.add_argument("--domain-candidate", action="append", default=[],
                    metavar="校名=URL",
                    help="你自己联网检索到的候选官网 URL；系统核验（教育域+200+校名）后写入台账并采集")
    ap.add_argument("--auto-harvest-mode", default="target", choices=["target", "region"],
                    help="target=本校+同类院校；region=区域高校按批推进（**多调几次即可把区域采全**）")
    ap.add_argument("--auto-harvest-region", default="北京市")
    ap.add_argument("--auto-harvest-batch", type=int, default=None,
                    help="region 模式每轮采几所（默认 3）")
    ap.set_defaults(auto_harvest=None)
    ap.set_defaults(explain=True)
    args = ap.parse_args(argv)

    if args.list_occupations:
        from edumatch.occupation import catalogue

        for item in catalogue():
            print(f"- {item['name']}（{item['id']}）：{item['note']}")
        return 0

    agent = TalentSupplyDemandAgent()
    micro_profile = args.micro_text
    if not micro_profile and args.micro_file:
        from pathlib import Path as _Path

        micro_profile = _Path(args.micro_file).read_text(encoding="utf-8")

    from agent import scope as scope_mod

    spec = scope_mod.resolve_scope(
        args.query, explicit=args.scope, has_personal_input=bool(micro_profile))
    interactive = args.interactive if args.interactive is not None else sys.stdin.isatty()
    # 自动补采（联网检索）是**默认动作**：本地优先，再走插件入口 A/B 采更多数据。
    # 只有显式 --no-auto-harvest 才关闭；关掉时报告会标注"本轮未联网"。
    auto_on = (args.auto_harvest if args.auto_harvest is not None else True)
    if auto_on:
        from edumatch.auto_harvest import auto_harvest, render_auto_harvest_markdown

        plan_preview = agent.plan(args.query)
        school_preview = plan_preview.get("school")
        kinds = ([k.strip() for k in args.auto_harvest_kinds.split(",") if k.strip()]
                 if args.auto_harvest_kinds else None)
        # 未点名院校时改走区域口径，而不是直接跳过——联网补采是必要项。
        mode = args.auto_harvest_mode if school_preview else "region"
        print(f"[auto-harvest] 按插件流程补采（{'目标口径：' + school_preview if school_preview else '区域口径'}）"
              " × 全部材料类型；顺序=先本地 data/source → 入口 A → 入口 B …")
        payload = auto_harvest(
            agent.settings, school=school_preview, major=plan_preview.get("major"),
            peer_max=args.auto_harvest_peer_max, kinds=kinds,
            timeout_s=args.auto_harvest_timeout,
            domain_candidates=_parse_domain_candidates(args.domain_candidate),
            mode=mode, region=args.auto_harvest_region,
            batch_size=args.auto_harvest_batch,
        )
        print("\n".join(render_auto_harvest_markdown(payload)))
        _AUTO_HARVEST_PAYLOAD.append(payload)
        if payload.get("n_ok"):
            args.source_mode = args.source_mode or "hybrid"
            print(f"[auto-harvest] 已入库 {payload.get('n_materials')} 份材料，"
                  "改用 --source-mode hybrid 分析。")
    # 交互模式下按推断/选择走单层级；批处理（--no-interactive 且未指定 --scope）
    # 保持原有行为输出完整三视角，避免静默改变既有流水线。
    chosen = spec.scale if (interactive or args.scope) else "all"
    if interactive and not args.scope:
        print(scope_mod.question_text(spec))
        try:
            chosen = scope_mod.parse_choice(input("> ")) or spec.scale
        except EOFError:
            chosen = spec.scale
        print(f"[scope] 使用：{scope_mod.SCALE_LABEL[chosen]}（{spec.reason}）")
    result = agent.research(
        args.query, include_template=args.template, simulate=args.simulate,
        persist=args.save_run, explain=args.explain, target_occupation=args.occupation,
        source_mode=args.source_mode, harvest=args.harvest, harvest_domain=args.domain,
        harvest_kinds=([k.strip() for k in args.harvest_kinds.split(",") if k.strip()]
                       if args.harvest_kinds else None),
        harvest_pages=([{"url": u, "kind": args.harvest_kind} for u in args.harvest_page]
                       if args.harvest_page else None),
        harvest_timeout_s=args.harvest_timeout,
        peers=(args.peers if args.peers in (None, "auto", "none")
               else [p.strip() for p in args.peers.split(",") if p.strip()]),
        peer_max=args.peer_max,
        peer_harvest_kinds=([k.strip() for k in args.peer_kinds.split(",") if k.strip()]
                            if args.peer_kinds else None),
        micro_profile=micro_profile,
        report_scope=chosen,
    )
    if _AUTO_HARVEST_PAYLOAD:
        result.data["auto_harvest"] = _AUTO_HARVEST_PAYLOAD[-1]
    print(result.report)
    if args.html:
        from agent.html_report import render_result_html

        out = Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_result_html(result.data, chosen), encoding="utf-8")
        print(f"\n[ok] wrote {out}（只含 {chosen} 层级）")
    if result.explanation:
        print("\n---\n## 解释层\n")
        print(result.explanation.get("explanation", ""))
    if args.json:
        Path(args.json).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[ok] wrote {args.json}")
    # 第一版产出后：按需追问是否要完整三视角（保留问询过程）
    _recommend_harvest(result.data, args)
    if interactive and chosen != "all":
        print("\n" + scope_mod.followup_text())
        try:
            wants_full = scope_mod.parse_yes(input("> "))
        except EOFError:
            wants_full = False
        if wants_full:
            from agent.html_report import render_result_html
            from agent.report import render_markdown

            full_report = render_markdown(result.data, scope="all")
            print("\n" + full_report)
            if args.html:
                full_path = Path(args.html).with_name(Path(args.html).stem + "_full.html")
                full_path.write_text(render_result_html(result.data, "all"), encoding="utf-8")
                print(f"[ok] wrote {full_path}（三视角完整版）")
        else:
            print("[ok] 保持单层级输出；如需三视角，可加 --scope all 重新生成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
