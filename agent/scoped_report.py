"""单层级详实报告（宏观 / 中观 / 微观）。

用户只关心一个层级时，不把另外两层的内容塞进报告：这里只渲染所选层级的数据，
并把该层级的证据、缺口、建议与模拟写全（Finding → Evidence → Model → Action →
Simulation）。三视角完整报告仍由 :mod:`agent.report` 的 18 节渲染负责。
"""

from __future__ import annotations

from typing import Any, Mapping

from .scope import SCALE_AUDIENCE, SCALE_LABEL


def _retrieval_ledger_block(result: Mapping[str, Any], limit: int = 12) -> list[str]:
    """全面检索台账：本地缓存 → 规范源 → 归档 → 采集产物 → 联网补采计划。"""
    ledger = result.get("retrieval_ledger")
    if not ledger:
        return []
    from edumatch.retrieval_sweep import render_ledger_markdown

    return render_ledger_markdown(ledger, limit=limit)


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _pct(value: Any, digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _header(result: Mapping[str, Any], scale: str) -> list[str]:
    plan = result.get("plan") or {}
    occ = ((result.get("occupation") or {}).get("occupation") or {}).get("name")
    primary = result.get("primary_tsi") or {}
    return [
        f"# EduMatch｜{SCALE_LABEL[scale]}",
        "",
        f"**读者**：{SCALE_AUDIENCE[scale]}　**层级**：`{scale}`",
        f"**研究对象**：{plan.get('school') or '（未点名高校）'} {plan.get('major') or ''}"
        + (f"　**目标岗位**：{occ}" if occ else ""),
        f"**运行编号**：`{result.get('run_id') or '—'}`　"
        f"**Primary TSI**：**{_num(primary.get('primary_tsi'))}**"
        f"（{primary.get('band') or '—'}；覆盖率 {_pct(primary.get('weighted_coverage'))}）",
        "",
        "> 本报告只覆盖你选择的一个层级；如需另外两层，可在生成后选择「三视角完整版」。",
        "",
        "---",
        "",
    ]


def _findings_block(result: Mapping[str, Any], keys: tuple[str, ...], limit: int = 4) -> list[str]:
    findings = [f for f in (result.get("findings") or []) if str(f.get("id")) in keys]
    if not findings:
        return []
    lines = ["## 关键结论（Finding → Model → Action → Simulation）", ""]
    for index, item in enumerate(findings[:limit], start=1):
        lines.append(f"**{index}. {item.get('title')}**")
        lines.append("")
        lines.append(f"- **Finding**：{item.get('statement')}")
        if item.get("model"):
            lines.append(f"- **Model**：{item['model']}")
        if item.get("action"):
            lines.append(f"- **Action**：{item['action']}")
        if item.get("simulation"):
            lines.append(f"- **Simulation**：{item['simulation']}")
        lines.append("")
    return lines


def _tsi_block(result: Mapping[str, Any]) -> list[str]:
    primary = result.get("primary_tsi") or {}
    dims = primary.get("dimensions") or {}
    if not dims:
        return []
    lines = ["## Primary TSI 分解（唯一正式总分）", "",
             "| 维度 | 得分 | 权重 | 覆盖率 | 缺失指标 |", "| --- | ---: | ---: | ---: | --- |"]
    for dim in dims.values():
        lines.append(f"| {dim.get('name')} | {_num(dim.get('score'))} | {dim.get('weight')} | "
                     f"{_pct(dim.get('coverage'))} | {', '.join(dim.get('missing_indicators') or []) or '无'} |")
    lines += ["", f"- Match / Skill Fit 是子指标，不构成第二个总分；缺失指标 "
              f"{', '.join(primary.get('missing_indicators') or []) or '无'} 不参与加权。", ""]
    return lines


def _evidence_block(result: Mapping[str, Any], limit: int = 12,
                    exclude_types: tuple[str, ...] = ()) -> list[str]:
    evidence = [e for e in (result.get("evidence") or [])
                if str(e.get("source_type") or "") not in exclude_types]
    lines = ["## 证据与复现", "",
             f"- 本轮登记证据 {len(evidence)} 条；每条含 `locator / quote / level / confidence`。",
             f"- 复现命令见 `result['plan']`；计算原则：数值只由 `analysis/` 确定性函数产出。"]
    rows = [e for e in evidence if e.get("evidence_level") in {"A", "B"}][:limit]
    if rows:
        lines += ["", "| 证据ID | 等级 | 标题 | 定位 |", "| --- | --- | --- | --- |"]
        for item in rows:
            lines.append(f"| {item.get('evidence_id')} | {item.get('evidence_level')} | "
                         f"{item.get('title')} | {(item.get('locator') or '')[:70]} |")
    lines.append("")
    return lines


def _md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return out


def _sources_block(result: Mapping[str, Any]) -> list[str]:
    """宏观信息源 · 覆盖院校台账：逐校写清"哪所院校提供了什么材料"。"""
    from reporting.render import school_ledger

    ledger = school_ledger(result)
    if not ledger:
        return []
    supply = result.get("supply") or {}
    target = (result.get("plan") or {}).get("school") or ""
    peers = [n for n, d in ledger.items() if "区域同类校" in d["roles"]]
    rows: list[list[Any]] = []
    for name, d in sorted(ledger.items(), key=lambda kv: -(kv[1]["n_courses"] or 0)):
        mats = "、".join(f"{m}（{st}）" for m, st in (d["materials"] or {}).items()) or "未获取"
        outcome = d["outcome"] or {}
        bits = []
        if isinstance(outcome.get("placement_rate"), (int, float)):
            bits.append(f"落实率 {_pct(outcome['placement_rate'])}%")
        if isinstance(outcome.get("further_study_rate"), (int, float)):
            bits.append(f"深造率 {_pct(outcome['further_study_rate'])}%")
        if isinstance(outcome.get("signing_rate"), (int, float)):
            bits.append(f"签约率 {_pct(outcome['signing_rate'])}%")
        roles = "、".join(d["roles"]) or "覆盖样本"
        source = d["domain"] or ("培养方案课程池 · 本地归档" if d["n_courses"]
                                else "就业质量报告 · 本地归档")
        state = d["status"] or "—"
        if d.get("harvest_note"):
            state += f"（{str(d['harvest_note'])[:50]}）"
        rows.append([name, roles, d["n_courses"] if d["n_courses"] is not None else "—",
                     mats, "、".join(bits) or "未获取", source, state])
    progress = (result.get("auto_harvest") or {}).get("region_progress") or {}
    head = [f"- 本期宏观供给来自 **{len(ledger)} 所院校**：目标校 **{target or '未指定'}**，"
            f"区域同类校 {len(peers)} 所"
            + (f"（{'、'.join(peers[:12])}）" if peers else "") + "。",
            "- 目标校**不合入**区域池；搜索到 URL ≠ 已覆盖，只有材料到 READY_FOR_ANALYSIS 才计入课程池。"]
    if progress:
        head.append(f"- 区域补采进度：目标池 {progress.get('pool', '—')} 所、已完成 "
                    f"{progress.get('done', '—')} 所、待采 {progress.get('remaining', '—')} 所"
                    "（可重复调用累积）。")
    return (["## 1.1 宏观信息源 · 覆盖院校台账", ""] + head + [""]
            + _md_table(["院校", "角色", "可核查课程", "材料类型 · 状态",
                         "就业结果（该校口径）", "来源渠道", "状态"], rows) + [""])


def _demand_profile_block(result: Mapping[str, Any]) -> list[str]:
    """需求侧画像：学历结构 / 行业分布 / 技能热度 / 薪资。"""
    occ = result.get("occupation") or {}
    req = occ.get("requirements") or {}
    market = result.get("market") or {}
    name = ((occ.get("occupation") or {}).get("name")) or "目标岗位"
    edu = {k: v for k, v in (req.get("education_distribution") or {}).items()
           if isinstance(v, (int, float))}
    inds = market.get("industries") or []
    rows = (occ.get("demand_top") or [])[:10]
    if not (edu or inds or rows):
        return []
    lines = ["## 1.2 需求侧画像（岗位要什么）", "",
             f"- 目标岗位：**{name}**；可观察岗位招聘记录 "
             f"{occ.get('n_jobs') if occ.get('n_jobs') is not None else '—'} 条"
             f"（匹配口径 {occ.get('match_scope') or '—'}）。"]
    med = req.get("median_salary") if isinstance(req.get("median_salary"), (int, float)) \
        else market.get("median_salary_target")
    p25 = req.get("p25_salary") if isinstance(req.get("p25_salary"), (int, float)) \
        else market.get("salary_p25_target")
    p75 = req.get("p75_salary") if isinstance(req.get("p75_salary"), (int, float)) \
        else market.get("salary_p75_target")
    n_salary = req.get("n_with_salary") or market.get("n_salary_target")
    n_daily = req.get("n_daily_excluded") or market.get("n_daily_salary_excluded")
    lines.append("- 薪资口径：" + (
        f"目标岗位月薪中位 {_num(med, 0)} 元（P25 {_num(p25, 0)} / P75 {_num(p75, 0)}）/ "
        f"同城基线 {_num(market.get('median_salary_baseline'), 0)} 元；"
        f"有月薪数值 {n_salary if n_salary is not None else '—'} 条"
        + (f"，日薪/兼职 {n_daily} 条不并入月薪口径" if n_daily else "")
        if isinstance(med, (int, float))
        else "未获取（该批岗位未提供可用月薪数值，不估算）"))
    lines.append("")
    buckets = req.get("salary_buckets") or market.get("salary_buckets") or {}
    if buckets:
        order = ["<8k", "8k-15k", "15k-25k", "25k-40k", ">40k"]
        lines += ["**月薪分档分布（目标岗位切片）**", ""] + _md_table(
            ["月薪档", "岗位数"],
            [[k, buckets[k]] for k in order if k in buckets]
            + [[k, v] for k, v in buckets.items() if k not in order]) + [""]
    if edu:
        total = sum(edu.values()) or 1
        lines += ["**学历结构**", ""] + _md_table(
            ["学历档", "记录数", "占比"],
            [[k, v, f"{v / total * 100:.1f}%"] for k, v in
             sorted(edu.items(), key=lambda kv: -kv[1])]) + [""]
    if inds:
        lines += ["**招聘行业分布**（平台原始标签，只作群体热度参照）", ""] + _md_table(
            ["行业", "记录数"], [[str(x[0]), x[1]] for x in inds[:10]]) + [""]
    if rows:
        lines += ["**岗位技能热度 Top 10**（需求向量强度）", ""] + _md_table(
            ["技能", "需求强度"], [[r.get("skill"), _num(r.get("demand"))] for r in rows]) + [""]
    return lines


def _benchmark_block(result: Mapping[str, Any],
                     heading: str = "## 1.3 目标校 × 同类校 × 市场基准") -> list[str]:
    """目标校 × 同类校 × 市场：三角对照 + 技能级三方对照。"""
    bench = result.get("benchmark") or {}
    tri = bench.get("triangle") or {}
    sk = bench.get("skill_benchmark") or {}
    tri_rows = tri.get("rows") or []
    sk_rows = sk.get("rows") or []
    if not tri_rows and not sk_rows:
        return []
    lines = [heading, ""]
    if tri_rows:
        lines += [f"口径：{tri.get('label') or '—'}（{tri.get('note') or ''}）", ""]
        lines += _md_table(["维度", "目标高校", "同类专业基准", "市场"],
                           [[r.get("dimension"), r.get("target"), r.get("peer"), r.get("market")]
                            for r in tri_rows])
        for finding in (tri.get("findings") or []):
            lines.append(f"- {finding}")
        lines.append("")
    if sk_rows:
        lines += ["**逐技能：市场需求 vs 目标校供给 vs 同类校供给**", ""] + _md_table(
            ["技能", "市场需求", "目标校供给", "同类校供给", "目标缺口", "差值", "判定"],
            [[r.get("skill"), _num(r.get("market_demand")), _num(r.get("target_supply")),
              _num(r.get("peer_supply")), _num(r.get("target_gap")),
              _num(r.get("target_vs_peer")), r.get("reading")] for r in sk_rows[:14]]) + [""]
    return lines


def _outcome_block(result: Mapping[str, Any]) -> list[str]:
    """同类高校就业结果对比：逐校列出，缺失记 null 不排序。"""
    bench = result.get("benchmark") or {}
    entities = ((bench.get("education_background") or {}).get("entities")) or []
    if not entities:
        return []
    lines = ["## 1.4 同类高校就业结果对比（逐校）", ""]
    med = bench.get("benchmarks") or {}
    note = "；".join(f"{k} 中位数 {_pct((v or {}).get('median'))}%（n={(v or {}).get('n')}）"
                    for k, v in med.items() if (v or {}).get("median") is not None)
    lines.append(f"- 基准中位数：{note or '未获取'}；缺失显示 null，不参与排序。")
    lines.append("")
    lines += _md_table(["院校", "落实率", "深造率", "签约率"],
                       [[e.get("entity"),
                         f"{_pct(e.get('placement_rate'))}%" if isinstance(e.get("placement_rate"), (int, float)) else "未获取",
                         f"{_pct(e.get('further_study_rate'))}%" if isinstance(e.get("further_study_rate"), (int, float)) else "未获取",
                         f"{_pct(e.get('signing_rate'))}%" if isinstance(e.get("signing_rate"), (int, float)) else "未获取"]
                        for e in entities[:14]]) + [""]
    return lines


def _policy_block(result: Mapping[str, Any]) -> list[str]:
    """政策与产业方向：只输出关联路径与热度，不做因果断言。"""
    pol = result.get("policy") or {}
    counts = pol.get("industry_counts") or {}
    skills = pol.get("skills_related") or []
    lit = result.get("literature") or {}
    if not (counts or skills or lit.get("top_by_citation")):
        return []
    lines = ["## 5. 政策与产业方向（关联路径，非因果）", "",
             f"- 本地政策库 {pol.get('n_documents') if pol.get('n_documents') is not None else '—'} 份，"
             f"命中本主题 {pol.get('n_matched_documents') if pol.get('n_matched_documents') is not None else '—'} 份。", ""]
    if counts:
        lines += _md_table(["产业方向", "命中文件数"],
                           [[k, v] for k, v in sorted(counts.items(), key=lambda kv: -(kv[1] or 0))[:10]]) + [""]
    if skills:
        lines += ["- 政策文本关联能力方向：" + "、".join(str(s) for s in skills[:18]), ""]
    works = lit.get("top_by_citation") or []
    if works:
        lines += ["- 方法论学术依据（文献，非本项目一手数据）："]
        for w in works[:5]:
            lines.append(f"  - {w.get('title')}（{w.get('year')}，被引 {w.get('cited_by_count')}）")
        lines.append("")
    return lines


def _assets_block(result: Mapping[str, Any]) -> list[str]:
    """数据资产总览：这一版到底动了多少数据 + 证据等级分布。"""
    ds = result.get("dataset_summary") or {}
    src = result.get("data_source") or {}
    evidence = list(result.get("evidence") or [])
    if not (ds or evidence):
        return []
    levels: dict[str, int] = {}
    for item in evidence:
        lv = str(item.get("evidence_level") or "E").upper()
        levels[lv] = levels.get(lv, 0) + 1
    return ["## 数据资产总览", "",
            f"- 本地文档 {ds.get('n_documents', '—')} 份；教育事实 {ds.get('n_education_facts', '—')} 条；"
            f"课程 {ds.get('n_courses', '—')} 门；政策 {ds.get('n_policies', '—')} 份。",
            f"- 数据口径：{src.get('mode') or 'local'}；本轮采集入库课程 "
            f"{src.get('harvest_courses', '—')} 门、事实 {src.get('harvest_facts', '—')} 条。",
            f"- 登记证据 {len(evidence)} 条；等级分布 "
            + ("、".join(f"{k} {v} 条" for k, v in sorted(levels.items())) or "未获取") + "。",
            ""]


def _micro_gap_block(micro: Mapping[str, Any]) -> list[str]:
    """个人缺口表：岗位需求 vs 个人供给；未出现记证据不足，不记 0。"""
    demand = ((micro.get("demand_layers") or {}).get("skill")) or {}
    supply = (micro.get("personal_supply") or {}).get("skill") or {}
    if not demand:
        return []
    rows = sorted(((k, v if isinstance(v, (int, float)) else 0.0)
                   for k, v in demand.items()), key=lambda kv: -kv[1])[:12]
    return (["### 个人缺口 · 岗位需求 vs 个人供给", ""]
            + _md_table(["技能", "岗位需求", "个人供给", "判定"],
                        [[k, _num(v),
                          _num(supply.get(k)) if isinstance(supply.get(k), (int, float)) else "证据不足",
                          "已提供可核查证据" if isinstance(supply.get(k), (int, float))
                          else "个人证据未出现（≠0，补材料后可重算）"] for k, v in rows]) + [""])


def _curriculum_block(result: Mapping[str, Any]) -> list[str]:
    """中观核心台账：本校课程 × 技能矩阵（逐门可核查）+ 未映射课程。"""
    csm = result.get("course_skill_matrix") or {}
    ids = list(csm.get("course_ids") or [])
    skills = list(csm.get("skills") or [])
    matrix = list(csm.get("matrix") or [])
    if not (ids and skills and matrix):
        return []
    meta = {c.get("course_id"): c for c in (result.get("courses") or [])}
    rows: list[list[Any]] = []
    for i, cid in enumerate(ids):
        row = matrix[i] if i < len(matrix) else []
        hit = [skills[j] for j, v in enumerate(row)
               if j < len(skills) and isinstance(v, (int, float)) and v > 0]
        if hit:
            rows.append([cid, hit])
    rows.sort(key=lambda r: -len(r[1]))
    unmapped = csm.get("unmapped_courses") or []
    credits = csm.get("credits_by_skill") or {}
    out = ["## 1.1 课程 × 技能矩阵（逐门可核查）", "",
           f"- 共 {len(rows)} 门课程在口径内承载至少 1 项技能；另有 {len(unmapped)} 门未映射"
           "（多为通识/体育/实践类）。供给强度 = 课程学分权重归一，0 表示口径内未见承载。", ""]
    if credits:
        out += _md_table(["技能", "学分权重"],
                         [[k, _num(v)] for k, v in
                          sorted(credits.items(), key=lambda kv: -(kv[1] or 0))[:12]]) + [""]
    out += _md_table(["课程", "学分", "类别", "承载技能"],
                     [[(meta.get(cid) or {}).get("name") or cid,
                       _num((meta.get(cid) or {}).get("credits"), 1),
                       "实践环节" if (meta.get(cid) or {}).get("is_practice")
                       else ("必修" if (meta.get(cid) or {}).get("is_required") else "选修/未知"),
                       "、".join(hit[:10])] for cid, hit in rows[:20]]) + [""]
    if unmapped:
        out += [f"- 未映射课程（{len(unmapped)} 门）：" + "、".join(str(x) for x in unmapped[:40]), ""]
    return out


def _macro(result: Mapping[str, Any]) -> str:
    occ = result.get("occupation") or {}
    job = result.get("occupation_match") or {}
    gaps = result.get("skill_gaps") or {}
    coverage = result.get("coverage") or {}
    supply = result.get("supply") or {}
    n_pool = supply.get("peer_n_schools") or len(supply.get("peer_by_school") or [])
    major_name = (result.get("plan") or {}).get("major") or "本专业"
    alignment = (result.get("semantic") or {}).get("objective_job_alignment") or {}
    mechanism = result.get("mechanism") or {}
    lines = _header(result, "macro")
    lines += _findings_block(result, ("F-tsi", "F-gap-1", "F-gap-2", "F-gap-3"), 4)
    lines += [
        "## 1. 区域供给口径 · " + f"{major_name}相关培养能力"
        + (f"（覆盖 {n_pool} 所院校课程池）" if n_pool else "（覆盖高校样本）"), "",
        f"- 覆盖高校 {coverage.get('n_schools') if coverage.get('n_schools') is not None else '—'} 所；"
        "**这是本地入库样本，不是全市全量**。",
        "- 需求口径：**Observed Job Posting Demand**"
        + (f"——{occ.get('n_jobs')} 条可观察岗位招聘记录（匹配口径 {occ.get('match_scope')}）。"
           if occ.get("n_jobs") is not None else "——本轮无可用岗位语料。"),
        "- 招聘记录不等于社会岗位总需求；课程池不等于全市总供给。",
        "",
    ]
    lines += _sources_block(result)
    lines += _demand_profile_block(result)
    lines += _benchmark_block(result)
    lines += _outcome_block(result)
    if alignment:
        if alignment.get("similarity") is None:
            lines += ["## 2. 培养目标与岗位能力一致性（S1）", "",
                      f"- 证据不足（不记 0）：{alignment.get('notes') or '未检索到可核查的培养目标原文'}。", ""]
        else:
            lines += ["## 2. 培养目标与岗位能力一致性（S1）", "",
                      f"- S1 = **{_num(alignment.get('similarity'))}**，覆盖 "
                      f"{alignment.get('n_covered')}/{alignment.get('n_demanded')} 项需求能力"
                      f"（依据 {alignment.get('basis')}）。", ""]
    lines += _tsi_block(result)
    rows = [r for r in (gaps.get("rows") or []) if r.get("status") == "gap"][:10]
    if rows:
        lines += ["## 3. 关键技能缺口（区域口径）", "",
                  "| 技能 | 需求 | 供给 | 缺口 | 供给依据 |", "| --- | ---: | ---: | ---: | --- |"]
        for row in rows:
            lines.append(f"| {row.get('skill')} | {_num(row.get('demand'))} | {_num(row.get('supply'))} | "
                         f"{_num(row.get('gap'))} | {row.get('supply_basis') or '—'} |")
        lines.append("")
    if job.get("match_100") is not None:
        lines += ["## 4. 岗位大类匹配（子指标）", "",
                  f"- 覆盖需求技能 {job.get('n_skills_covered')}/{job.get('n_skills_compared')}；"
                  f"定义性缺失：{'、'.join(job.get('definitional_missing') or []) or '无'}。", ""]
    paths = mechanism.get("paths") or []
    if paths:
        lines += ["## 5. 政策—产业—岗位—技能关联路径", "",
                  f"- 跟踪 {len(paths)} 条技能路径；输出为**关联路径**，不做因果断言。",
                  "| 技能 | 政策提及 | 市场需求 | 课程覆盖 | 路径状态 |",
                  "| --- | --- | ---: | ---: | --- |"]
        for row in paths[:10]:
            lines.append(f"| {row.get('skill')} | {'是' if row.get('policy_mentioned') else '—'} | "
                         f"{_num(row.get('market_demand'))} | {_num(row.get('course_supply'))} | "
                         f"{row.get('path_status')} |")
        lines.append("")
    sim = result.get("simulation") or {}
    if sim.get("scenarios"):
        lines += ["## 6. 政策/布局方案模拟（decision support）", "",
                  "| 方案 | ΔSkillFit | 近似 ΔTSI | 关闭缺口数 |", "| --- | ---: | ---: | ---: |"]
        for scenario in sim["scenarios"]:
            lines.append(f"| {scenario.get('name')} | {_num(scenario.get('delta_fit_100'))} | "
                         f"{_num(scenario.get('delta_tsi_estimate'))} | {scenario.get('gaps_closed')} |")
        lines += ["", "- 模拟只对已提出的方案做量化，不限制建议范围；ΔTSI 为近似值。", ""]
    lines += _policy_block(result)
    lines += _retrieval_ledger_block(result)
    lines += _assets_block(result)
    lines += _evidence_block(result)
    return "\n".join(lines)


def _meso(result: Mapping[str, Any]) -> str:
    supply = (result.get("supply") or {}).get("target") or {}
    occ = result.get("occupation") or {}
    job = result.get("occupation_match") or {}
    gaps = result.get("skill_gaps") or result.get("skill_gaps_target") or {}
    bench = result.get("benchmark") or {}
    conflicts = result.get("conflict_resolution") or {}
    alignment = (result.get("semantic") or {}).get("objective_job_alignment") or {}
    lines = _header(result, "meso")
    lines += _findings_block(result, ("F-tsi", "F-gap-1", "F-gap-2", "F-match", "F-objective"), 5)
    lines += [
        "## 1. 培养方案画像（本专业在培养什么）", "",
        f"- 可核查课程 {supply.get('n_courses', '—')} 门（映射 {supply.get('n_mapped_courses', '—')} 门，"
        f"可靠度 {supply.get('reliability') or '—'}）。",
        "- 供需两侧来源：02 培养方案解析 / 04 招聘分析 → 05 技能本体归一 → 06 匹配模型。",
        "",
    ]
    lines += _curriculum_block(result)
    if alignment:
        lines += ["### 培养目标—岗位能力一致性（S1）", ""]
        if alignment.get("similarity") is None:
            lines += [f"- 证据不足（不记 0）：{alignment.get('notes') or '未检索到可核查的培养目标原文'}。",
                      "- 已检索来源：培养方案 / 专业介绍 / 教学质量报告 / 就业质量报告（自动抽取正文）。", ""]
        elif alignment.get("proxy_school_level"):
            lines += [f"- 只有**校级**培养目标代理（值 {_num(alignment.get('similarity'))}，"
                      f"覆盖 {alignment.get('n_covered')}/{alignment.get('n_demanded')} 项需求能力）："
                      "**不计入 Primary TSI**，仅作背景参考，不能当作专业级结论。",
                      f"- 依据：{alignment.get('basis')}", ""]
        else:
            lines += [f"- S1 = **{_num(alignment.get('similarity'))}**，覆盖 "
                      f"{alignment.get('n_covered')}/{alignment.get('n_demanded')} 项需求能力"
                      f"（依据 {alignment.get('basis')}）。",
                      f"- 已覆盖：{'、'.join(alignment.get('covered_skills') or []) or '—'}",
                      f"- 未覆盖：{'、'.join(alignment.get('missing_skills') or []) or '—'}", ""]
    if occ.get("demand_status") == "ok" or occ.get("demand_top"):
        lines += ["## 2. 目标岗位画像", "",
                  "| 岗位需求技能 | 需求强度 |", "| --- | ---: |"]
        for row in (occ.get("demand_top") or [])[:12]:
            lines.append(f"| {row.get('skill')} | {_num(row.get('demand'))} |")
        req = occ.get("requirements") or {}
        if req.get("education_distribution"):
            lines += ["", "- 学历结构：" + "、".join(
                f"{k} {v} 条" for k, v in req["education_distribution"].items())]
        lines.append("")
    lines += _tsi_block(result)
    if job.get("match_100") is not None:
        lines += ["## 3. 目标岗位匹配（子指标）", "",
                  f"- Match = **{_num(job.get('match_100'))}**（{job.get('band')}）；"
                  f"覆盖 {job.get('n_skills_covered')}/{job.get('n_skills_compared')}，"
                  f"缺失 {job.get('n_skills_missing')} 项。", ""]
    rows = [r for r in (gaps.get("rows") or []) if r.get("status") == "gap"][:12]
    if rows:
        lines += ["## 4. 能力缺口明细", "",
                  "| 技能 | 需求 | 本校供给 | 缺口 | 判定 |", "| --- | ---: | ---: | ---: | --- |"]
        for row in rows:
            lines.append(f"| {row.get('skill')} | {_num(row.get('demand'))} | {_num(row.get('supply'))} | "
                         f"{_num(row.get('gap'))} | {row.get('status')} |")
        lines.append("")
    if bench:
        lines += ["## 5. 同类院校对比（Benchmark）", "",
                  f"- 基准口径：{bench.get('scope') or bench.get('status') or '—'}；"
                  f"基准 Skill Fit {_num(bench.get('skill_fit_100') or bench.get('fit_100'))}。",
                  "- 课程数量只是证据，不是结论；比较的是四层培养能力。", ""]
        lines += _benchmark_block(result, heading="### 逐技能：本校 vs 同类校 vs 市场")
    if conflicts.get("records"):
        lines += ["## 6. 证据冲突消解", "",
                  "| 技能 | 原结果 | 修正后 | 依据 |", "| --- | ---: | ---: | --- |"]
        for record in conflicts["records"]:
            lines.append(f"| {record.get('changed_skill')} | {_num(record.get('original_result'))} | "
                         f"{_num(record.get('reconciled_result'))} | {record.get('evidence_source')} |")
        lines += ["", f"- 只重算受影响技能（{', '.join(conflicts.get('changed_skills') or [])}）；"
                  f"范围：{conflicts.get('recalculation_scope')}。", ""]
    sim = result.get("simulation") or {}
    if sim.get("scenarios"):
        lines += ["## 7. 培养方案优化模拟", "",
                  "| 方案 | Skill Fit 前→后 | 近似 ΔTSI | 关闭缺口 |", "| --- | --- | ---: | ---: |"]
        for scenario in sim["scenarios"]:
            lines.append(f"| {scenario.get('name')} | {_num(scenario.get('fit_100_before'))} → "
                         f"{_num(scenario.get('fit_100_after'))} | "
                         f"{_num(scenario.get('delta_tsi_estimate'))} | {scenario.get('gaps_closed')} |")
        lines += ["", "- 模拟为方案假设下的结构性变化，不是就业结果预测。", ""]
    lines += _retrieval_ledger_block(result)
    lines += _assets_block(result)
    lines += _evidence_block(result)
    return "\n".join(lines)


def _micro(result: Mapping[str, Any]) -> str:
    micro = result.get("micro_result") or {}
    lines = _header(result, "micro")
    if not micro:
        lines += ["## 个人尺度需要个人画像输入", "",
                  "未收到个人画像。请用 `--micro-text \"我学过 …\"` 或 `--micro-file <path>` 提供；"
                  "只给学校+专业+年级+目标岗位也可以（L0 专业基准，会明确标注）。", ""]
        return "\n".join(lines)
    lines += _findings_block(result, ("F-micro-skill", "F-micro-practice",
                                      "F-micro-knowledge", "F-micro-capability"), 4)
    lines += [
        "## 1. 个人证据画像（L0–L4）", "",
        f"- 证据分层：**L{micro.get('sparse_level')}**"
        + ("（Major Baseline 专业基准推断，**不是真实个人能力判断**）"
           if micro.get("baseline") else "（基于个人证据）"),
        f"- 个人岗位适配（子指标）：**{_num(micro.get('fit_100'))}**/100；"
        f"供给口径 `{micro.get('supply_provenance')}`。",
        f"- 证据条目：" + "、".join(f"{k} {v}" for k, v in (micro.get("evidence_summary") or {}).items()),
        "- 证据分层口径：L0 只有院校/专业/年级/岗位 · L1 +课程 · L2 +技能 · "
        "L3 +项目/能力 · L4 +实习/科研/作品集/结果；层级只决定结论强度，不改变缺口算法。",
        "",
    ]
    lines += _micro_gap_block(micro)
    lines += [
        "## 2. 四层缺口（Knowledge / Skill / Capability / Practice，分别输出，不合成一个数字）", "",
        "| 层 | 缺口项数 | 明细 |", "| --- | ---: | --- |",
    ]
    for layer, label in (("knowledge", "知识 Gap"), ("skill", "技能 Gap"),
                         ("capability", "能力 Gap"), ("practice", "实践 Gap")):
        block = (micro.get("gaps") or {}).get(layer) or {}
        if block.get("status") != "ok":
            lines.append(f"| {label} | — | 证据不足：{block.get('reason') or '缺需求向量'} |")
            continue
        top = block.get("top_gaps") or []
        not_ev = block.get("not_evidenced") or []
        detail = ("缺口：" + "、".join(f"{r['item']}（{_num(r['gap'])}）" for r in top[:5])) if top else "—"
        if not_ev:
            detail += "；未在个人证据中出现（≠0）：" + "、".join(str(x) for x in not_ev[:5])
        lines.append(f"| {label} | {block.get('n_gap', 0)} | {detail} |")
    actions = micro.get("priority_actions") or []
    if actions:
        lines += ["", "## 3. 优先行动与学习路径", ""]
        for action in actions[:8]:
            lines.append(f"- **{action.get('layer')}**｜{action.get('action')}")
    declared = (micro.get("declared") or {}).get("absences") or []
    if declared:
        lines += ["", "## 4. 用户自述缺项（不等于 0 分）", "",
                  "、".join(str(a.get("item")) for a in declared), ""]
    lines += ["", "## 5. 边界", "",
              "- 个人未被证据覆盖的技能记**证据不足**，不记 0；",
              "- 个人读数不与专业级/区域级数字直接换算；",
              "- 示例输入不代表真实个人，需本人确认后使用。", ""]
    lines += _assets_block(result)
    lines += _evidence_block(result, exclude_types=("literature", "policy"))
    return "\n".join(lines)


def render_scoped(result: Mapping[str, Any], scale: str) -> str:
    if scale == "macro":
        return _macro(result)
    if scale == "meso":
        return _meso(result)
    if scale == "micro":
        return _micro(result)
    raise ValueError(f"unknown scale: {scale}")
