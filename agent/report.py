"""Render an engine result into the three-layer, findings-first report.

Layout (all 18 numbered sections are preserved so downstream tooling and the
evaluation contract keep working):

* **Executive View** - §1 核心发现、§2 Primary TSI 总览（面向用户/评委）
* **Research View**  - §3–§14 画像、Skill Fit/Gap、矩阵、三角比较、趋势、机制、模拟
* **Audit View**     - §15–§18 数据质量、版本、证据链、run_id 与指标依赖图

The main report exposes exactly one formal score (Primary TSI). TSI v1 / 2.0
appear only in §16 as named historical / research-comparison versions.
"""

from __future__ import annotations

from typing import Any

CAUSAL_FORBIDDEN = ("导致", "证明了", "必然导致", "决定了就业", "必然")


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _status_cn(status: str) -> str:
    return {
        "gap": "缺口",
        "oversupply": "供给相对富余",
        "balanced": "基本平衡",
        "insufficient_evidence": "证据不足",
        "covered": "已覆盖",
        "absent_in_scope": "口径内未见供给",
        "target_gap": "目标校供给低于需求",
        "below_peer": "低于同类基准",
        "above_peer": "高于同类基准",
        "consistent": "基本一致",
        "ok": "可用",
        "partial": "部分证据",
    }.get(status, status)


def _basis_summary(basis: Any) -> str:
    """One-line scoring basis: raw → benchmark → formula → score."""
    if isinstance(basis, str):
        return basis
    if not isinstance(basis, dict):
        return ""
    kind = basis.get("type")
    if kind == "continuous":
        return (f"原始 {_num(basis.get('raw'))} / 基准 {_num(basis.get('benchmark'))} → "
                f"{basis.get('formula')} = {_num(basis.get('score'))}")
    if kind == "ordinal":
        return f"分级「{basis.get('level') or '—'}」→ 查表 = {_num(basis.get('score'))}"
    if kind == "semantic_vector":
        return (f"向量余弦 {_num(basis.get('cosine'), 4)}（{basis.get('provider')}）→ 校准 "
                f"{_num(basis.get('similarity'), 4)} → ×100 = {_num(basis.get('score'))}")
    if kind == "semantic_anchor":
        quote = (basis.get("quote") or "").replace("|", "／")[:60]
        return (f"语义锚点「{basis.get('level')}」余弦 {_num(basis.get('cosine'), 4)} → "
                f"{_num(basis.get('score'))}" + (f"；命中原文：{quote}" if quote else ""))
    if kind == "keyword_rule":
        return f"关键词规则「{basis.get('level') or '—'}」→ 查表 = {_num(basis.get('score'))}"
    if kind == "threshold":
        return (f"原始 {_num(basis.get('raw'))} / 锚点 {basis.get('anchor')} → "
                f"{basis.get('formula')} = {_num(basis.get('score'))}")
    if kind == "direct":
        return f"直接采用 {basis.get('source')} = {_num(basis.get('score'))}"
    if kind == "composite":
        return f"{basis.get('formula')} = {_num(basis.get('score'))}"
    return ""


def _render_unavailable(result: dict[str, Any]) -> str:
    """Report for a major with no data: refuse to answer, explain what is needed."""
    coverage = result.get("major_coverage") or {}
    lines = [
        "# EduMatch 研究结果：无法给出结论（数据不足）",
        "",
        f"**研究问题**：{result.get('query', '')}",
        "",
        f"**结论**：{result.get('message', '缺少数据')}",
        "",
        f"**原因**：{result.get('reason', '')}",
        "",
        "## 现有可分析的专业族",
        "",
        "| 专业族 | 说明 |",
        "| --- | --- |",
    ]
    for family in coverage.get("known_families") or []:
        lines.append(f"| `{family}` | 归档中有该族的结构化教育事实 |")
    lines += ["", "## 如何补充该专业的数据", ""]
    for step in result.get("how_to_enable") or []:
        lines.append(f"- {step}")
    lines += [
        "",
        "## 说明",
        "",
        "- 本系统不会用其他专业的数据冒充该专业结论；宁可返回「数据不足」，也不输出无法追溯的分数。",
        "- 校级口径的就业率/满意度只能代表全校基线，不能替代专业口径指标。",
    ]
    return "\n".join(lines)


