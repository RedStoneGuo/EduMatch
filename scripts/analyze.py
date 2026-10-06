"""一条命令跑完整条流程：自动补采 → 引擎分析 → 分层报告(MD+HTML) → 质量门。

这是系统的**唯一推荐入口**，新对话窗口只需要跑这一条：

    python scripts\\analyze.py --query "分析北京工业大学信息管理与信息系统专业与数据分析师岗位的匹配度"

常用参数：
    --occupation 数据分析师        明确目标岗位（缺省时由引擎按语料推断）
    --scope all|macro|meso|micro   交付层级（默认 all = 三视角）
    --micro-file 个人画像.txt      个人画像（微观尺度用）
    --out-dir 分析产物/<名字>       交付目录（默认自动按 院校_专业_岗位 命名）
    --auto-harvest / --no-auto-harvest   是否先按插件流程自动补采（默认：点名院校时开启）
    --domain-candidate "校名=URL"   你联网检索到的官网 URL（可多次，系统核验后入库）
    --offline                     不联网（自动补采跳过，只出计划与缺口）

产出（全部新增，不覆盖已有文件）：
    报告_macro.html / 报告_meso.html / 报告_micro.html / 报告_all.html
    报告_*.md（同一份结果的 Markdown 版本）
    result.json、自动补采台账（若启用）、质量门报告
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
PROJECT = CORE.parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from agent.core import TalentSupplyDemandAgent  # noqa: E402
from agent.report import render_markdown  # noqa: E402
from reporting.render import render_result  # noqa: E402

JOB_HINTS = ("岗位", "工程师", "分析师", "经理", "专员", "顾问", "研究员", "讲师",
             "教师", "开发", "运维", "产品", "算法", "咨询", "专家")

ASK_TEMPLATE = """\
需要先和用户把下面几项确认清楚（**不要替用户默认专业/岗位就开跑**）：

1. 尺度与对象：宏观（区域/政府）· 中观（院校+专业/教师）· 微观（个人/学生）？
2. 院校 + 专业：要分析哪所学校的哪个专业？（不确定时先说"我来做岗位/专业探索"）
3. 目标岗位：没有目标岗位时，先给 3–5 个候选（含要求与薪酬区间）再让用户选。
4. 微观补充：学生的课程/成绩/项目/实习（自然语言即可，可分批给）。
5. 交付层级：第一版只要一个层级，还是直接出三视角？

确认后再执行（系统会自动补采 → 分析 → 分层报告 MD+HTML → 质量门）：
  .\\analyze.ps1 "<确认后的问题>" -Occupation "<岗位>" -Scope all [-MicroFile "<个人画像.txt>"]