def _top_gaps(gaps: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return [r for r in (gaps.get("rows") or []) if r.get("status") == "gap"][:limit]


def _occupation_line(occ: dict[str, Any], match: dict[str, Any]) -> str:
    name = (occ.get("occupation") or {}).get("name") or "—"
    if match.get("match_100") is None:
        return f"目标岗位「{name}」：{occ.get('reason') or '证据不足'}，不输出匹配度"
    return (f"目标岗位「{name}」（{occ.get('n_jobs')} 条岗位，匹配口径 "
            f"{occ.get('match_scope')}）匹配度 **{_num(match.get('match_100'))}/100"
            f"（{match.get('band')}）**：{match.get('n_skills_compared')} 项需求技能覆盖 "
            f"{match.get('n_skills_covered')} 项")


def _primary_label(primary: dict[str, Any]) -> str:
    if primary.get("primary_tsi") is None:
        reason = (primary.get("not_computable_short")
                  or primary.get("not_computable_reason") or "证据不足")
        return f"无法计算（{reason.rstrip('。')}）"
    return f"{_num(primary.get('primary_tsi'))}（{primary.get('band') or '—'}）"


def _findings_lines(result: dict[str, Any]) -> list[str]:
    """Six findings, each traceable to one research object."""
    plan = result["plan"]
    primary = result.get("primary_tsi") or {}
    fit_block = result.get("skill_fit") or {}
    target_fit = fit_block.get("target") or {}
    peer_fit = fit_block.get("peer") or {}
    primary_fit = fit_block.get("primary") or {}
    gaps = result.get("skill_gaps") or {}
    demand = result.get("demand_vector") or {}
    supply = result.get("supply") or {}
    bench = result.get("benchmark") or {}
    sim = result.get("simulation") or {}
    mechanism = result.get("mechanism") or {}
    quality = result.get("data_quality") or {}
    occ = result.get("occupation") or {}
    job_match = result.get("occupation_match") or {}
    lines: list[str] = ["## 1. 核心发现（Executive View）", ""]
    top_demand = (demand.get("top_skills") or [])[:5]
    if occ.get("demand_status") == "ok":
        occ_top = occ.get("demand_top") or []
        edu = (occ.get("requirements") or {}).get("education_distribution") or {}
        occ_name = (occ.get("occupation") or {}).get("name") or "—"
        lines.append(
            f"**发现 1｜目标岗位需要什么**：目标岗位「{occ_name}」"
            f"（语料 {occ.get('n_jobs')} 条岗位，匹配口径 {occ.get('match_scope')}）。"
            + ("需求强度最高的是 " + "、".join(
                f"{r['skill']}（{_num(r['demand'])}）" for r in occ_top[:5]) + "；"
               if occ_top else "")
            + ("学历结构以 " + "、".join(f"{k} {v} 条" for k, v in list(edu.items())[:2]) + " 为主。"
               if edu else ""))
    elif occ.get("status") == "insufficient_evidence":
        lines.append("**发现 1｜目标岗位需要什么**：" + (
            occ.get("reason") or "目标岗位样本不足，无法给出岗位需求画像"))
    elif top_demand:
        lines.append("**发现 1｜北京市场需要什么**：需求强度最高的是 " + "、".join(
            f"{r['skill']}（{_num(r['demand'])}）" for r in top_demand) + "。")
    else:
        lines.append("**发现 1｜北京市场需要什么**：需求向量不可用——" + (
            (result.get("market") or {}).get("demand_scope_note")
            or "缺少该专业族的岗位语料") )
    target_supply = supply.get("target") or {}
    peer_supply = supply.get("peer") or {}
    if target_supply:
        lines.append(
            f"**发现 2｜目标高校正在培养什么**：{plan.get('school') or '（未点名高校）'} "
            f"可核查课程 {target_supply.get('n_courses')} 门（可靠度 "
            f"{target_supply.get('reliability')}，"
            f"{'部分证据' if target_supply.get('partial') else '完整口径'}）；"
            f"北京同类专业基准课程 {peer_supply.get('n_courses')} 门。目标校与基准口径严格分开。")
    elif plan.get("school"):
        lines.append(
            f"**发现 2｜目标高校正在培养什么**：{plan['school']} 没有可核查的课程证据"
            f"（目标供给 `insufficient_evidence`）；北京同类专业基准课程 "
            f"{peer_supply.get('n_courses') or 0} 门。目标校与基准口径严格分开。")
    else:
        lines.append("**发现 2｜目标高校正在培养什么**：未指定目标高校，仅给出区域基准口径画像。")
    if job_match.get("match_100") is not None:
        bench = occ.get("benchmark_match") or {}
        detail = (f"**发现 3｜该专业与目标岗位的匹配度**："
                  f"{plan.get('school') or '研究对象'}{plan['major']} → "
                  f"「{(occ.get('occupation') or {}).get('name')}」= "
                  f"**{_num(job_match.get('match_100'))}/100（{job_match.get('band')}）**；"
                  f"需求技能 {job_match.get('n_skills_compared')} 项中覆盖 "
                  f"{job_match.get('n_skills_covered')} 项，缺失 "
                  f"{job_match.get('n_skills_missing')} 项。")
        if job_match.get("definitional_missing"):
            detail += ("岗位定义性技能缺失：" + "、".join(job_match["definitional_missing"][:6]) + "。")
        if bench.get("match_100") is not None:
            detail += (f"北京同类专业基准口径 {_num(bench.get('match_100'))}"
                       f"（{bench.get('band')}）——对照，不代表该校。")
        lines.append(detail)
    elif primary_fit.get("fit_100") is not None and target_fit.get("fit_100") is not None:
        delta = round(float(target_fit["fit_100"]) - float(peer_fit.get("fit_100") or 0), 2)
        lines.append(
            f"**发现 3｜二者差在哪里**：目标高校 Skill Fit "
            f"**{_num(target_fit.get('fit_100'))}**，北京同类专业基准 "
            f"{_num(peer_fit.get('fit_100'))}，差值 {delta:+.2f}。")
    elif primary_fit.get("fit_100") is not None:
        lines.append(
            f"**发现 3｜二者差在哪里**：区域口径 Skill Fit = "
            f"**{_num(primary_fit.get('fit_100'))}**（研究对象为北京同类专业课程池）；"
            f"市场需求构成对照，本问题未点名高校故不输出校际差值。")
    else:
        lines.append("**发现 3｜二者差在哪里**：研究对象自身的 Skill Fit 证据不足，"
                     "仅能给出可获得的口径与市场需求对照（不使用基准值替代研究对象）。")
    gaps_top = _top_gaps(gaps, 5)
    occ_missing = (job_match.get("top_missing_skills") or [])[:5]
    if job_match.get("match_100") is not None and occ_missing:
        lines.append(
            "**发现 4｜核心技能缺口（相对目标岗位）**："
            + "、".join(f"{r['skill']}（缺口 {_num(r['gap'])}）" for r in occ_missing)
            + f"；岗位需求技能覆盖 {job_match.get('n_skills_covered')}/"
              f"{job_match.get('n_skills_compared')}。")
    elif gaps_top:
        scope_label = (
            "" if (fit_block.get("used_for_primary") == "target_school")
            else "（区域同类专业基准口径的缺口，不代表该校）"
        )
        lines.append(
            "**发现 4｜核心技能缺口**" + scope_label + "："
            + "、".join(f"{r['skill']}（缺口 {_num(r['gap'])}）" for r in gaps_top)
            + f"；Skill Gap Index {_num(gaps.get('skill_gap_index'))}"
              f"（可比技能 {gaps.get('n_comparable')}/{gaps.get('n_skills')}）。")
    elif not (gaps.get("n_comparable") or 0):
        lines.append("**发现 4｜核心技能缺口**：供给与需求向量不完整，本轮无法识别缺口"
                     f"（可比技能 {gaps.get('n_comparable')}/{gaps.get('n_skills')}）。")
    else:
        lines.append(f"**发现 4｜核心技能缺口**：未识别到显著缺口；Skill Gap Index "
                     f"{_num(gaps.get('skill_gap_index'))}"
                     f"（可比技能 {gaps.get('n_comparable')}/{gaps.get('n_skills')}）。")
    path = mechanism.get("association_path") or {}
    lines.append("**发现 5｜为什么形成这些缺口**：" + (
        path.get("summary", "") + "（关联路径，非因果）" if path.get("status") == "association_path"
        else "可用于路径分析的样本不足，仅输出政策—产业—技能—课程的关联清单。"))
    combined = sim.get("combined_scenario") or {}
    if combined and (combined.get("matching_after") or {}).get("matching_score_100") is not None:
        lines.append(
            f"**发现 6｜调整培养方案后可能改善什么**：组合方案下 Skill Fit "
            f"{_num((combined.get('matching_before') or {}).get('matching_score_100'))} → "
            f"{_num((combined.get('matching_after') or {}).get('matching_score_100'))}，"
            f"Primary TSI {_num(combined.get('tsi_before'))} → {_num(combined.get('tsi_after'))}"
            f"（Δ {_num(combined.get('tsi_delta'))}）。模拟为情景假设，不是就业结果预测。")
    else:
        lines.append("**发现 6｜调整培养方案后可能改善什么**：缺少可用的供需向量或未请求模拟，"
                     "本轮不输出模拟结论。")
    lines.append("")
    if primary.get("primary_tsi") is None:
        reason = (primary.get("not_computable_short")
                  or primary.get("not_computable_reason") or "证据不足").rstrip("。")
        lines.append(
            f"**综合结论**：Primary TSI 无法计算——{reason}。"
            f"数据可信度：{quality.get('reliability') or '—'}。")
    else:
        lines.append(
            f"**综合结论**：Primary TSI = **{_num(primary.get('primary_tsi'))}**"
            f"（{primary.get('band') or '—'}；权重覆盖率 {_pct(primary.get('weighted_coverage'))}）。"
            f"数据可信度：{quality.get('reliability') or '—'}。")
    lines.append("")
    # Finding-driven 五要素：Finding → Evidence → Model → Action → Simulation
    findings = result.get("findings")
    if not findings:
        from .findings import build_findings

        findings = [f.to_dict() for f in build_findings(result)]
        result["findings"] = findings
    if findings:
        lines.append("### 1.1 Finding-driven 结论（Finding → Model → Action → Simulation）")
        lines.append("")
        from .findings import render_findings

        lines.extend(render_findings(findings, limit=3))
    micro = result.get("micro_result")
    if micro:
        lines.append("### 1.2 个人尺度诊断（Micro · 自然语言输入）")
        lines.append("")
        baseline = ("Major Baseline 专业基准推断，**不是真实个人能力判断**"
                    if micro.get("baseline") else "基于个人证据")
        lines.append(f"- 证据分层：**L{micro.get('sparse_level')}**（{baseline}）；"
                     f"供给口径 `{micro.get('supply_provenance')}`。")
        lines.append(f"- 个人岗位适配（子指标）：**{_num(micro.get('fit_100'))}/100**"
                     "（不等于个人 Primary TSI；微观按证据分层诊断）。")
        for layer, label in (("knowledge", "知识缺口"), ("skill", "技能缺口"),
                             ("capability", "能力缺口"), ("practice", "实践缺口")):
            block = (micro.get("gaps") or {}).get(layer) or {}
            if block.get("status") != "ok":
                lines.append(f"- {label}：证据不足（不记为 0）——{block.get('reason') or '缺需求向量'}")
                continue
            top = block.get("top_gaps") or []
            if top:
                lines.append(f"- {label}：" + "、".join(
                    f"{r['item']}（缺口 {_num(r['gap'])}）" for r in top[:5]))
            elif block.get("not_evidenced"):
                lines.append(f"- {label}：以下项未在个人证据中出现（**证据不足，不等于 0**）："
                             + "、".join(str(x) for x in block["not_evidenced"][:6]))
            else:
                lines.append(f"- {label}：未识别到显著缺口")
        actions = micro.get("priority_actions") or []
        if actions:
            lines.append("- **优先行动**：" + "；".join(a["action"] for a in actions[:4]))
        declared = (micro.get("declared") or {}).get("absences") or []
        if declared:
            lines.append("- 自述缺项（不等于 0 分）：" + "、".join(
                str(a.get("item")) for a in declared[:6]))
        lines.append("")
    return lines


def render_markdown(result: dict[str, Any], scope: str = "all") -> str:
    # 用户只关心某一层级时，只渲染该层级（不塞另外两层的内容）。
    if scope in ("macro", "meso", "micro"):
        from .scoped_report import render_scoped

        return render_scoped(result, scope)
    if "tsi_v2" not in result or "primary_tsi" not in result:
        return _render_unavailable(result)
    plan = result["plan"]
    primary = result["primary_tsi"]
    fit_block = result.get("skill_fit") or {}
    target_fit = fit_block.get("target") or {}
    peer_fit = fit_block.get("peer") or {}
    gaps = result.get("skill_gaps") or {}
    supply = result.get("supply") or {}
    demand = result.get("demand_vector") or {}
    market = result.get("market") or {}
    policy = result.get("policy") or {}
    bench = result.get("benchmark") or {}
    quality = result.get("data_quality") or {}
    occ = result.get("occupation") or {}
    job_match = result.get("occupation_match") or {}
    ds = result.get("dataset_summary") or {}
    lines: list[str] = []

    lines.append("# EduMatch｜北京高等教育人才供需适配研究报告")
    lines.append("")
    lines.append(f"**研究问题**：{result['query']}")
    lines.append("")
    lines.append(
        f"**研究对象**：{plan['major']} 专业"
        f"{'（' + plan['school'] + '）' if plan.get('school') else '（北京同类专业口径）'}；"
        f"分析模式 `{plan['mode']}`；运行编号 `{result['run_id']}`")
    occ_head = result.get("occupation") or {}
    job_head = result.get("occupation_match") or {}
    if job_head.get("match_100") is not None:
        lines.append(f"**目标岗位**：{_occupation_line(occ_head, job_head)}")
    elif (plan.get("target_occupation") or None):
        lines.append(f"**目标岗位**：{plan['target_occupation']}——"
                     f"{occ_head.get('reason') or '证据不足'}")
    lines.append(f"**综合指标**：Primary TSI = **{_primary_label(primary)}**")
    lines.append("")

    # ---------------- Executive View ----------------
    lines.extend(_findings_lines(result))

    lines.append("## 2. 供需总览：Primary TSI（唯一正式总分）与岗位匹配子指标")
    lines.append("")
    if job_match.get("match_100") is not None or occ.get("status") == "insufficient_evidence":
        lines.append("### 2.1 目标岗位匹配（子指标，用于解释 Primary TSI 的供需适配维）")
        lines.append("")
        lines.append(
            "> **口径**：Primary TSI 是唯一正式总分；本节岗位匹配度（Match）是它的"
            "**子指标**，二者不并列、不互相换算。Match 高只说明目标岗位的需求技能被覆盖得多，"
            "不单独构成\"整体适配\"结论。"
        )
        lines.append("")
        if job_match.get("match_100") is not None:
            lines.append(
                f"- **目标岗位匹配度 = {_num(job_match.get('match_100'))}/100"
                f"（{job_match.get('band')}）**；"
                f"岗位族「{(occ.get('occupation') or {}).get('name')}」；"
                f"语料匹配 {occ.get('n_jobs')} 条岗位（{occ.get('match_scope')}）。")
            lines.append(
                f"- 覆盖需求技能 {job_match.get('n_skills_covered')}/"
                f"{job_match.get('n_skills_compared')}；缺失 "
                f"{job_match.get('n_skills_missing')} 项；供给口径 `{job_match.get('supply_provenance')}`"
                f"（可靠度 {job_match.get('supply_reliability')}）。")
            req = occ.get("requirements") or {}
            if req.get("education_distribution"):
                lines.append("- 岗位学历结构：" + "、".join(
                    f"{k} {v} 条" for k, v in req["education_distribution"].items())
                    + (f"；薪资中位 {_num(req.get('median_salary'), 0)}"
                       if req.get("median_salary") else f"；{req.get('salary_note') or ''}"))
            if job_match.get("definitional_missing"):
                lines.append("- 岗位定义性技能缺失：" + "、".join(job_match["definitional_missing"]))
            bench = occ.get("benchmark_match") or {}
            if bench.get("match_100") is not None:
                lines.append(
                    f"- 对照口径（**不代表该校**）：北京同类专业课程池与该岗位匹配度 "
                    f"{_num(bench.get('match_100'))}（{bench.get('band')}）。")
            lines.append("")
            lines.append("| 岗位需求技能 | 需求强度 | 本校供给 | 是否覆盖 | 缺口 |")
            lines.append("| --- | --- | --- | --- | --- |")
            for row in (job_match.get("top_required_skills") or [])[:10]:
                lines.append(
                    f"| {row['skill']} | {_num(row['demand'])} | {_num(row['supply'])} | "
                    f"{'是' if row['covered'] else '否'} | {_num(row['gap'])} |")
            lines.append("")
            lines.append(f"- {job_match.get('method_note')}")
        else:
            lines.append("- 目标岗位匹配度：**证据不足**（"
                         + (job_match.get("reason") or occ.get("reason")
                            or "缺少研究对象自身的可核查供给") + "）。")
            cats = occ.get("catalogue") or []
            if cats:
                lines.append("- 可用目标岗位族：" + "、".join(c["name"] for c in cats))
        lines.append("")
        lines.append("### 2.2 综合适配指标（Primary TSI）")
        lines.append("")
    if primary.get("primary_tsi") is None:
        lines.append(f"- **Primary TSI：无法计算**（{primary.get('not_computable_reason') or '证据不足'}）；"
                     f"版本 `{primary.get('version')}`；可用指标 "
                     f"{primary.get('n_available')}/{primary.get('n_total')}。")
    else:
        lines.append(
            f"- **Primary TSI = {_num(primary.get('primary_tsi'))}（{primary.get('band') or '—'}）**；"
            f"版本 `{primary.get('version')}`；可用指标 {primary.get('n_available')}/{primary.get('n_total')}。")
    lines.append(
        f"- 维度权重覆盖率：{_pct(primary.get('weighted_coverage'))}；综合置信度："
        f"{_num(primary.get('confidence'))}。")
    scope_info = primary.get("supply_scope") or {}
    if scope_info.get("provisional"):
        lines.append(f"- ⚠️ **{scope_info.get('provisional_note')}**")
    lines.append("")
    lines.append("| 维度 | 得分 | 权重 | 覆盖率 | 可用指标 | 缺失指标 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for dim, value in (primary.get("dimensions") or {}).items():
        lines.append(
            f"| {value['name']} | {_num(value['score'])} | {value['weight']} | "
            f"{_pct(value['coverage'])} | {value['n_available']}/{value['n_total']} | "
            f"{', '.join(value['missing_indicators']) or '无'} |")
    lines.append("")
    if primary.get("excluded_dimensions"):
        lines.append(f"- 因覆盖率不足被整维剔除：{list(primary['excluded_dimensions'])}"
                     "（缺失不等于 0，剔除后在覆盖率中披露）")
        lines.append("")
    lines.append(
        f"- 一票否决式结论禁止：Primary TSI 只表达当前证据下的适配状态，"
        f"缺失指标 {', '.join(primary.get('missing_indicators') or []) or '无'} 不参与加权。")
    lines.append("")

    # ---------------- Research View ----------------
    lines.append("## 3. 数据范围、方法与可复现")
    lines.append("")
    lines.append(
        f"- 归档文件 {ds.get('n_documents')} 份；结构化教育事实 {ds.get('n_education_facts')} 条；"
        f"覆盖年份 {ds.get('years')}；政策 {policy.get('n_documents')} 份"
        f"（去重 {len(policy.get('duplicates_removed') or [])} 份）。")
    lines.append(
        f"- 研究链路：{' → '.join(s['skill'].split('_', 1)[1] for s in plan['steps'])}。")
    lines.append(
        "- 计算原则：LLM 只做解释；全部数值来自 `analysis/` 的确定型函数；"
        "缺失记 `null` 并披露，不记 0，也不用其他口径顶替。")
    ledger = result.get("retrieval_ledger") or {}
    if ledger.get("summary"):
        summary = ledger["summary"]
        needs = [m for m, needed in (summary.get("needs_online") or {}).items() if needed]
        lines.append(
            f"- 全面检索台账：共检索 {summary.get('n_attempts')} 条来源记录"
            f"（命中有正文 {summary.get('n_hits')} 条），来源覆盖 "
            "本地正文缓存 → 规范一手材料 → 归档 → 采集产物 → 联网插件；"
            + (f"仍缺、需联网补采：{'、'.join(needs)}。" if needs
               else "本地/归档/采集已覆盖，无需联网补采。"))
    lines.append(
        "- 供需分离：就业结果只取自就业质量报告，招聘数据只用于需求侧。")
    lines.append("")

    lines.append("## 4. 需求画像：北京市场需要什么")
    lines.append("")
    if market.get("demand_scope_note"):
        lines.append(f"- 岗位样本：⚠️ **需求口径提示**：{market['demand_scope_note']}")
        corpus = (result.get("demand_scope") or {}).get("corpus") or {}
        if corpus.get("family_match_share"):
            lines.append(
                "- 岗位语料各专业族关键词覆盖率："
                + "、".join(f"{k} {_pct(v)}" for k, v in corpus["family_match_share"].items())
                + f"（语料主轴 {corpus.get('corpus_family')}）。")
    else:
        lines.append(f"- 岗位样本：{market.get('note') or '见数据质量'}。")
    lines.append(
        f"- 需求向量：{demand.get('n_skills')} 个技能；分量权重 "
        + "、".join(f"{k}={v}" for k, v in (demand.get('component_weights') or {}).items())
        + "。")
    lines.append(
        f"- 不可用分量（不进分母）：{', '.join(demand.get('unavailable_components') or []) or '无'}。")
    lines.append("")
    lines.append("| 技能 | 需求强度 | 出现频率 | 岗位覆盖 | 岗位族覆盖 | 薪资溢价 | 置信度 | 证据等级 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in (demand.get("rows") or [])[:10]:
        comp = row.get("components") or {}
        lines.append(
            f"| {row['skill']} | {_num(row['demand'])} | {_num(comp.get('frequency'))} | "
            f"{_num(comp.get('position_coverage'))} | {_num(comp.get('occupation_coverage'))} | "
            f"{_num(comp.get('salary_premium'))} | {_num(row['confidence'])} | "
            f"{row.get('evidence_level')} |")
    lines.append("")
    lines.append(
        f"- 岗位三口径 raw/dedup/effective = {market.get('raw_count')}/"
        f"{market.get('deduplicated_count')}/{market.get('effective_count')}"
        f"（{market.get('counts_status')}）；硕士及以上占比 {_pct(market.get('master_plus_share'))}；"
        f"薪资中位 {_num(market.get('median_salary_target'), 0)} 元 vs 同城基线 "
        f"{_num(market.get('median_salary_baseline'), 0)} 元。")
    lines.append("")

    lines.append("## 5. 供给画像：目标高校在培养什么（Target Supply）")
    lines.append("")
    target_supply = supply.get("target") or {}
    if target_supply:
        lines.append(
            f"- 口径：`{target_supply.get('provenance')}`；状态 `{target_supply.get('status_label')}`；"
            f"可核查课程 {target_supply.get('n_courses')} 门（映射成功 "
            f"{target_supply.get('n_mapped_courses')} 门）；可靠度 {target_supply.get('reliability')}。")
        if target_supply.get("reason"):
            lines.append(f"- 说明：{target_supply['reason']}")
        lines.append("")
        lines.append("| 技能 | 供给强度 | 覆盖课程数 | 必修课 | 选修课 | 实践课 | 供给权重 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for item in target_supply.get("top_skills") or []:
            ch = (target_supply.get("channels") or {}).get(item["skill"], {})
            lines.append(
                f"| {item['skill']} | {_num(item['supply'])} | {ch.get('n_courses', '—')} | "
                f"{ch.get('required_courses', '—')} | {ch.get('elective_courses', '—')} | "
                f"{ch.get('practice_courses', '—')} | {_num(ch.get('weight'))} |")
    else:
        lines.append("- 目标供给：未指定目标高校或该校无课程证据，记 `insufficient_evidence`。")
    lines.append("")
    lines.append(
        f"- 供给通道可用性：{', '.join(target_supply.get('unavailable_channels') or []) or '全部可用'}"
        "（不可用通道不猜测、不参与加权）。")
    lines.append("")

    lines.append("## 6. 区域基准画像：北京同类专业（Peer Benchmark）")
    lines.append("")
    peer_supply = supply.get("peer") or {}
    lines.append(
        f"- 口径：`{peer_supply.get('provenance')}`；状态 `{peer_supply.get('status_label')}`；"
        f"课程 {peer_supply.get('n_courses')} 门（映射成功 {peer_supply.get('n_mapped_courses')} 门，"
        f"其中 E 级模板课程不归属任何高校）。")
    lines.append(
        f"- 基准 Skill Fit = {_num(peer_fit.get('fit_100'))}；Skill Gap Index = "
        f"{_num(((result.get('skill_gaps_peer') or {}).get('skill_gap_index')))}。")
    lines.append(
        "- **目标高校与基准口径互不替代**：目标校证据不足时，本报告不会用基准值充当目标校结论。")
    lines.append("")
    lines.append("| 技能 | 基准供给 | 供给权重 | 覆盖课程数 |")
    lines.append("| --- | --- | --- | --- |")
    for item in (peer_supply.get("top_skills") or [])[:10]:
        ch = (peer_supply.get("channels") or {}).get(item["skill"], {})
        lines.append(f"| {item['skill']} | {_num(item['supply'])} | "
                     f"{_num(ch.get('weight'))} | {ch.get('n_courses', '—')} |")
    lines.append("")

    lines.append("## 7. Skill Fit 与 Skill Gap（核心解释结果）")
    lines.append("")
    lines.append(
        f"- 主口径（{fit_block.get('used_for_legacy_fit')}）Skill Fit = "
        f"**{_num((result.get('matching') or {}).get('matching_score_100'))}/100**；"
        f"Skill Gap Index = **{_num(gaps.get('skill_gap_index'))}**。")
    lines.append(
        f"- 供需适配维使用口径：`{fit_block.get('used_for_primary')}`"
        f"（{((primary.get('supply_scope') or {}).get('scope_note')) or ''}）")
    lines.append(
        f"- 目标高校口径 Fit = {_num(target_fit.get('fit_100'))}"
        f"（{_status_cn(target_fit.get('status') or '')}）；"
        f"北京同类专业基准 Fit = {_num(peer_fit.get('fit_100'))}。")
    lines.append(
        f"- 缺口口径：{gaps.get('method_note') or ''}需求侧缺失仍记 null；"
        f"本轮 {gaps.get('n_supply_absent_in_scope')} 个技能属口径内未见供给。")
    lines.append("")
    lines.append("| 技能 | 需求 | 供给 | 缺口 | 判定 | 供给依据 | 证据等级 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in (gaps.get("rows") or [])[:12]:
        lines.append(
            f"| {row['skill']} | {_num(row['demand'])} | {_num(row['supply'])} | "
            f"{_num(row['gap'])} | {_status_cn(row['status'])} | "
            f"{_status_cn(row.get('supply_basis') or '—')} | {row.get('evidence_level')} |")
    lines.append("")
    cross = gaps.get("reported_gap_crosscheck") or {}
    if cross.get("rows"):
        lines.append("**与归档旧结论的交叉核对**（旧结论为 D 级语义判断）")
        lines.append("")
        lines.append("| 归档记录缺口 | 映射技能 | 模型计算缺口 | 是否一致 |")
        lines.append("| --- | --- | --- | --- |")
        for row in cross["rows"]:
            verdict = {"consistent": "一致", "model_disagrees": "模型不认可"}.get(
                row["agreement"], "无法判定")
            lines.append(f"| {row['archive_reported']} | {row['mapped_skill']} | "
                         f"{_num(row['computed_gap'])} | {verdict} |")
        lines.append("")

    lines.append("## 8. 技能矩阵：供给 × 需求 × 缺口")
    lines.append("")
    lines.append("| 技能 | 目标校供给 | 基准供给 | 市场需求 | 目标缺口 | 判定 | 解读 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    skill_bench = (bench.get("skill_benchmark") or {})
    for row in (skill_bench.get("rows") or [])[:12]:
        lines.append(
            f"| {row['skill']} | {_num(row['target_supply'])} | {_num(row['peer_supply'])} | "
            f"{_num(row['market_demand'])} | {_num(row['target_gap'])} | "
            f"{_status_cn(row['status'])} | {row.get('reading', '')} |")
    lines.append("")
    lines.append(f"- {skill_bench.get('note', '')}")
    lines.append("")

    lines.append("## 9. 供给结构分解（学分 / 必修 / 实践 / 深度 / 培养目标通道）")
    lines.append("")
    lines.append(
        "供给强度不再是「课程是否提到该技能」的 0/1，而是显式的连续通道：")
    lines.append("")
    lines.append("```")
    lines.append("w(c,s) = 学分 × 必修系数 × 深度系数 × 实践系数")
    lines.append("Supply(s) = min( Σ_c w(c,s) / C_ref + β·1[培养目标命中 s], 1 )")
    lines.append("```")
    lines.append("")
    channels = (result.get("supply_channels") or {})
    rows = sorted(channels.items(), key=lambda kv: -(kv[1].get("weight") or 0))[:10]
    lines.append("| 技能 | 覆盖课程 | 学分合计 | 必修 | 选修 | 未知要求 | 实践课 | 实践学时 | 深度级别 | 培养目标命中 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for skill, ch in rows:
        lines.append(
            f"| {skill} | {ch.get('n_courses', 0)} | {_num(ch.get('credits'))} | "
            f"{ch.get('required_courses', 0)} | {ch.get('elective_courses', 0)} | "
            f"{ch.get('unknown_requirement_courses', 0)} | {ch.get('practice_courses', 0)} | "
            f"{_num(ch.get('practice_hours'))} | {', '.join(ch.get('depth_levels') or []) or '—'} | "
            f"{'是' if ch.get('objective_hit') else '否'} |")
    lines.append("")
    lines.append(
        f"- 涉及技能 {len(channels)} 个；来源课程口径 = "
        f"`{((result.get('course_scope') or {}).get('used_for_fit'))}`。")
    lines.append("")

    lines.append("## 10. 三角比较与差异解释（目标校 VS 同类基准 VS 市场）")
    lines.append("")
    tri = bench.get("triangle") or {}
    lines.append(f"- {tri.get('label', '')}：{tri.get('note', '')}")
    lines.append("")
    for finding in tri.get("findings") or []:
        lines.append(f"- {finding}")
    lines.append("")
    lines.append("| 维度 | 目标高校 | 北京同类基准 | 市场需求 |")
    lines.append("| --- | --- | --- | --- |")
    for row in tri.get("rows") or []:
        lines.append(f"| {row['dimension']} | {_num(row.get('target')) if isinstance(row.get('target'), (int, float)) else (row.get('target') or '—')} | "
                     f"{_num(row.get('peer')) if isinstance(row.get('peer'), (int, float)) else (row.get('peer') or '—')} | "
                     f"{_num(row.get('market')) if isinstance(row.get('market'), (int, float)) else (row.get('market') or '—')} |")
    lines.append("")
    lines.append(
        f"- 教育背景横向比较（保留作背景，不作为核心基准）：可排序 "
        f"{bench.get('rankable')}；{bench.get('sample_note', '')}")
    lines.append("")
    if bench.get("entities"):
        lines.append("| 学校 | 毕业去向落实率 | 签约率 | 深造率 | 实践学分占比 | 高级职称比例 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in bench["entities"][:10]:
            lines.append(
                f"| {row['entity']} | {_num(row.get('placement_rate'))} | "
                f"{_num(row.get('signing_rate'))} | {_num(row.get('further_study_rate'))} | "
                f"{_num(row.get('practice_credit_ratio'))} | {_num(row.get('senior_title_ratio'))} |")
        lines.append("")

    lines.append("## 11. 趋势：市场变化 vs 培养响应")
    lines.append("")
    trends = result.get("trends") or {}
    curriculum = trends.get("curriculum_supply") or {}
    if curriculum.get("status") == "ok":
        lines.append(
            f"- 课程覆盖面：{curriculum.get('first_year')}→{curriculum.get('last_year')} "
            f"变化 {_num(curriculum.get('change'))}（{curriculum.get('direction')}，"
            f"{curriculum.get('n_periods')} 期）。")
    else:
        lines.append(f"- 课程覆盖面：证据不足（{curriculum.get('reason') or '无多期数据'}）。")
    for key in ("placement_rate", "signing_rate", "further_study_rate", "practice_credit_ratio"):
        summary = trends.get(key) or {}
        if summary.get("status") == "ok":
            lines.append(
                f"- {key}：{summary.get('first_year')}→{summary.get('last_year')} 变化 "
                f"{_num(summary.get('change'))}（{summary.get('direction')}，n="
                f"{summary.get('n_periods')} 期 / {summary.get('n_observations')} 条观测）。")
        else:
            lines.append(f"- {key}：证据不足（{summary.get('reason') or '数据不足'}）。")
    market_trend = trends.get("market_skill_demand") or {}
    response = trends.get("response") or {}
    lines.append(f"- 市场技能需求趋势：{market_trend.get('reason') or market_trend.get('status')}。")
    lines.append(f"- 培养响应判断：{response.get('conclusion') or response.get('reason')}。")
    lines.append("")

    lines.append("## 12. 机制分析：政策—产业—岗位—技能—课程 关联路径")
    lines.append("")
    mech = result.get("mechanism") or {}
    path = mech.get("association_path") or {}
    lines.append(f"- 路径状态：`{path.get('status')}`；{path.get('summary') or path.get('reason') or ''}")
    lines.append(
        f"- 政策主题（按提及频次）：{'、'.join((policy.get('industry_direction') or [])[:6]) or '证据不足'}；"
        f"匹配政策 {policy.get('n_matched_documents')}/{policy.get('n_documents')} 份。")
    if path.get("n_paths"):
        lines.append("")
        lines.append("| 技能 | 政策提及 | 市场需求 | 课程覆盖 | 缺口 | 路径状态 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in (path.get("paths") or [])[:8]:
            lines.append(
                f"| {row['skill']} | {'是' if row['policy_mentioned'] else '否'} | "
                f"{_num(row['demand'])} | {_num(row['supply'])} | {_num(row['gap'])} | "
                f"{_status_cn(row['curriculum_status'])} |")
        lines.append("")
    lines.append(f"- {path.get('method_note') or ''}")
    assoc = mech.get("association_practice_vs_placement") or {}
    lines.append(
        f"- 统计关联（样本充分时才输出）：实践学分占比 vs 落实率 r="
        f"{_num(assoc.get('r'))}，n={assoc.get('n')}，状态 {assoc.get('status')}。")
    importance = mech.get("importance_on_placement_rate") or {}
    if importance.get("status") == "ok":
        lines.append(f"- 置换重要性（n={importance['n']}，CV R²={importance['cv_r2_mean']}）："
                     + "、".join(f"{k} {v}" for k, v in importance["importance"].items()))
    else:
        lines.append(f"- 机制模型状态：{importance.get('status')}（样本不足时不做重要性结论）。")
    lines.append(f"- 表述护栏：{mech.get('language_guard', '')}")
    lines.append("")

    lines.append("## 13. 培养方案模拟（Skill Gap → 课程 → ΔFit → ΔPrimary TSI）")
    lines.append("")
    sim = result.get("simulation")
    if sim:
        for scenario in sim.get("single_scenarios") or []:
            lines.append(
                f"- 增加《{scenario['scenario']['course_name']}》→ Skill Fit "
                f"{_num((scenario.get('matching_before') or {}).get('matching_score_100'))} → "
                f"{_num((scenario.get('matching_after') or {}).get('matching_score_100'))}，"
                f"Primary TSI {_num(scenario.get('tsi_before'))} → {_num(scenario.get('tsi_after'))}"
                f"（Δ {_num(scenario.get('tsi_delta'))}）。")
        combined = sim.get("combined_scenario") or {}
        lines.append(
            f"- 组合方案 → Skill Fit "
            f"{_num((combined.get('matching_before') or {}).get('matching_score_100'))} → "
            f"{_num((combined.get('matching_after') or {}).get('matching_score_100'))}，"
            f"Primary TSI {_num(combined.get('tsi_before'))} → {_num(combined.get('tsi_after'))}"
            f"（Δ {_num(combined.get('tsi_delta'))}）；"
            f"Skill Gap Index {_num(combined.get('skill_gap_index_before'))} → "
            f"{_num(combined.get('skill_gap_index_after'))}。")
        if combined.get("gaps_changed"):
            lines.append("- 缺口变化：" + "、".join(
                f"{g['skill']} {_num(g['gap_before'])}→{_num(g['gap_after'])}"
                for g in combined["gaps_changed"][:6]))
        lines.append(f"- **{sim.get('disclaimer', '')}**")
        lines.append("- 模拟假设：" + "；".join(sim.get("assumptions") or []))
        lines.append(f"- 基线课程口径：`{sim.get('base_course_source')}` "
                     f"（{sim.get('base_scope')}）。")
    else:
        lines.append("- 本次运行未请求模拟（模式 G / 加 `--simulate` 可触发）。")
    lines.append("")

    lines.append("## 14. 主要供需矛盾与建议")
    lines.append("")
    top = _top_gaps(gaps, 5)
    if top:
        for row in top:
            lines.append(
                f"- **供需矛盾**：{row['skill']}（需求 {_num(row['demand'])} / 供给 "
                f"{_num(row['supply'])} / 缺口 {_num(row['gap'])}）。"
                f"**建议**：评估将《{row['skill']}》相关内容纳入必修或实践环节，"
                "并在下一轮培养方案修订中复核其学分与实验/项目支撑。")
    else:
        lines.append("- 本口径下未识别到显著缺口；建议保持现有结构并持续监测需求变化。")
    if (supply.get("target") or {}).get("partial"):
        lines.append("- **数据建议**：目标高校课程证据偏少，建议补录该校培养方案课程表，"
                     "使 Target Supply 从「保守下界」升级为完整画像。")
    if not any((t or {}).get("status") == "ok" for k, t in (result.get("trends") or {}).items()
               if k == "market_skill_demand"):
        lines.append("- **数据建议**：招聘数据只有一个时间窗口，建议按季度重复导出 HAR，"
                     "才能回答「市场变化是否被培养体系及时响应」。")
    if not (policy.get("industry_direction")):
        lines.append("- **数据建议**：政策文本未匹配到产业方向，建议补充政策文件后重跑机制分析。")
    lines.append("")
    lines.append(
        "- 建议均为模型假设下的方案方向，不是就业结果预测；所有建议对应上方可追溯的缺口与证据。")
    lines.append("")

    # ---------------- Audit View ----------------
    lines.append("## 15. 风险、数据质量与可信度")
    lines.append("")
    lines.append(f"- 综合可信度判断：**{quality.get('reliability') or '—'}**"
                 f"（{quality.get('n_ok')}/{quality.get('n_checks')} 项检查通过）。")
    lines.append("")
    lines.append("| 检查项 | 状态 | 说明 |")
    lines.append("| --- | --- | --- |")
    for check in quality.get("checks") or []:
        lines.append(f"| {check['item']} | {_status_cn(check['status'])} | {check['detail']} |")
    lines.append("")
    lines.append(
        f"- Primary TSI 覆盖率 {_pct(quality.get('primary_tsi_coverage'))}；"
        f"缺失指标：{', '.join(quality.get('primary_tsi_missing') or []) or '无'}；"
        f"TSI 2.0 覆盖率 {_pct(quality.get('v2_coverage'))}。")
    lines.append(
        "- 报告 PDF 已用 pypdf 抽取正文并抽取 A 级事实；无文本层的扫描件标记 "
        "`pdf_no_text_layer`，既不静默跳过、也不猜测填充。")
    lines.append("")

    lines.append("## 16. 方法版本：Primary TSI 与历史版本")
    lines.append("")
    versions = primary.get("versions") or {}
    formal = versions.get("formal") or {}
    lines.append(f"- **正式主指标**：`{formal.get('id')}` v{formal.get('version')} = "
                 f"{_num(formal.get('score'))}；对用户唯一露出。")
    for role in ("historical_version", "research_comparison", "benchmark_version"):
        item = versions.get(role) or {}
        lines.append(f"- {role}：`{item.get('id')}` v{item.get('version')} = "
                     f"{_num(item.get('score'))}；{item.get('note', '')}")
    lines.append("")
    lines.append(
        "- Primary TSI 与 TSI 2.0 的差异来自模型逻辑：2.0 的 B1 与 C4 输入完全相同"
        "（C4 写作 `0.5·m4 + 0.5·m4`，恒等于 m4），同一匹配结果被加权两次；"
        "Primary 移除该重复并按统一 Fit 主线重建供需适配维。")
    lines.append("")
    if result.get("legacy_comparison"):
        lc = result["legacy_comparison"]
        lines.append(
            f"- 旧版 Coze 基线：公式复算 {_num(lc.get('tsi_v1_replayed'))} vs 报告写出 "
            f"{_num(lc.get('tsi_v1_stated_by_legacy_llm'))}；"
            f"旧版把 {lc['missing_as_zero']['n_zero']}/{lc['missing_as_zero']['n_indicators']} "
            "个『信息不足』指标记为 0 分。")
        lines.append("")

    lines.append("## 17. Evidence Chain")
    lines.append("")
    lines.append(f"- 本轮登记证据 {len(result.get('evidence') or [])} 条；每条含 "
                 "`locator/quote/level/confidence`。")
    lines.append("")
    lines.append("| 证据ID | 等级 | 标题 | 定位 |")
    lines.append("| --- | --- | --- | --- |")
    for item in (result.get("evidence") or [])[:14]:
        lines.append(
            f"| {item['evidence_id']} | {item['evidence_level']} | {item['title'][:30]} | "
            f"{str(item['locator'])[:54]} |")
    lines.append("")

    lines.append("## 18. 审计信息：run_id、公式、指标依赖与复现")
    lines.append("")
    retrieval = result.get("retrieval") or {}
    if retrieval:
        src = retrieval.get("data_source") or {}
        if src:
            mode_label = {"local": "本地数据", "plugin": "插件联网数据",
                          "hybrid": "本地 + 插件混合"}.get(src.get("mode"), src.get("mode"))
            lines.append(
                f"- **供给端数据来源**：`{src.get('mode')}`（{mode_label}）——"
                f"本地 {src.get('local_courses', 0)} 门课程 / 收割 {src.get('harvest_courses', 0)} 门课程；"
                f"本地 {src.get('local_facts', 0)} 条事实 / 收割 {src.get('harvest_facts', 0)} 条事实。")
            if src.get("harvest_performed"):
                lines.append(
                    f"  - 插件采集：{src.get('harvest_school')}（{src.get('harvest_domain')}）"
                    f"后端 {src.get('harvest_backend')}、状态 {src.get('harvest_state')}、"
                    f"入库 {src.get('harvest_import', {}).get('installed') and len(src['harvest_import']['installed'])} 份；"
                    f"产物目录 `{src.get('harvest_out_dir')}`")
            elif src.get("harvest_requested") and src.get("error"):
                lines.append(f"  - 插件采集未完成：{src.get('error')}")
            if src.get("peer_candidates"):
                used = list(src.get("peer_harvested") or []) + list(src.get("peer_reused") or [])
                lines.append(
                    f"  - **同类院校基准**（{src.get('peer_selector') or 'auto'} 判定）："
                    f"候选 {len(src['peer_candidates'])} 所，实际进入基准池 {len(used)} 所"
                    + (f"（新采 {len(src.get('peer_harvested') or [])} / 复用 {len(src.get('peer_reused') or [])}）"
                       if used else ""))
                for item in src["peer_candidates"][:6]:
                    mark = "已采" if item.get("school") in used else "未采"
                    lines.append(
                        f"    - {item.get('school')}（{item.get('province') or '—'}，"
                        f"{'、'.join(item.get('tiers') or []) or '普通本科'}，"
                        f"得分 {item.get('score')}，{mark}）：{'；'.join(item.get('reasons') or [])}")
                for item in (src.get("peer_skipped") or [])[:6]:
                    lines.append(f"    - 跳过 {item.get('school')}：{item.get('reason')}")
            for note in (src.get("notes") or []):
                lines.append(f"  - {note}")
            lines.append("")
        lines.append(
            f"- **本轮定点检索**：{retrieval.get('target', {}).get('school')} · "
            f"{retrieval.get('target', {}).get('major')}（{retrieval.get('target', {}).get('family')}口径）")
        supply_r = retrieval.get("supply") or {}
        texts = retrieval.get("curriculum_texts") or {}
        emp = retrieval.get("employment") or {}
        reports = retrieval.get("school_reports") or {}
        lines.append(
            f"  - 培养方案 {supply_r.get('plan_pdfs')} 份 → 课程 {supply_r.get('courses')} 门；"
            f"课程大纲文本 {texts.get('syllabi')} 份、专业介绍/培养方案文本 "
            f"{texts.get('major_intro_or_plan')} 份")
        lines.append(
            f"  - 该专业就业事实 {emp.get('major_facts')} 条（{', '.join(emp.get('fact_types') or []) or '—'}），"
            f"来自 {emp.get('source_reports')} 份报告；校级口径事实 {emp.get('school_level_facts')} 条"
            + (f"（{emp.get('fallback')}）" if emp.get("fallback") else "")
            + f"；校级报告文本 {reports.get('texts')} 份（{', '.join(reports.get('categories') or [])}）")
        lines.append(
            f"  - 政策匹配 {((retrieval.get('policy') or {}).get('matched_documents'))} 份；"
            f"岗位需求技能 {((retrieval.get('market') or {}).get('demand_skills'))} 个"
            f"（目标岗位 {((retrieval.get('market') or {}).get('occupation')) or '未指定'}，"
            f"岗位样本 {((retrieval.get('market') or {}).get('occupation_jobs'))}）；"
            f"文献 {((retrieval.get('literature') or {}).get('n_works'))} 篇")
        lines.append(f"  - {retrieval.get('note')}")
        lines.append("")
    lines.append(
        f"- 运行编号 `{result['run_id']}`；工具调用 {len(result.get('tool_calls') or [])} 次；"
        f"开始 {result.get('started_at')}，结束 {result.get('finished_at')}。")
    lines.append(
        f"- 复现命令：`python -m agent.runner --query \"{result['query']}\" --simulate --template`")
    lines.append("")
    lines.append("| 指标 | 名称 | 维度 | 得分 | 维内权重 | 证据等级 | 打分依据 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for metric in primary.get("metrics") or []:
        detail = metric.get("detail") or {}
        basis = _basis_summary(detail.get("basis")) or detail.get("formula") or metric.get("reason") or ""
        lines.append(
            f"| {metric['metric_id']} | {metric['name']} | {detail.get('source_metric') or '—'} | "
            f"{_num(metric['value'])} | — | {metric['evidence_level']} | {basis[:70]} |")
    lines.append("")
    audit = ((result.get("metric_graph") or {}).get("primary") or {}).get("audit") or {}
    v2_audit = (result.get("metric_graph") or {}).get("v2_audit") or {}
    lines.append(
        f"- 指标依赖图：Primary 共 {audit.get('n_nodes')} 个指标节点，"
        f"重复计数组 {audit.get('n_duplicate_groups')} 个（clean={audit.get('clean')}）；"
        f"TSI 2.0 审计发现 {v2_audit.get('n_duplicate_groups')} 组重复输入"
        f"（{', '.join('-'.join(g['metrics']) for g in v2_audit.get('duplicate_groups') or [])}）。")
    lines.append(
        "- 指标缺失策略：" + (primary.get("method_note") or ""))
    lines.append("")
    return "\n".join(lines)