"""


def _target_is_explicit(query: str, plan: dict, occupation: str | None) -> tuple[bool, str]:
    """目标是否足够明确（专业出现在提问里 + 有目标岗位）。"""
    major = str(plan.get("major") or "")
    if not major or plan.get("mode") == "X_unknown_major":
        return False, "没识别到明确的专业"
    if major not in (query or ""):
        return False, f"专业「{major}」是系统默认值，不是用户说的"
    if occupation:
        return True, ""
    if any(hint in (query or "") for hint in JOB_HINTS):
        return True, ""
    return False, "没有目标岗位（不能默认跑整个岗位大类）"


def _slug(text: str, limit: int = 40) -> str:
    value = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(text or "").strip())
    return value[:limit] or "分析产物"


def _default_out_dir(plan: dict, occupation: str | None) -> Path:
    parts = [plan.get("school") or "区域", plan.get("major") or "专业"]
    if occupation:
        parts.append(occupation)
    # 默认落在**当前工作目录**下，不假设 core 外还有什么目录结构——
    # 整包拷到别的电脑/别的路径也能直接跑；可用 EDUMATCH_OUT_DIR 或 --out-dir 覆盖。
    base = Path(os.environ.get("EDUMATCH_OUT_DIR") or (Path.cwd() / "分析产物"))
    return base / _slug("_".join(parts))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EduMatch 一条命令跑完分析")
    ap.add_argument("--query", required=True)
    ap.add_argument("--occupation", default=None)
    ap.add_argument("--scope", default="all", choices=["all", "macro", "meso", "micro"])
    ap.add_argument("--micro-file", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--prefix", default="报告")
    ap.add_argument("--auto-harvest", dest="auto_harvest", action="store_true",
                    help="强制联网补采（默认开启）")
    ap.add_argument("--no-auto-harvest", dest="auto_harvest", action="store_false",
                    help="关闭联网补采（仅离线复现时使用；报告会标注未联网）")
    ap.add_argument("--peer-max", type=int, default=2, help="自动补采的同类院校数量上限")
    ap.add_argument("--harvest-mode", default="target", choices=["target", "region"],
                    help="target=本校+同类院校；region=区域高校按批推进（多次调用累积到全区域）")
    ap.add_argument("--harvest-region", default="北京市")
    ap.add_argument("--harvest-batch", type=int, default=None, help="region 模式每轮采几所（默认 3）")
    ap.add_argument("--domain-candidate", action="append", default=[],
                    metavar="校名=URL")
    ap.add_argument("--source-mode", default=None, choices=["local", "plugin", "hybrid"])
    ap.add_argument("--offline", action="store_true", help="不联网（自动补采只出计划）")
    ap.add_argument("--force", action="store_true",
                    help="目标不明确也直接跑（**不推荐**；正常应先与用户确认）")
    ap.add_argument("--ask", action="store_true", help="只打印问询清单，不执行")
    ap.add_argument("--json", default=None, help="结果 JSON 路径（默认写进交付目录）")
    ap.set_defaults(auto_harvest=None)
    args = ap.parse_args(argv)

    agent = TalentSupplyDemandAgent()
    plan = agent.plan(args.query)
    if args.ask:
        print(ASK_TEMPLATE)
        return 0
    explicit, why = _target_is_explicit(args.query, plan, args.occupation)
    if not explicit and not args.force:
        # 首轮不擅自默认专业/岗位：先把问询清单交给 Agent
        print(f"[需要先问询] {why}。")
        print(ASK_TEMPLATE)
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir(plan, args.occupation)
    out_dir.mkdir(parents=True, exist_ok=True)

    harvest_payload: dict | None = None
    # 联网检索是默认动作：新 Agent 每次运行都必须走"本地 → 插件联网"这条链路，
    # 只有显式 --no-auto-harvest / --offline 才跳过，并在报告里如实标注。
    auto_on = args.auto_harvest if args.auto_harvest is not None else True
    source_mode = args.source_mode
    if auto_on and plan.get("school"):
        from edumatch.auto_harvest import auto_harvest, render_auto_harvest_markdown

        candidates: dict[str, list[str]] = {}
        for item in args.domain_candidate:
            if "=" in item:
                name, url = item.split("=", 1)
                candidates.setdefault(name.strip(), []).append(url.strip())
        print(f"[1/5] 自动补采（插件流程）：{plan.get('school')} + 同类院校 × 全部材料类型 …")
        harvest_payload = auto_harvest(
            agent.settings, school=plan.get("school"), major=plan.get("major"),
            peer_max=args.peer_max, allow_network=not args.offline,
            domain_candidates=candidates,
            mode=args.harvest_mode, region=args.harvest_region,
            batch_size=args.harvest_batch,
        )
        print("\n".join(render_auto_harvest_markdown(harvest_payload)))
        if harvest_payload.get("n_ok"):
            source_mode = source_mode or "hybrid"
        progress = harvest_payload.get("region_progress") or {}
        if progress.get("remaining"):
            print(f"[auto-harvest] 区域池还剩 {progress['remaining']} 所未采；"
                  "**再跑一次同一命令即可继续采下一批**，采到目标覆盖率后再出结论。")
    else:
        print("[1/5] 跳过自动补采（未点名院校 / 已关闭 / 离线）。")

    print("[2/5] 引擎分析（数值只由 analysis/ 确定性函数产出）…")
    micro_profile = None
    if args.micro_file:
        micro_profile = Path(args.micro_file).read_text(encoding="utf-8")
    result = agent.research(
        args.query, target_occupation=args.occupation, source_mode=source_mode,
        micro_profile=micro_profile, report_scope=args.scope, explain=False,
    )
    data = result.data
    if harvest_payload:
        data["auto_harvest"] = harvest_payload

    print("[3/5] 写结构化结果 …")
    json_path = Path(args.json) if args.json else (out_dir / "result.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")

    print("[4/5] 出报告（Markdown + 既有版式 HTML，分层只新增不覆盖）…")
    scopes = ["macro", "meso", "micro", "all"] if args.scope == "all" else [args.scope]
    written: list[Path] = []
    for scope in scopes:
        html = render_result(data, scope)
        html_path = out_dir / f"{args.prefix}_{scope}.html"
        html_path.write_text(html, encoding="utf-8")
        md_path = out_dir / f"{args.prefix}_{scope}.md"
        md_path.write_text(render_markdown(data, scope=scope), encoding="utf-8")
        written += [html_path, md_path]

    print("[5/5] 质量门 …")
    from scripts.validate_edumatch import run as validate_run  # noqa: PLC0415

    report = validate_run()
    gate = "PASS（0 error）" if report.n_errors == 0 else f"FAIL（{report.n_errors} error）"
    print(f"       validate_edumatch：{gate}（{len(report.items)} 项检查）")

    print("\n交付目录：", out_dir)
    for path in written:
        print(f"  - {path.name}  ({path.stat().st_size/1024:.0f} KB)")
    print(f"  - {json_path.name}")
    if harvest_payload:
        print("  - 自动补采台账见 result.json 的 auto_harvest 字段（报告「来源与复现」已渲染）")
    first = (out_dir / f"{args.prefix}_all.html") if args.scope == "all" else \
        (out_dir / f"{args.prefix}_{args.scope}.html")
    print(f"\n下一步：打开 {first.name} 阅读；补做其它层级直接再跑一次同一命令（不会覆盖已有文件）。")
    return 0 if report.n_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
