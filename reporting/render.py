# -*- coding: utf-8 -*-
"""任意院校/专业的引擎结果 → 既有版式的单文件 HTML（Core 正式入口）。

这是**正式交付版式的唯一出口**：复用 `reporting.theme`（CSS/JS）与
`reporting.components`（图表/TSI Tree/S1/检索台账），因此任意院校专业生成的
分析报告与既有《人工智能 × 大模型算法工程师》演示页面是同一套版式。

命令行：

    python -m reporting.render --result <result.json> --scope all  --out 三视角报告.html
    python -m reporting.render --result <result.json> --scope micro --out 微观报告.html

大模型也可以基于同一套 theme/components **自行编写新的渲染脚本或页面**，
但必须复用本模块的主题与构件，保证视觉与信息结构一致。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from . import components as C
from .theme import CSS, JS

from edumatch.vocab import clean_vocabulary


def _dims_scores(primary: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (primary.get("dimensions") or {}).items():
        score = value.get("score") if isinstance(value, Mapping) else value
        if isinstance(score, (int, float)):
            out[key] = float(score)
    return out


def _indicators(primary: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"id": m.get("metric_id"), "name": m.get("name"),
             "value": m.get("value"), "level": m.get("evidence_level"),
             "status": m.get("status")} for m in (primary.get("metrics") or [])]


def _indicator_value(primary: Mapping[str, Any], metric_id: str):
    """按指标号取已算好的值（取不到返回 None，渲染层显示「—」）。"""
    for m in (primary.get("metrics") or []):
        if str(m.get("metric_id")) == metric_id:
            return m.get("value")
    return None


def _demand_rows(result: Mapping[str, Any], limit: int = 16) -> list[dict[str, Any]]:
    rows = result.get("demand_rows")
    if rows:
        rows = clean_rows_quiet(rows)
        return list(rows)[:limit]
    occupied = ((result.get("occupation") or {}).get("demand_top")) or []
    rows = [{"skill": r.get("skill"), "demand": r.get("demand")} for r in occupied]
    rows = clean_rows_quiet(rows)
    return rows[:limit]


def clean_rows_quiet(rows):
    """按清洗后的技能名过滤行（渲染层统一入口，避免"同类项一大堆"）。"""
    names = [str(r.get("skill")) for r in rows]
    kept, _audit = clean_vocabulary(names)
    keep = set(kept)
    return [r for r in rows if str(r.get("skill")) in keep]


def _supply_scores(result: Mapping[str, Any], scope: str = "used") -> dict[str, float]:
    """取供给向量。

    ``scope="macro"`` 必须用 **peer（区域同类专业课程池）**——宏观层回答的是"这个区域
    能供给什么"，不是"我这一所学校供给了什么"；``scope="meso"`` 用 target（本校）。
    """
    bundle = result.get("supply") or {}
    if scope == "macro":
        key = "peer"
    elif scope == "meso":
        key = "target"
    else:
        key = bundle.get("used_for_legacy_fit") or bundle.get("used") or "peer"
    info = (bundle.get(key) or bundle.get("peer") or bundle.get("target") or {})
    rows = clean_rows_quiet(list(info.get("top_skills") or []))
    scores = {str(r.get("skill")): float(r.get("supply") or 0.0) for r in rows}
    # `top_skills` 只截了前 12 项：若不补齐，未进前 12 的技能会被画成"供给 0.00"，
    # 那不是"没供给"，是"没进榜单"。用全量向量/逐技能基准补上真实读数。
    if key == "target":
        full = (result.get("course_skill_matrix") or {}).get("supply") or {}
        for skill, value in full.items():
            if isinstance(value, (int, float)):
                scores.setdefault(str(skill), float(value))
    else:
        bench = (result.get("benchmark") or {}).get("skill_benchmark") or {}
        for row in (bench.get("rows") or []):
            value = row.get("peer_supply")
            if isinstance(value, (int, float)):
                scores.setdefault(str(row.get("skill")), float(value))
    return scores


def _tree_adapter(result: Mapping[str, Any], scope: str = "used") -> dict[str, Any]:
    primary = result.get("primary_tsi") or {}
    return {
        "tsi": primary.get("primary_tsi"),
        "tsi_dimensions": _dims_scores(primary),
        "tsi_indicators": _indicators(primary),
        "demand_top": _demand_rows(result, limit=20),
        "supply_scores": _supply_scores(result, scope),
    }


def _cite_for(result: Mapping[str, Any], refs, *keywords) -> str:
    """按关键词挑一条已登记证据生成上标引用（找不到就留空，不硬造）。"""
    if refs is None:
        return ""
    evidence = list(result.get("evidence") or [])
    for item in evidence:
        text = f'{item.get("title") or ""}{item.get("locator") or ""}{item.get("source_type") or ""}'
        if any(k and k in text for k in keywords):
            return refs.cite(item.get("evidence_id"))
    # 关键词对不上时，用第一条已登记证据兜底（仍是真实登记过的来源，不硬造编号）
    return refs.cite(evidence[0].get("evidence_id")) if evidence else ""


def _demand_label(result: Mapping[str, Any]) -> tuple[str, float | None]:
    """需求侧口径标签：岗位族命中就用岗位名；否则退回"按专业导出语料"。

    报告标题与提示语必须用**真实口径**措辞——岗位族没解析成功不代表没有需求，
    本系统会退到专业作用域语料（`demand_scope.coverage`），说反话会让读者误判。
    """
    occ_block = result.get("occupation") or {}
    occ = occ_block.get("occupation") or {}
    coverage = ((result.get("demand_scope") or {}).get("coverage")) or {}
    name = str(occ.get("name") or "").strip()
    n_jobs = occ_block.get("n_jobs")
    if name and isinstance(n_jobs, (int, float)) and n_jobs:
        return name, float(n_jobs)
    label = str(coverage.get("label") or "").strip()
    n_used = coverage.get("n_jobs") or coverage.get("n_used")
    if label and isinstance(n_used, (int, float)) and n_used:
        return f"{label} 专业需求语料", float(n_used)
    return (name or "目标岗位"), (float(n_jobs) if isinstance(n_jobs, (int, float)) else None)


def _data_gap_banner(result: Mapping[str, Any]) -> str:
    """数据不足时在封面正面写清"缺什么、怎么补"——不让 未获取 散落在各页角落。"""
    problems: list[str] = []
    notes: list[str] = []
    occ_block = result.get("occupation") or {}
    occ = occ_block.get("occupation") or {}
    demand_status = occ_block.get("demand_status")
    demand_name, demand_n = _demand_label(result)
    coverage = ((result.get("demand_scope") or {}).get("coverage")) or {}
    requested = str(occ.get("requested") or "").strip()
    if occ_block.get("status") == "insufficient_evidence" or demand_status not in (None, "ok"):
        if isinstance(demand_n, (int, float)) and demand_n:
            notes.append(
                f"<b>岗位族未命中，但需求侧有数据</b>："
                + (f"请求的岗位「{C.e(requested)}」未解析到已知岗位族；" if requested else "")
                + f"本轮需求改用 <b>{C.e(demand_name)}</b> 的 {C.comma(demand_n)} 条语料"
                + (f"（{C.e(coverage.get('keyword_source') or '专业作用域')}）" if coverage else "")
                + "。因此<b>岗位级匹配（Match）不可计算</b>，而<b>专业级供需适配 F 维照常计算</b>。"
                  "要拿岗位级读数，请换成岗位库里的目标岗位"
                  "（`python -m agent.runner --list-occupations`）或提供该岗位 JD 清单。")
        else:
            problems.append(
                f"<b>岗位需求侧未获取</b>：{C.e(occ_block.get('reason') or '目标岗位未能解析到已知岗位族')}"
                + (f"（请求的岗位「{C.e(requested)}」）" if requested else "")
                + "。处理：换成岗位库里的目标岗位（`python -m agent.runner --list-occupations`），"
                  "或提供该岗位的 JD 清单，让系统按原文抽需求。")
    tsi = (result.get("primary_tsi") or {}).get("primary_tsi")
    if tsi is None:
        missing = (result.get("primary_tsi") or {}).get("missing_indicators") or []
        problems.append(
            "<b>Primary TSI 未计算</b>：F 维（供需适配）是定义性维度，缺需求或供给就不出分"
            + (f"（缺指标：{'、'.join(str(m) for m in missing[:8])}）" if missing else "")
            + "。这是口径要求，不是算不出来。")
    coverage = result.get("coverage") or {}
    target = (result.get("supply") or {}).get("target") or {}
    if not target.get("n_courses"):
        problems.append(
            f"<b>目标校课程供给未获取</b>："
            f"{(result.get('plan') or {}).get('school') or ''}"
            f"{(result.get('plan') or {}).get('major') or ''} 在本地的培养方案里没有解析出可核查课程表。"
            "处理：跑一次联网补采（默认开启），或用 `scripts\\audit_course_coverage.py` 核对是否解析漏行。")
    if not problems and not notes:
        return ""
    items = "".join(f"<li>{p}</li>" for p in problems)
    note_items = "".join(f"<li>{n}</li>" for n in notes)
    border = "var(--red)" if problems else "var(--clay)"
    head = "本轮数据不足 · 先看这里" if problems else "本轮口径说明 · 先看这里"
    return (f'<div class="src-block" style="border-left:4px solid {border};margin-top:16px">'
            f"<h3>{head}</h3>"
            + (f"<ul>{items}</ul>" if items else "")
            + (f"<div class=\"sd\">口径提示：</div><ul>{note_items}</ul>" if note_items else "")
            + '<p class="footnote">缺数据的维度在页面里一律显示「未获取」，不补位、不估算、'
            "不用其它专业或其它学校的数据顶替；补到数据后重跑即可自动补齐。</p></div>")


def _door(kind, no, tag, role, scale, obj, value, unit, cta, href, sub=""):
    """三入口门卡（与演示页面 door_card 同一套标记）。"""
    return (
        f'<a class="door {kind}" href="{href}">'
        f'<span class="no">{C.e(no)}</span>'
        f'<div class="tag">{C.e(tag)}</div>'
        f'<div class="role">{C.e(role)}</div>'
        '<div class="rule"></div>'
        f'<div class="scale">{C.e(scale)}</div>'
        f'<div class="obj">{obj}</div>'
        f'<div class="metric"><span class="v">{C.e(value)}</span>'
        f'<span class="u">{C.e(unit)}</span></div>'
        + (f'<div class="door-sub">{sub}</div>' if sub else "")
        + f'<div class="enter"><span>{C.e(cta)}</span><span class="ar">→</span></div></a>'
    )


def _cover(result: Mapping[str, Any], scope: str, banner: str = "") -> str:
    """封面：三入口门卡（宏观-政府 / 中观-专业 / 微观-个人）+ 打分 + 点击跳转。

    必须包在 ``<section class="view on" id="cover">`` 里：演示页的路由脚本按 ``.view``
    切换页面，未包裹的内容会在**每个子页都重复出现**（就是"封面三大模块重复"的原因）。
    """
    plan = result.get("plan") or {}
    primary = result.get("primary_tsi") or {}
    micro = result.get("micro_result") or {}
    occ = ((result.get("occupation") or {}).get("occupation") or {}).get("name") or ""
    subject = f"{plan.get('school') or '（未点名高校）'} · {plan.get('major') or ''}".strip(" ·")
    coverage_pct = C.pct(primary.get("weighted_coverage"), 0)
    gaps = result.get("skill_gaps") or {}
    n_critical = sum(1 for r in (gaps.get("rows") or [])
                     if (r.get("gap") or 0) >= 0.25)
    micro_gaps = (micro.get("gaps") or {})
    micro_top = "—"
    for layer in ("skill", "knowledge", "capability", "practice"):
        top = ((micro_gaps.get(layer) or {}).get("top_gaps") or [])
        if top:
            micro_top = str(top[0].get("item"))
            break
    macro_door = _door(
        "gov", "01", "宏观 · 政府端 Government", "区域", "宏观 / Macro",
        '覆盖高校培养能力供给<br><span class="lt">×</span> 可观察岗位招聘记录',
        C.f2(primary.get("primary_tsi")), "/100 Primary TSI", "查看区域供需", "#macro",
        sub=f'关键缺口 {n_critical} 项 · 证据覆盖 {coverage_pct}%')
    meso_door = _door(
        "tea", "02", "中观 · 专业/教师端 Faculty", "专业", "中观 / Meso",
        f'{C.e(plan.get("school") or "某院校")} · {C.e(plan.get("major") or "某专业")}'
        + (f'<br><span class="lt">×</span> {C.e(occ)}' if occ else ""),
        C.f2((result.get("occupation_match") or {}).get("match_100")),
        "/100 目标岗位适配", "查看培养适配", "#meso",
        sub=f'Primary TSI {C.f2(primary.get("primary_tsi"))} · 证据覆盖 {coverage_pct}%')
    micro_door = _door(
        "stu", "03", "微观 · 个人/学生端 Student", "个人", "微观 / Micro",
        '个人证据画像<br><span class="lt">→</span> 三类缺口与补齐建议',
        (C.f2(micro.get("fit_100")) if micro else len(micro_gaps) or "—"),
        ("/100 个人岗位适配" if micro else "层证据"), "查看能力诊断", "#micro",
        sub=f'证据分层 L{micro.get("sparse_level", "—")} · 最大缺口：{C.e(micro_top)}')
    doors = {"macro": macro_door, "meso": meso_door, "micro": micro_door}
    shown = "".join(doors[k] for k in ("macro", "meso", "micro")) if scope == "all" \
        else doors[scope]
    label = {"macro": "宏观层 · 区域/覆盖高校", "meso": "中观层 · 专业培养适配",
             "micro": "微观层 · 个人证据诊断", "all": "三视角完整版"}[scope]
    return (
        '<section class="view on" id="cover"><div class="wrap"><div class="masthead">'
        '<span class="brand">高教人才供需适配观察</span>'
        f'<span class="idx">{C.e(scope)}</span></div>'
        + (f'<div class="src-block" style="border-left:3px solid var(--clay);margin-top:14px">'
           f'<div class="sd">{banner}</div></div>' if banner else "")
        +
        '<h1><span class="thin">Edu</span>Match</h1>'
        f'<p class="tagline">{C.e(label)}</p>'
        f'<div class="sub"><p class="lead">研究对象 <b>{C.e(subject)}</b>'
        + (f"　目标岗位 <b>{C.e(occ)}</b>" if occ else "")
        + '</p><span class="hint">三个尺度共享同一套 TSI 哲学与证据链；评价对象不同，'
          '分值不直接横向比较 ↓</span></div>'
        + _data_gap_banner(result)
        + f'<div class="doors">{shown}</div>'
        + ('<p class="footnote" style="margin-top:14px">三个尺度的打分口径不同：'
           '宏观是覆盖高校培养能力、中观是本专业培养方案、微观是个人证据；'
           '缺数据的维度一律标「未获取」，不补位、不估算。</p>' if scope == "all" else "")
        + "</div></section>"
    )


_SALARY_BUCKET_ORDER = ["<8k", "8k-15k", "15k-25k", "25k-40k", ">40k"]


def _salary_bucket_order(label: str) -> int:
    """薪资分档按金额从低到高排，而不是按条数排——否则读者看不出分布形状。"""
    key = str(label)
    return _SALARY_BUCKET_ORDER.index(key) if key in _SALARY_BUCKET_ORDER else 99


def _hbar_block(title, rows, note="", cite="", limit=12, keep_missing=False):
    """横条榜（index.html 同款 .hbar）：rows = [(label, value, subtext), ...]。"""
    clean = [(str(l), float(v), str(s)) for l, v, s in rows
             if isinstance(v, (int, float)) and v is not None]
    clean = clean[:limit]
    if not clean and keep_missing:
        # 零数据模板要用：维度必须露出来（显示「未获取」），而不是整块消失。
        clean = [(str(l), 0.0, "未获取") for l, _v, _s in list(rows)[:limit]]
    if not clean:
        return ""
    maxv = max(v for _, v, _ in clean) or 1.0
    bars = "".join(C.hbar(l, v, maxv, s) for l, v, s in clean)
    return ('<div class="src-block"><h3>' + title + (cite or "") + "</h3>"
            + (f'<div class="sd">{note}</div>' if note else "")
            + bars + "</div>")


def school_ledger(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """把「宏观这一层到底用了哪些院校的信息源」拆成一校一行——不合并、不省略。

    数据来自 supply.target_by_school / supply.peer_by_school / coverage /
    benchmark.education_background / auto_harvest.attempts，逐校给出角色、
    可核查课程数、材料类型、就业结果与来源渠道。
    """
    supply = result.get("supply") or {}
    coverage = result.get("coverage") or {}
    bench = result.get("benchmark") or {}
    harvest = result.get("auto_harvest") or {}
    rows: dict[str, dict[str, Any]] = {}

    def slot(name):
        key = str(name or "").strip()
        if not key:
            return None
        return rows.setdefault(key, {"school": key, "roles": [], "n_courses": None,
                                     "materials": {}, "domain": "", "status": "",
                                     "outcome": {}, "n_materials": None,
                                     "harvest_note": ""})

    def add_role(item, role):
        if item is not None and role not in item["roles"]:
            item["roles"].append(role)

    for row in (supply.get("target_by_school") or []):
        item = slot(row.get("school"))
        add_role(item, "目标校")
        if item is not None:
            item["n_courses"] = row.get("n_courses")
    for row in (supply.get("peer_by_school") or []):
        item = slot(row.get("school"))
        add_role(item, "区域同类校")
        if item is not None and item["n_courses"] is None:
            item["n_courses"] = row.get("n_courses")
    for row in (coverage.get("schools") or []):
        item = slot(row.get("school"))
        if item is not None and not item["roles"]:
            item["roles"].append("覆盖样本")
    for row in (((bench.get("education_background") or {}).get("entities")) or []):
        item = slot(row.get("entity"))
        add_role(item, "就业结果样本")
        if item is not None:
            item["outcome"] = row
    for attempt in (harvest.get("attempts") or []):
        item = slot(attempt.get("school"))
        add_role(item, "插件补采")
        if item is None:
            continue
        item["domain"] = attempt.get("domain") or item["domain"]
        item["status"] = attempt.get("status") or item["status"]
        item["harvest_note"] = attempt.get("reason") or ""
        if attempt.get("n_materials") is not None:
            item["n_materials"] = attempt.get("n_materials")
    audit = coverage.get("school_audit") or {}
    item = slot(audit.get("school"))
    if item is not None:
        for material, entry in (audit.get("materials") or {}).items():
            item["materials"][material] = str((entry or {}).get("state") or "—")
        if not item["status"]:
            item["status"] = "ready" if audit.get("ready") else "partial"
    # 区域同类校的材料口径：课程池（培养方案）。只有真正入库课程才算已覆盖。
    for name, item in rows.items():
        if "区域同类校" in item["roles"] and not item["materials"]:
            item["materials"] = {"培养方案（课程池）": "READY_FOR_ANALYSIS"}
    return rows


def _macro_source_html(result: Mapping[str, Any], refs=None) -> str:
    """宏观信息源台账：逐校列出本期宏观页真正用到的院校与材料。"""
    ledger = school_ledger(result)
    supply = result.get("supply") or {}
    coverage = result.get("coverage") or {}
    plan = result.get("plan") or {}
    if not ledger:
        return ""
    target = str(plan.get("school") or supply.get("target_by_school", [{}])[0].get("school")
                 or coverage.get("school_audit", {}).get("school") or "")
    peers = [n for n, d in ledger.items() if "区域同类校" in d["roles"]]
    rows = ""
    for name, d in sorted(ledger.items(), key=lambda kv: -(kv[1]["n_courses"] or 0)):
        mats = "".join(
            f'<span class="chip">{C.e(m)} · {C.e(st)}</span>'
            for m, st in (d["materials"] or {}).items()) or '<span class="chip na">未获取</span>'
        outcome = d["outcome"] or {}
        bits = []
        if isinstance(outcome.get("placement_rate"), (int, float)):
            bits.append(f'落实率 {C.pct(outcome["placement_rate"])}%')
        if isinstance(outcome.get("further_study_rate"), (int, float)):
            bits.append(f'深造率 {C.pct(outcome["further_study_rate"])}%')
        if isinstance(outcome.get("signing_rate"), (int, float)):
            bits.append(f'签约率 {C.pct(outcome["signing_rate"])}%')
        rest = [r for r in d["roles"] if r != "目标校"] or ["覆盖样本"]
        roles = (('<b>目标校</b> · ' if d["school"] == target else "") + C.e(" / ".join(rest)))
        if d["domain"]:
            source = (f'<span class="path">{C.e(d["domain"])}</span>'
                      + ("（插件补采）" if "插件补采" in d["roles"] else ""))
        elif d["n_courses"]:
            source = '<span class="path">培养方案课程池 · 本地归档</span>'
        elif "就业结果样本" in d["roles"]:
            source = '<span class="path">就业质量报告 · 本地归档</span>'
        else:
            source = '<span class="path">本地归档</span>'
        state = C.e(d["status"] or "—")
        if d.get("harvest_note"):
            state += f' · {C.e(str(d["harvest_note"])[:70])}'
        rows += (f'<tr><td><b>{C.e(name)}</b></td><td>{roles}</td>'
                 f'<td class="n">{d["n_courses"] if d["n_courses"] is not None else "—"}</td>'
                 f'<td>{mats}</td>'
                 f'<td>{" · ".join(bits) or "未获取"}</td>'
                 f'<td>{source}</td>'
                 f'<td>{state}</td></tr>')
    bars = _hbar_block(
        "各校课程供给贡献",
        [(n, d["n_courses"], f'{d["n_courses"]} 门')
         for n, d in sorted(ledger.items(), key=lambda kv: -(kv[1]["n_courses"] or 0))
         if d["n_courses"]],
        note="同一套技能本体下，各校培养方案贡献的可核查课程数；课程池按同名去重前计数。")
    harvest = result.get("auto_harvest") or {}
    progress = harvest.get("region_progress") or {}
    plan_txt = (f'区域补采进度：目标池 {progress.get("pool", "—")} 所，已完成 '
                f'{progress.get("done", "—")} 所，待采 {progress.get("remaining", "—")} 所'
                "（可重复调用累积，直到把区域采全）。" if progress else "")
    head = (f'本期宏观供给来自 <b>{len(ledger)} 所院校</b>：目标校 '
            f'<b>{C.e(target or "未指定")}</b>，区域同类校 {len(peers)} 所'
            + (f'（{C.e("、".join(peers[:12]))}）' if peers else "")
            + '。目标校<b>不合入</b>区域池，避免"一所学校代表一个地区"。'
            + "搜索到 URL ≠ 已覆盖：只有材料到 READY_FOR_ANALYSIS 才计入课程池。"
            + plan_txt)
    return ('<div class="src-block" style="border-left:3px solid var(--ink)">'
            '<h3>宏观信息源 · 覆盖院校台账</h3>'
            f'<div class="sd">{head}</div>'
            '<table class="tbl"><thead><tr><th>院校</th><th>角色</th>'
            '<th class="n">可核查课程</th><th>材料类型 · 状态</th>'
            '<th>就业结果（该校口径）</th><th>来源渠道</th><th>状态</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
            '<p class="footnote">区域池是<b>覆盖高校样本</b>，不是区域总供给；'
            '未覆盖的院校要在下方「全面检索台账」里写明原因与补采计划。</p>'
            + bars + "</div>")


def _cellbar(value, maxv, cls=""):
    """表格内嵌小条（index.html 同款 .cellbar）：缺失显示「未获取」，不画成 0。"""
    if not isinstance(value, (int, float)):
        return f'<div class="cellbar miss{cls}"><i style="width:0%"></i><span>未获取</span></div>'
    w = max(abs(value) / maxv * 100, 0.4) if maxv else 0.4
    miss = " miss" if abs(value) <= 1e-6 else ""
    return (f'<div class="cellbar{cls}{miss}"><i style="width:{w:.1f}%"></i>'
            f"<span>{C.f2(value)}</span></div>")


def _macro_market_html(result: Mapping[str, Any], refs=None) -> str:
    """岗位需求画像：学历结构 / 行业分布 / 技能热度 / 薪资——全是"多条形图"。"""
    occ = result.get("occupation") or {}
    req = occ.get("requirements") or {}
    market = result.get("market") or {}
    name = ((occ.get("occupation") or {}).get("name")) or "目标岗位"
    demand_cite = _cite_for(result, refs, "招聘", "岗位", "HAR", "jobs")
    blocks: list[str] = []
    edu = {k: v for k, v in (req.get("education_distribution") or {}).items()
           if isinstance(v, (int, float))}
    if edu:
        total = sum(v for v in edu.values() if isinstance(v, (int, float))) or 1
        blocks.append(_hbar_block(
            "岗位学历结构", [(k, v, f"{C.comma(v)} 条 · {v / total * 100:.1f}%")
                          for k, v in sorted(edu.items(), key=lambda kv: -(kv[1] or 0))[:8]],
            note=f"目标岗位「{C.e(name)}」在可观察招聘记录中的学历分布。", cite=demand_cite))
    inds = market.get("industries") or []
    if inds:
        blocks.append(_hbar_block(
            "招聘行业分布", [(str(x[0]), x[1], C.comma(x[1])) for x in inds[:10]],
            note="岗位所属行业（平台原始标签，未做人工归类），只作群体热度参照。"))
    rows = _demand_rows(result, limit=10)
    if rows:
        blocks.append(_hbar_block(
            "岗位技能热度 Top 10",
            [(r.get("skill"), r.get("demand"), C.f2(r.get("demand"))) for r in rows],
            note="需求向量强度（0–1）；右侧数值即参与匹配计算的口径。", cite=demand_cite))
    # 薪资画像：来自岗位切片（occupation.requirements）与市场大盘（market）两套口径
    med = req.get("median_salary") if isinstance(req.get("median_salary"), (int, float)) \
        else market.get("median_salary_target")
    p25 = req.get("p25_salary") if isinstance(req.get("p25_salary"), (int, float)) \
        else market.get("salary_p25_target")
    p75 = req.get("p75_salary") if isinstance(req.get("p75_salary"), (int, float)) \
        else market.get("salary_p75_target")
    buckets = req.get("salary_buckets") or market.get("salary_buckets") or {}
    n_salary = req.get("n_with_salary") or market.get("n_salary_target")
    n_daily = req.get("n_daily_excluded") or market.get("n_daily_salary_excluded")
    salary_line = (f'目标岗位月薪中位 <b>{C.comma(med)}</b> 元'
                   + (f'（P25 {C.comma(p25)} / P75 {C.comma(p75)}）' if p25 and p75 else "")
                   + f'；同城基线 {C.comma(market.get("median_salary_baseline"))} 元'
                   + (f'，薪资溢价 {C.f2(market.get("salary_premium"))}×'
                      if isinstance(market.get("salary_premium"), (int, float)) else "")
                   + f'；有月薪数值 {C.comma(n_salary)} 条'
                   + (f'，另有 {C.comma(n_daily)} 条日薪/兼职不并入月薪口径' if n_daily else "")
                   if isinstance(med, (int, float))
                   else "薪资口径：未获取（该批岗位未提供可用月薪数值，不估算）")
    bucket_bar = _hbar_block(
        "月薪分档分布（目标岗位切片）",
        [(k, v, f"{C.comma(v)} 条") for k, v in
         sorted(buckets.items(), key=lambda kv: _salary_bucket_order(kv[0]))],
        note="只统计月薪口径；日薪/兼职岗位已剔除并单独计数，不与月薪混池。",
        keep_missing=True)
    blocks.append('<div class="src-block"><h3>薪资与规模</h3>'
                  f'<div class="sd">{salary_line}</div>'
                  + C.stat_card(C.comma(market.get("n_target_jobs")), "条", "目标岗位语料",
                                f'总语料 {C.comma(market.get("raw_count"))} 条 → 去重 '
                                f'{C.comma(market.get("deduplicated_count"))} 条', ref=demand_cite)
                  + "</div>")
    blocks.append(bucket_bar)
    if not blocks:
        return ""
    return ('<div class="sec-head" style="margin-top:56px"><div>'
            '<div class="eyebrow">需求侧画像 · Demand Profile</div>'
            "<h2 style=\"font-size:clamp(24px,3.4vw,40px)\">岗位要什么：学历 · 行业 · 技能 · 薪资</h2>"
            "</div></div>" + "".join(blocks))


def _macro_benchmark_html(result: Mapping[str, Any], refs=None) -> str:
    """目标校 vs 同类校 vs 市场：三角对照 + 技能级三方对照（多校参与的直接证据）。"""
    bench = result.get("benchmark") or {}
    tri = bench.get("triangle") or {}
    rows = tri.get("rows") or []
    sk = bench.get("skill_benchmark") or {}
    sk_rows = sk.get("rows") or []
    demand_cite = _cite_for(result, refs, "课程", "培养方案", "course")
    if not rows and not sk_rows:
        return ""
    tri_html = ""
    if rows:
        body = "".join(
            f'<tr><td><b>{C.e(r.get("dimension"))}</b></td>'
            f'<td>{C.e(r.get("target"))}</td><td>{C.e(r.get("peer"))}</td>'
            f'<td>{C.e(r.get("market"))}</td></tr>' for r in rows)
        findings = "".join(f"<li>{C.e(f)}</li>" for f in (tri.get("findings") or []))
        tri_html = ('<div class="src-block"><h3>' + C.e(tri.get("label") or "三角对照") + "</h3>"
                    '<table class="tbl"><thead><tr><th>维度</th><th>目标高校</th>'
                    f'<th>同类专业基准</th><th>市场</th></tr></thead><tbody>{body}</tbody></table>'
                    + (f"<ul>{findings}</ul>" if findings else "")
                    + f'<p class="footnote">{C.e(tri.get("note") or "")}</p></div>')
    sk_html = ""
    if sk_rows:
        maxv = max([abs(x.get(k) or 0) for x in sk_rows
                    for k in ("market_demand", "target_supply", "peer_supply")] or [1.0]) or 1.0
        body = "".join(
            f'<tr><td><b>{C.e(r.get("skill"))}</b></td>'
            f'<td>{_cellbar(r.get("market_demand"), maxv, " cdem")}</td>'
            f'<td>{_cellbar(r.get("target_supply"), maxv)}</td>'
            f'<td>{_cellbar(r.get("peer_supply"), maxv)}</td>'
            f'<td class="n">{C.f2(r.get("target_vs_peer"))}</td>'
            f'<td>{C.e(r.get("reading"))}</td></tr>'
            for r in sk_rows[:14])
        sk_html = ('<div class="src-block"><h3>技能级三方对照（多校参与）' + demand_cite + "</h3>"
                   '<div class="sd">同一个技能，在<b>市场</b>、<b>目标校</b>、<b>区域同类校</b>'
                   "三个口径上的读数；差值 = 目标校 − 同类基准（优先解释差异，不排名）。</div>"
                   '<table class="tbl cmp-tbl"><thead><tr><th>技能</th><th>市场需求</th>'
                   "<th>目标校供给</th><th>同类校供给</th><th class=\"n\">差值</th>"
                   f"<th>判定</th></tr></thead><tbody>{body}</tbody></table></div>")
    return ('<div class="sec-head" style="margin-top:56px"><div>'
            '<div class="eyebrow">基准对照 · Benchmark</div>'
            "<h2 style=\"font-size:clamp(24px,3.4vw,40px)\">不是一所学校："
            "目标校 × 同类校 × 市场</h2></div></div>" + tri_html + sk_html)


def _macro_outcome_html(result: Mapping[str, Any]) -> str:
    """多校就业结果对比：把 benchmark 里的每一所院校单独画出来。"""
    bench = result.get("benchmark") or {}
    entities = ((bench.get("education_background") or {}).get("entities")) or []
    if not entities:
        # 该专业在本地就业质量报告里没有分专业行时，维度**不能消失**——
        # 显示「未获取」并写清去哪补，读者才知道是"没有数据"而不是"没做这一项"。
        major = (result.get("plan") or {}).get("major") or "本专业"
        return ('<div class="sec-head" style="margin-top:56px"><div>'
                '<div class="eyebrow">人才结果 · Outcome</div>'
                "<h2 style=\"font-size:clamp(24px,3.4vw,40px)\">同类高校就业结果对比"
                "</h2></div></div>"
                '<div class="src-block"><h3>同类高校就业结果对比</h3>'
                f'<div class="sd">本地就业质量报告里没有「{C.e(major)}」的分专业行'
                "（落实率 / 签约率 / 深造率），本轮<b>未获取</b>——不估算、不用别的专业顶替。"
                "补采目标校与同类校的《毕业生就业质量报告》后可自动补齐这一块。</div>"
                '<p class="footnote">口径：就业结果只接受就业质量报告原文；'
                "招聘数据不参与该维度。</p></div>")
    pr = [(e.get("entity"), (e.get("placement_rate") or 0) * 100,
           f'{C.pct(e.get("placement_rate"))}%') for e in entities
          if isinstance(e.get("placement_rate"), (int, float))]
    fs = [(e.get("entity"), (e.get("further_study_rate") or 0) * 100,
           f'{C.pct(e.get("further_study_rate"))}%') for e in entities
          if isinstance(e.get("further_study_rate"), (int, float))]
    sg = [(e.get("entity"), (e.get("signing_rate") or 0) * 100,
           f'{C.pct(e.get("signing_rate"))}%') for e in entities
          if isinstance(e.get("signing_rate"), (int, float))]
    blocks = [b for b in (_hbar_block("各校毕业去向落实率", pr, limit=14),
                          _hbar_block("各校深造率", fs, limit=14),
                          _hbar_block("各校签约率", sg, limit=14)) if b]
    if not blocks:
        body = "".join(
            f'<tr><td><b>{C.e(x.get("entity"))}</b></td><td>未获取</td>'
            f'<td>未获取</td><td>未获取</td></tr>' for x in entities[:14])
        blocks = ['<div class="src-block"><h3>同类高校就业结果</h3>'
                  '<div class="sd">本轮同类院校就业结果指标未获取（缺失记 null，'
                  '不参与排序、不估算）。</div>'
                  '<table class="tbl"><thead><tr><th>院校</th><th>落实率</th>'
                  f'<th>深造率</th><th>签约率</th></tr></thead><tbody>{body}</tbody></table></div>']
    med = bench.get("benchmarks") or {}
    note = "；".join(
        f'{k} 中位数 {C.pct((v or {}).get("median"))}%（n={(v or {}).get("n")}）'
        for k, v in med.items() if (v or {}).get("median") is not None) or "基准中位数：未获取"
    return ('<div class="sec-head" style="margin-top:56px"><div>'
            '<div class="eyebrow">人才结果 · Outcome</div>'
            "<h2 style=\"font-size:clamp(24px,3.4vw,40px)\">同类高校就业结果对比</h2>"
            f'</div><div class="boundary"><b>口径</b>：{C.e(note)}。'
            "教育背景指标仅作背景，缺失显示 null、不参与排序。</div></div>"
            + "".join(blocks))


def _macro_policy_html(result: Mapping[str, Any]) -> str:
    """政策与产业方向：只输出关联路径与热度，不做因果断言。"""
    pol = result.get("policy") or {}
    counts = pol.get("industry_counts") or {}
    skills = pol.get("skills_related") or []
    lit = result.get("literature") or {}
    blocks: list[str] = []
    if counts:
        blocks.append(_hbar_block(
            "政策文件产业方向热度",
            [(k, v, f"{v} 份") for k, v in sorted(counts.items(), key=lambda kv: -(kv[1] or 0))[:10]],
            note=f'本地政策库 {C.comma(pol.get("n_documents"))} 份，命中本主题 '
                 f'{C.comma(pol.get("n_matched_documents"))} 份（关键词命中计数，非因果）。'))
    if skills:
        blocks.append('<div class="src-block"><h3>政策文本关联能力方向</h3>'
                      '<div class="chips">' + C.chip_list(skills[:18]) + "</div></div>")
    works = lit.get("top_by_citation") or []
    if works:
        lis = "".join(
            f'<li>{C.e(w.get("title"))}（{C.e(w.get("year"))}，被引 {C.comma(w.get("cited_by_count"))}）'
            + (f' <span class="path">{C.e(w.get("doi"))}</span>' if w.get("doi") else "")
            + "</li>" for w in works[:5])
        blocks.append('<div class="src-block"><h3>方法论学术依据（文献，非本项目一手数据）</h3>'
                      f'<div class="sd">OpenAlex 检索 {lit.get("n_works", 0)} 篇，'
                      f'年份 {C.e((lit.get("year_range") or ["—", "—"])[0])}–'
                      f'{C.e((lit.get("year_range") or ["—", "—"])[1])}；仅用于机制假设的学术依据。</div>'
                      f"<ul>{lis}</ul></div>")
    if not blocks:
        return ""
    return ('<div class="sec-head" style="margin-top:56px"><div>'
            '<div class="eyebrow">机制背景 · Policy &amp; Mechanism</div>'
            "<h2 style=\"font-size:clamp(24px,3.4vw,40px)\">政策与产业方向</h2></div>"
            '<div class="boundary"><b>边界</b>：只输出「政策—产业—岗位—技能—课程」'
            "关联路径，不做因果断言。</div></div>" + "".join(blocks))


def _scale_titles(result: Mapping[str, Any]) -> dict[str, str]:
    """三个尺度子页的大标题：按**本次分析对象**生成，不用死模板句。

    宏观＝「<专业>相关培养能力 · 覆盖 N 所院校 · M 门课程池 × <岗位> 可观察招聘记录 K 条」
    中观＝「<院校> · <专业> 培养方案 · T 门可核查课程 × <岗位> 能力要求」
    微观＝「个人证据画像（L<n>）→ <岗位> 补齐建议」
    """
    plan = result.get("plan") or {}
    supply = result.get("supply") or {}
    micro = result.get("micro_result") or {}
    occ_block = result.get("occupation") or {}
    occ_name, n_jobs = _demand_label(result)
    major = str(plan.get("major") or "").strip() or "本专业"
    school = str(plan.get("school") or "").strip() or "本院校"
    n_pool = supply.get("peer_n_schools") or len(supply.get("peer_by_school") or [])
    n_pool_courses = (supply.get("peer") or {}).get("n_courses")
    n_target_courses = (supply.get("target") or {}).get("n_courses")
    pool_txt = f"覆盖 {n_pool} 所院校" if n_pool else "覆盖高校样本"
    course_txt = (f" · {C.comma(n_pool_courses)} 门课程池"
                  if isinstance(n_pool_courses, (int, float)) else "")
    jobs_txt = f" {C.comma(n_jobs)} 条" if isinstance(n_jobs, (int, float)) else ""
    target_txt = (f" · {C.comma(n_target_courses)} 门可核查课程"
                  if isinstance(n_target_courses, (int, float)) else "")
    level = micro.get("sparse_level")
    macro = (f"{C.e(major)}相关培养能力 · {pool_txt}{course_txt}<br>"
             f'× <span class="thin">{C.e(occ_name)}</span> 可观察岗位招聘记录{jobs_txt}')
    meso = (f"{C.e(school)} · {C.e(major)} 培养方案{target_txt}<br>"
            f'× <span class="thin">{C.e(occ_name)}</span> 能力要求')
    micro_h2 = (f"个人证据画像（L{level}）" if level is not None else "个人证据画像")
    micro_h2 += f'<br>→ <span class="thin">{C.e(occ_name)}</span> 补齐建议'
    return {"macro": macro, "meso": meso, "micro": micro_h2}


def _macro_section(result: Mapping[str, Any], refs=None) -> str:
    if refs is not None:
        refs.set_site("macro")
    demand_cite = _cite_for(result, refs, "招聘", "岗位", "HAR", "jobs")
    supply_cite = _cite_for(result, refs, "课程", "培养方案", "course")
    primary = result.get("primary_tsi") or {}
    occ = result.get("occupation") or {}
    gaps = result.get("skill_gaps") or {}
    coverage = result.get("coverage") or {}
    supply_bundle = result.get("supply") or {}
    peer_info = supply_bundle.get("peer") or {}
    # 区域池按院校拆分（引擎在 supply.peer_by_school 里给出）
    pool_schools = supply_bundle.get("peer_by_school") or coverage.get("schools") or []
    n_pool_schools = supply_bundle.get("peer_n_schools") or (len(pool_schools) or None)
    req = occ.get("requirements") or {}
    adapter = _tree_adapter(result, "macro")      # 宏观 = 区域同类专业课程池（peer）
    rows = _demand_rows(result)
    supply = adapter["supply_scores"]
    # 双向条共用同一刻度：取需求与供给的最大值，避免供给 > 需求时条宽超过 100%
    maxd = max([r.get("demand") or 0 for r in rows]
               + [supply.get(r.get("skill")) or 0 for r in rows] or [1.0]) or 1.0
    duals = "".join(C.dual_bar(r.get("skill"), supply.get(r.get("skill")),
                               r.get("demand") or 0.0, maxd) for r in rows)
    gap_rows = [r for r in (gaps.get("rows") or []) if r.get("status") == "gap"][:12]
    gap_html = "".join(
        f'<tr><td><b>{C.e(r.get("skill"))}</b></td><td class="n">{C.f2(r.get("demand"))}</td>'
        f'<td class="n">{C.f2(r.get("supply"))}</td><td class="n">{C.f2(r.get("gap"))}</td>'
        f'<td>{C.e(r.get("supply_basis") or "—")}</td></tr>' for r in gap_rows)
    return (
        '<section class="view" id="macro"><div class="wrap">'
        '<div class="sec-head"><div><div class="eyebrow">01 — 宏观 · Macro</div>'
        f'<h2>{_scale_titles(result)["macro"]}</h2></div>'
        '<div class="boundary"><b>边界</b>：供给是<b>区域同类专业课程池</b>'
        f"（{peer_info.get('n_courses', '—')} 门，来自多所院校的同类专业培养方案），"
        "不是目标校一所学校；需求是 Observed Job Posting Demand，数量不可直接相除。</div></div>"
        '<div class="stage"><div class="block-black">'
        f'<div class="blk-lbl">综合适配指数 / Primary TSI{supply_cite}</div>'
        f'<div class="mega">{C.f2(primary.get("primary_tsi"))}'
        '<span class="of">&nbsp;/100</span></div>'
        f'<div class="stamp">{C.e(primary.get("band") or "未获取")}</div>'
        '<div class="bm">'
        f'<div class="ln"><span>结构与技能适配 Match（子指标）</span>'
        f'<b>{C.f2((result.get("occupation_match") or {}).get("match_100"))}</b></div>'
        f'<div class="ln"><span>技能结构适配 Skill Fit（子指标）</span>'
        f'<b>{C.f2(_indicator_value(primary, "F1"))}</b></div>'
        f'<div class="ln"><span>参与比对技能</span><b>{len(gaps.get("rows") or [])} 个</b></div>'
        f'<div class="ln"><span>可观察招聘记录</span>'
        f'<b>{C.comma(occ.get("n_jobs"))} 条</b></div>'
        '</div></div>'
        '<div class="block-paper">'
        '<div class="blk-lbl" style="color:var(--red)">岗位需求 vs 课程供给 · 技能强度</div>'
        f"{duals}"
        '<div class="legend"><span><i style="background:#141414"></i>课程供给</span>'
        '<span><i style="background:#d8342a"></i>岗位需求</span></div></div></div>'
        '<div class="stats">'
        + C.stat_card(C.comma(occ.get("n_jobs")), "条", "可观察岗位招聘记录",
                      "Observed Job Posting Demand", ref=demand_cite)
        + C.stat_card(C.f2(primary.get("primary_tsi")), "", "Primary TSI（唯一正式总分）",
                      f"覆盖率 {C.pct(primary.get('weighted_coverage'), 0)}%", ref=supply_cite)
        + C.stat_card(str(len(gaps.get("rows") or [])), "项", "参与比对技能",
                      f"其中缺口 {len(gap_rows)} 项")
        + "</div>"
        # 目标岗位画像（学历/薪资）与覆盖高校：缺失一律显示「未获取」，不省略
        + '<div class="src-block"><h3>目标岗位画像</h3>'
        + '<div class="stats" style="margin-top:0">'
        + C.stat_card(str(len(req.get("education_distribution") or {})) or "—", "档",
                      "学历结构", "、".join(f"{k} {v} 条" for k, v in
                                          (req.get("education_distribution") or {}).items()) or "未获取")
        + C.stat_card(C.f2(req.get("median_salary"), 0), "元", "薪资中位数",
                      C.e(req.get("salary_note") or "未获取"))
        + C.stat_card(str(n_pool_schools or coverage.get("n_schools") or "—"), "所",
                      "区域课程池院校",
                      (f"目标校 {C.e((result.get('plan') or {}).get('school') or '—')} 单列，"
                       "不合入区域池") if n_pool_schools else "覆盖样本，非全市全量")
        + "</div>"
        + (f'<div class="sd" style="margin-top:8px">区域同类专业课程池来自 '
           f'<b>{n_pool_schools} 所院校</b>（逐校明细见下方「宏观信息源 · 覆盖院校台账」）：</div>'
           '<div class="chips">' + "".join(
               f'<span class="chip">{C.e(x.get("school"))} · {x.get("n_courses")} 门</span>'
               for x in pool_schools[:30]) + "</div>"
           if pool_schools else "")
        + (f'<p class="footnote">区域池本地覆盖 {n_pool_schools or "—"} 所院校。'
           '宏观层要回答"区域能供给什么"：若该地区开设此专业的院校更多，'
           '本地未覆盖的部分需按项目规范用插件联网补采（口径见下方「全面检索台账」），'
           '报告只对已覆盖样本下结论。</p>' if (n_pool_schools or 0) < 5 else "")
        + "</div>"
        # —— 以下为宏观信息密度扩展：需求画像 / 多校信息源台账 / 三方基准 /
        #    就业结果对比 / 政策产业方向 —— 全部复用同一套 theme 构件。
        + _macro_market_html(result, refs)
        + _macro_source_html(result, refs)
        + _macro_benchmark_html(result, refs)
        + _macro_outcome_html(result)
        + _macro_policy_html(result)
        + '<div class="tsi-grid">' + C.radar_svg(adapter["tsi_dimensions"])
        + "<div>" + C.indicator_grid(adapter["tsi_indicators"]) + "</div></div>"
        + C.tsi_tree_html(adapter, "招聘语料 Demand 向量")
        + C.alignment_html(adapter, "覆盖高校（本地入库样本）")
        + C.retrieval_ledger_html({"retrieval_ledger": result.get("retrieval_ledger")})
        + (f'<div class="src-block"><h3>关键技能缺口{demand_cite}</h3><table class="tbl"><thead><tr>'
           '<th>技能</th><th class="n">需求</th><th class="n">供给</th>'
           '<th class="n">缺口</th><th>供给依据</th></tr></thead><tbody>'
           + gap_html + "</tbody></table></div>" if gap_html else "")
        + "</div></section>"
    )


def _meso_course_skill_html(result: Mapping[str, Any], refs=None) -> str:
    """中观核心台账：本校课程 × 技能矩阵（哪些课承载了哪些技能，逐门可核查）。"""
    csm = result.get("course_skill_matrix") or {}
    ids = list(csm.get("course_ids") or [])
    skills = list(csm.get("skills") or [])
    matrix = list(csm.get("matrix") or [])
    supply = result.get("supply") or {}
    target = supply.get("target") or {}
    plan = result.get("plan") or {}
    supply_cite = _cite_for(result, refs, "课程", "培养方案", "course")
    blocks: list[str] = []
    credits = csm.get("credits_by_skill") or {}
    if credits:
        blocks.append(_hbar_block(
            "本校课程按技能承载（学分权重 Top 12）",
            [(k, v, f"{C.f2(v)} 学分") for k, v in
             sorted(credits.items(), key=lambda kv: -(kv[1] or 0))[:12]],
            note=f'口径：{C.e(plan.get("school"))}{C.e(plan.get("major"))}培养方案 '
                 f'{target.get("n_courses", "—")} 门可核查课程；技能由课程名/大纲映射，'
                 f'映射 {target.get("n_mapped_courses", "—")} 门。', cite=supply_cite))
    if ids and skills and matrix:
        meta = {c.get("course_id"): c for c in (result.get("courses") or [])}
        rows = []
        for i, cid in enumerate(ids):
            row = matrix[i] if i < len(matrix) else []
            hit = [skills[j] for j, v in enumerate(row)
                   if j < len(skills) and isinstance(v, (int, float)) and v > 0]
            if hit:
                rows.append((cid, hit))
        rows.sort(key=lambda kv: -len(kv[1]))
        body = ""
        for cid, hit in rows[:20]:
            info = meta.get(cid) or {}
            kind = ("实践环节" if info.get("is_practice")
                    else "必修" if info.get("is_required") else "选修/未知")
            src = str(info.get("source_document") or "") or "—"
            body += (f'<tr><td><b>{C.e(info.get("name") or cid)}</b></td>'
                     f'<td class="n">{C.f2(info.get("credits"), 1)}</td>'
                     f'<td>{kind}</td><td>{C.e("、".join(hit[:10]))}</td>'
                     f'<td class="path">{C.e(src.rsplit("/", 1)[-1])}</td></tr>')
        more = ""
        if len(rows) > 20:
            extra = "".join(
                f'<tr><td><b>{C.e((meta.get(cid) or {}).get("name") or cid)}</b></td>'
                f'<td class="n">{C.f2((meta.get(cid) or {}).get("credits"), 1)}</td>'
                f'<td>{"实践环节" if (meta.get(cid) or {}).get("is_practice") else "选修/未知"}</td>'
                f'<td>{C.e("、".join(hit[:10]))}</td><td class="path">—</td></tr>'
                for cid, hit in rows[20:80])
            more = (f'<details class="more"><summary>其余 {len(rows) - 20} 门承载课程明细'
                    "</summary><div class=\"dbody\"><table class=\"tbl\"><thead><tr>"
                    "<th>课程</th><th class=\"n\">学分</th><th>类别</th><th>承载技能</th>"
                    f"<th>来源</th></tr></thead><tbody>{extra}</tbody></table></div></details>")
        unmapped = csm.get("unmapped_courses") or []
        blocks.append(
            '<div class="src-block"><h3>本校课程 × 技能矩阵（逐门可核查）' + supply_cite + "</h3>"
            f'<div class="sd">共 {len(rows)} 门课程在口径内承载至少 1 项技能；'
            f'另有 {len(unmapped)} 门未映射到技能（多为通识/体育/实践类）。'
            "供给强度 = 课程学分权重归一，0 表示口径内未见承载。</div>"
            '<table class="tbl"><thead><tr><th>课程</th><th class="n">学分</th><th>类别</th>'
            f'<th>承载技能</th><th>来源文件</th></tr></thead><tbody>{body}</tbody></table>'
            + (f'<details class="more"><summary>未映射课程（{len(unmapped)} 门）</summary>'
               '<div class="dbody"><div class="chips">'
               + C.chip_list([str(x) for x in unmapped[:80]]) + "</div></div></details>"
               if unmapped else "")
            + more + "</div>")
    if not blocks:
        return ""
    return ('<div class="sec-head" style="margin-top:56px"><div>'
            '<div class="eyebrow">培养方案解剖 · Curriculum</div>'
            "<h2 style=\"font-size:clamp(24px,3.4vw,40px)\">课程与技能的对应关系"
            "</h2></div></div>" + "".join(blocks))


def _meso_peer_bench_html(result: Mapping[str, Any], refs=None) -> str:
    """中观基准：本校 vs 区域同类校，逐技能差异（不是一句话结论）。"""
    bench = result.get("benchmark") or {}
    tri = bench.get("triangle") or {}
    sk = bench.get("skill_benchmark") or {}
    rows = sk.get("rows") or []
    supply = result.get("supply") or {}
    peer_info = supply.get("peer") or {}
    supply_cite = _cite_for(result, refs, "课程", "培养方案", "course")
    parts: list[str] = []
    tri_rows = tri.get("rows") or []
    if tri_rows:
        body = "".join(
            f'<tr><td><b>{C.e(r.get("dimension"))}</b></td><td>{C.e(r.get("target"))}</td>'
            f'<td>{C.e(r.get("peer"))}</td><td>{C.e(r.get("market"))}</td></tr>'
            for r in tri_rows)
        findings = "".join(f"<li>{C.e(f)}</li>" for f in (tri.get("findings") or []))
        parts.append('<div class="src-block"><h3>三角比较 · 目标高校 VS 同类专业基准 VS 市场</h3>'
                     '<table class="tbl"><thead><tr><th>维度</th><th>目标高校</th>'
                     '<th>同类专业基准</th><th>市场</th></tr></thead>'
                     f'<tbody>{body}</tbody></table>'
                     + (f"<ul>{findings}</ul>" if findings else "") + "</div>")
    if rows:
        maxv = max([abs(x.get(k) or 0) for x in rows
                    for k in ("market_demand", "target_supply", "peer_supply")] or [1.0]) or 1.0
        body = "".join(
            f'<tr><td><b>{C.e(r.get("skill"))}</b></td>'
            f'<td>{_cellbar(r.get("market_demand"), maxv, " cdem")}</td>'
            f'<td>{_cellbar(r.get("target_supply"), maxv)}</td>'
            f'<td>{_cellbar(r.get("peer_supply"), maxv)}</td>'
            f'<td class="n">{C.f2(r.get("target_gap"))}</td>'
            f'<td>{C.e(r.get("reading"))}</td></tr>' for r in rows[:14])
        parts.append(
            '<div class="src-block"><h3>逐技能：本校供给 vs 同类校供给 vs 市场需求' + supply_cite + "</h3>"
            f'<div class="sd">同类专业基准取区域课程池（{peer_info.get("n_courses", "—")} 门，'
            "多所院校同类专业培养方案）；缺口 = 需求 − 供给。优先解释差异，不产出排行榜。</div>"
            '<table class="tbl cmp-tbl"><thead><tr><th>技能</th><th>市场需求</th><th>本校供给</th>'
            '<th>同类校供给</th><th class="n">本校缺口</th><th>判定</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')
    if not parts:
        return ""
    return ('<div class="sec-head" style="margin-top:56px"><div>'
            '<div class="eyebrow">同类院校基准 · Benchmark</div>'
            "<h2 style=\"font-size:clamp(24px,3.4vw,40px)\">本校在区域同类专业中的位置"
            "</h2></div></div>" + "".join(parts))


def _meso_section(result: Mapping[str, Any], refs=None) -> str:
    if refs is not None:
        refs.set_site("meso")
    demand_cite = _cite_for(result, refs, "招聘", "岗位", "HAR", "jobs")
    supply_cite = _cite_for(result, refs, "课程", "培养方案", "course")
    primary = result.get("primary_tsi") or {}
    bundle = result.get("supply") or {}
    target = bundle.get("target") or {}
    occ = result.get("occupation") or {}
    job = result.get("occupation_match") or {}
    gaps = result.get("skill_gaps_target") or result.get("skill_gaps") or {}
    conflicts = result.get("conflict_resolution") or {}
    bench = result.get("benchmark") or {}
    adapter = _tree_adapter(result, "meso")
    plan = result.get("plan") or {}
    gap_rows = [r for r in (gaps.get("rows") or []) if r.get("status") == "gap"][:12]
    gap_html = "".join(
        f'<tr><td><b>{C.e(r.get("skill"))}</b></td><td class="n">{C.f2(r.get("demand"))}</td>'
        f'<td class="n">{C.f2(r.get("supply"))}</td><td class="n">{C.f2(r.get("gap"))}</td></tr>'
        for r in gap_rows)
    # 没有缺口行时**不能整块消失**：要么"无显著缺口"，要么"需求证据不足"，都要说清。
    if not gap_html:
        n_rows = len(gaps.get("rows") or [])
        if n_rows:
            gap_html = (f'<tr><td colspan="4">本轮 {n_rows} 项参与比对的技能'
                        "<b>均未出现超过阈值的缺口</b>（供给 ≥ 需求）。</td></tr>")
        else:
            gap_html = ('<tr><td colspan="4">本轮<b>未获取</b>能力缺口：'
                        + C.e(((result.get("occupation") or {}).get("reason"))
                              or "目标岗位需求证据不足（岗位族未解析或语料不覆盖本专业族），"
                                 "没有需求向量就无法算缺口——不记 0、不估算。")
                        + "</td></tr>")
    conflict_html = ""
    if conflicts.get("records"):
        rows = "".join(
            f'<tr><td>{C.e(r.get("changed_skill"))}</td>'
            f'<td class="n">{C.f2(r.get("original_result"))}</td>'
            f'<td class="n">{C.f2(r.get("reconciled_result"))}</td>'
            f'<td>{C.e(r.get("evidence_source"))}</td></tr>' for r in conflicts["records"])
        conflict_html = ('<div class="src-block"><h3>证据冲突消解（只重算受影响技能）</h3>'
                         '<table class="tbl"><thead><tr><th>技能</th><th class="n">原结果</th>'
                         f'<th class="n">修正后</th><th>依据</th></tr></thead>'
                         f"<tbody>{rows}</tbody></table></div>")
    return (
        '<section class="view" id="meso"><div class="wrap">'
        '<div class="sec-head"><div><div class="eyebrow">02 — 中观 · Meso</div>'
        f'<h2>{_scale_titles(result)["meso"]}</h2></div>'
        '<div class="boundary"><b>边界</b>：'
        f'只取 {C.e((result.get("plan") or {}).get("school") or "本校")}'
        f'{C.e((result.get("plan") or {}).get("major") or "本专业")} 培养方案，'
        f'对上 {C.e(((result.get("occupation") or {}).get("occupation") or {}).get("name") or "目标岗位")} '
        "岗位族需求；不混用其它学校或其它专业。</div></div>"
        '<div class="stats">'
        + C.stat_card(C.f2(primary.get("primary_tsi")), "", "Primary TSI（唯一正式总分）",
                      f"覆盖率 {C.pct(primary.get('weighted_coverage'), 0)}%", ref=supply_cite)
        + C.stat_card(C.f2(job.get("match_100")), "", "目标岗位匹配（子指标）",
                      C.e(job.get("band") or "—"))
        + C.stat_card(str(target.get("n_courses", "—")), "门", "本校可核查课程",
                      f"映射 {target.get('n_mapped_courses', '—')} 门")
        + C.stat_card(C.comma(occ.get("n_jobs")), "条", "可观察岗位招聘记录",
                      C.e(occ.get("match_scope") or ""), ref=demand_cite)
        + "</div>"
        '<div class="tsi-grid">' + C.radar_svg(adapter["tsi_dimensions"])
        + "<div>" + C.indicator_grid(adapter["tsi_indicators"]) + "</div></div>"
        + C.tsi_tree_html(adapter, "招聘语料 Demand 向量")
        + C.alignment_html(adapter, f"{C.e(plan.get('school'))}{C.e(plan.get('major'))}专业")
        + C.retrieval_ledger_html({"retrieval_ledger": result.get("retrieval_ledger")})
        + (f'<div class="src-block"><h3>能力缺口明细{demand_cite}</h3><table class="tbl"><thead><tr>'
           '<th>技能</th><th class="n">需求</th><th class="n">本校供给</th>'
           f'<th class="n">缺口</th></tr></thead><tbody>{gap_html}</tbody></table></div>'
           if gap_html else "")
        + _meso_course_skill_html(result, refs)
        + _meso_peer_bench_html(result, refs)
        + conflict_html
        + "</div></section>"
    )


def _micro_gap_chart(micro: Mapping[str, Any]) -> str:
    """个人缺口条形图（index.html 同款 .gap）：需求强度 vs 个人供给位。"""
    demand = ((micro.get("demand_layers") or {}).get("skill")) or {}
    supply = (micro.get("personal_supply") or {}).get("skill") or {}
    if not demand:
        return ('<div class="stage" style="margin-top:24px"><div class="block-paper">'
                '<div class="blk-lbl" style="color:var(--red)">个人缺口 · 岗位需求 vs 个人供给</div>'
                '<div class="sd">本轮<b>未获取</b>个人缺口读数：个人尺度需要本人材料'
                "（已修课程/成绩、项目、实习、作品集）。"
                "补一份个人画像后，这一栏会按技能逐项画出「需求 vs 个人供给」。</div>"
                '<p class="footnote">未提供个人材料时不会用专业基准冒充个人读数；'
                "「没提到」一律记证据不足（≠0 分）。</p></div></div>")
    rows = sorted(((k, v if isinstance(v, (int, float)) else 0.0)
                   for k, v in demand.items()), key=lambda kv: -kv[1])[:10]
    if not rows:
        return ""
    maxv = max(v for _, v in rows) or 1.0
    bars = ""
    for name, d in rows:
        s = supply.get(name)
        note = "" if isinstance(s, (int, float)) else "个人证据未出现（≠0）"
        bars += C.gap_bar(name, d or 0.0, float(s) if isinstance(s, (int, float)) else 0.0,
                          maxv, note)
    return ('<div class="stage" style="margin-top:24px"><div class="block-paper">'
            '<div class="blk-lbl" style="color:var(--red)">个人缺口 · 岗位需求 vs 个人供给</div>'
            f'<div class="gaps">{bars}</div>'
            '<div class="legend"><span><i style="background:#141414"></i>岗位需求强度</span>'
            '<span><i style="background:#d8342a"></i>个人供给 0 · 最紧迫</span></div>'
            '<p class="footnote">竖线 = 个人实测供给位；「个人证据未出现」记证据不足，'
            "不等于个人没有该能力，也不记 0 分——补一份可核查材料即可重算。</p>"
            "</div></div>")


def _micro_layers_html(micro: Mapping[str, Any]) -> str:
    """四层缺口明细：先给汇总（需求/已覆盖/有缺口/证据不足），再按层展开项目名。

    旧版把每一行都铺成「知识 Knowledge | 0.34 | — | — | 未在个人证据中出现」，
    既没有项目名，又重复几十行——这里改为"汇总表 + 可展开明细"。
    """
    gaps = micro.get("gaps") or {}
    layers = [("knowledge", "知识 Knowledge"), ("skill", "技能 Skill"),
              ("capability", "能力 Capability"), ("practice", "实践 Practice")]
    summary_rows: list[str] = []
    details: list[str] = []
    for key, label in layers:
        block = gaps.get(key) or {}
        if block.get("status") != "ok":
            summary_rows.append(
                f'<tr><td><b>{C.e(label)}</b></td><td class="n">—</td><td class="n">—</td>'
                f'<td class="n">—</td><td class="n">—</td>'
                f'<td>证据不足：{C.e(block.get("reason") or "缺需求向量")}</td></tr>')
            continue
        rows = [r for r in (block.get("rows") or []) if isinstance(r, Mapping)]
        covered = [r for r in rows if r.get("status") == "covered"]
        gapped = sorted([r for r in rows if r.get("status") == "gap"],
                        key=lambda r: -(r.get("gap") or 0))
        notev = [r for r in rows if r.get("status") == "not_evidenced"]
        worst = gapped[0] if gapped else None
        summary_rows.append(
            f'<tr><td><b>{C.e(label)}</b></td><td class="n">{len(rows)}</td>'
            f'<td class="n">{len(covered)}</td><td class="n">{len(gapped)}</td>'
            f'<td class="n">{len(notev)}</td>'
            + (f'<td><b>{C.e(worst.get("item"))}</b>（缺口 {C.f2(worst.get("gap"))}）</td>'
               if worst else '<td>未识别到显著缺口</td>') + "</tr>")
        inner: list[str] = []
        if gapped:
            body = "".join(
                f'<tr><td><b>{C.e(r.get("item"))}</b></td>'
                f'<td class="n">{C.f2(r.get("demand"))}</td>'
                f'<td class="n">{C.f2(r.get("supply"))}</td>'
                f'<td class="n">{C.f2(r.get("gap"))}</td></tr>' for r in gapped[:10])
            inner.append('<div class="sd"><b>有缺口</b>（按缺口大小排序，'
                         f'共 {len(gapped)} 项）</div>'
                         '<table class="tbl"><thead><tr><th>项目</th><th class="n">需求</th>'
                         '<th class="n">个人供给</th><th class="n">缺口</th></tr></thead>'
                         f'<tbody>{body}</tbody></table>')
            if len(gapped) > 10:
                inner.append(f'<p class="footnote">其余 {len(gapped) - 10} 项缺口更小，未逐条展开。</p>')
        if covered:
            chips = "".join(f'<span class="chip">{C.e(r.get("item"))} · {C.f2(r.get("supply"))}</span>'
                            for r in covered[:12])
            inner.append(f'<div class="sd" style="margin-top:8px"><b>已覆盖 {len(covered)} 项</b>'
                         "（个人证据足以支撑，不算缺口）</div>"
                         f'<div class="chips">{chips}</div>'
                         + (f'<p class="footnote">其余 {len(covered) - 12} 项已覆盖但需求更低。</p>'
                            if len(covered) > 12 else ""))
        if notev:
            top_nev = notev[:12]
            chips = "".join(
                f'<span class="chip na">{C.e(r.get("item"))} · 需求 {C.f2(r.get("demand"))}</span>'
                for r in top_nev)
            inner.append(f'<div class="sd" style="margin-top:8px"><b>证据不足 {len(notev)} 项</b>'
                         "（个人材料里没有对应证据 → <b>≠0 分</b>，补一份可核查材料即可重算；"
                         "下面按岗位需求强度从高到低列前 "
                         f'{len(top_nev)} 项）</div><div class="chips">{chips}</div>'
                         + (f'<p class="footnote">其余 {len(notev) - len(top_nev)} 项证据不足'
                            '（需求更低，不在本页展开；完整清单在 result.json 的 '
                            'micro_result.gaps 里）。</p>' if len(notev) > len(top_nev) else ""))
        details.append(f'<details class="more"><summary>{C.e(label)} 明细'
                       f'（需求 {len(rows)} 项 · 已覆盖 {len(covered)} · 有缺口 {len(gapped)}）'
                       f'</summary><div class="dbody">{"".join(inner)}</div></details>')
    return ('<table class="tbl"><thead><tr><th>层</th><th class="n">需求项</th>'
            '<th class="n">已覆盖</th><th class="n">有缺口</th><th class="n">证据不足</th>'
            '<th>最紧迫缺口</th></tr></thead>'
            f'<tbody>{"".join(summary_rows)}</tbody></table>' + "".join(details))


def _micro_actions_html(micro: Mapping[str, Any]) -> str:
    """优先行动：量化的分开列，证据不足的按层归并成 chips，避免同一句重复 N 遍。"""
    actions = [a for a in (micro.get("priority_actions") or []) if isinstance(a, Mapping)]
    if not actions:
        return ('<div class="src-block"><h3>优先行动</h3>'
                '<div class="sd">本轮<b>未生成优先行动</b>：需要个人材料才能把缺口排成'
                "可执行清单（补哪门课 / 做哪个项目 / 补哪段实习）。"
                "未提供个人画像时，系统不去猜个人该补什么。</div></div>")
    layer_cn = {"knowledge": "知识", "skill": "技能", "capability": "能力", "practice": "实践"}
    quantified = [a for a in actions if isinstance(a.get("gap"), (int, float))]
    grouped: dict[str, list[str]] = {}
    for a in actions:
        if isinstance(a.get("gap"), (int, float)):
            continue
        grouped.setdefault(str(a.get("layer") or "skill"), []).append(str(a.get("item") or "—"))
    parts = ['<div class="src-block"><h3>优先行动</h3>']
    if quantified:
        body = "".join(
            f'<tr><td>{C.e(layer_cn.get(str(a.get("layer")), a.get("layer")))}</td>'
            f'<td><b>{C.e(a.get("item"))}</b></td><td class="n">{C.f2(a.get("gap"))}</td>'
            f'<td>{C.e(a.get("action"))}</td></tr>' for a in quantified[:8])
        parts.append('<div class="sd">已量化缺口（按缺口大小排序，可直接排优先级）：</div>'
                     '<table class="tbl"><thead><tr><th>层</th><th>项目</th>'
                     f'<th class="n">缺口</th><th>建议动作</th></tr></thead><tbody>{body}</tbody></table>')
    for layer, items in grouped.items():
        cn = layer_cn.get(layer, layer)
        parts.append(
            f'<div class="sd" style="margin-top:10px"><b>{C.e(cn)}层 · 证据不足 {len(items)} 项</b>'
            "（在个人材料里没有出现，<b>不等于 0 分</b>）：补一份可核查材料"
            "（课程成绩 / 课程项目 / 实习 / 作品集）即可重算。</div>"
            '<div class="chips">'
            + "".join(f'<span class="chip na">{C.e(i)}</span>' for i in items[:12]) + "</div>"
            + (f'<p class="footnote">另有 {len(items) - 12} 项证据不足，'
               "完整清单见「四层缺口全量明细」。</p>" if len(items) > 12 else ""))
    parts.append("</div>")
    return "".join(parts)


def _micro_section(result: Mapping[str, Any], micro: Mapping[str, Any], refs=None) -> str:
    if refs is not None:
        refs.set_site("micro")
    supply = micro.get("personal_supply") or {}
    layers = [("knowledge", "知识 Knowledge"), ("skill", "技能 Skill"),
              ("capability", "能力 Capability"), ("practice", "实践 Practice")]
    # 个人供给明细：每层列出已提供的证据项（缺失显示「未获取」）
    supply_rows = ""
    for key, label in layers:
        items = supply.get(key) or {}
        if items:
            chips = "".join(f'<span class="chip">{C.e(k)} · {C.f2(v)}</span>'
                            for k, v in sorted(items.items(), key=lambda kv: -(kv[1] or 0))[:14])
        else:
            chips = '<span class="chip na">未获取（该层没有个人证据）</span>'
        supply_rows += (f'<tr><td><b>{C.e(label)}</b></td>'
                        f'<td>{len(items) or "—"}</td><td>{chips}</td></tr>')
    declared = (micro.get("declared") or {}).get("absences") or []
    declared_html = ("；".join(f'{C.e(a.get("item"))}（自述缺项，≠0 分）' for a in declared[:8])
                     if declared else "无")
    return (
        '<section class="view" id="micro"><div class="wrap">'
        '<div class="sec-head"><div><div class="eyebrow">03 — 微观 · Micro</div>'
        f'<h2>{_scale_titles(result)["micro"]}</h2></div>'
        '<div class="boundary"><b>边界</b>：个人读数不与专业级/区域级数字直接换算。</div></div>'
        '<div class="stats">'
        + C.stat_card(f"L{micro.get('sparse_level', '—')}", "", "证据分层",
                      "Major Baseline" if micro.get("baseline") else "基于个人证据")
        + C.stat_card(C.f2(micro.get("fit_100")), "", "个人岗位适配（子指标）",
                      f"供给口径 {C.e(micro.get('supply_provenance') or '—')}",
                      ref=_cite_for(result, refs, "招聘", "岗位", "HAR", "jobs"))
        + "</div>"
        + ("" if micro else
           '<div class="src-block" style="border-left:3px solid var(--red)">'
           "<h3>本轮没有个人画像输入</h3>"
           '<div class="sd">个人尺度的所有读数（个人缺口、四层明细、优先行动）都需要'
           "<b>本人材料</b>：已修课程与成绩、课程项目、实习/科研、作品集、自述缺项。"
           "补一份即可重算——只给「学校+专业+年级+目标岗位」时退化为 L0 专业基准，"
           "页面会明确标注「不是真实个人能力判断」。</div></div>")
        # 个人证据画像明细（L0–L4）
        + _micro_gap_chart(micro)
        + '<div class="src-block"><h3>个人证据画像明细（L0–L4）</h3>'
        + f'<div class="sd">证据分层 <b>L{C.e(micro.get("sparse_level", "—"))}</b>'
        + ("（Major Baseline 专业基准推断，<b>不是真实个人能力判断</b>）"
           if micro.get("baseline") else "（基于本人提供的证据）")
        + f'；供给口径 {C.e(micro.get("supply_provenance") or "—")}；'
        + f'自述缺项：{declared_html}。</div>'
        + '<div class="chips">'
        + "".join(f'<span class="chip">{C.e(k)} 证据 {v} 项</span>'
                  for k, v in (micro.get("evidence_summary") or {}).items())
        + "</div>"
        + '<div class="sd" style="margin-top:8px">证据分层口径：<b>L0</b> 只有院校/专业/年级/岗位 · '
        '<b>L1</b> +课程 · <b>L2</b> +技能 · <b>L3</b> +项目/能力 · '
        '<b>L4</b> +实习/科研/作品集/结果。层级只决定<b>结论强度</b>，不改变缺口算法；'
        "L0 会退化为专业基准推断并明确标注。</div>"
        + '<table class="tbl"><thead><tr><th>层</th><th class="n">证据项</th>'
        + f'<th>已提供的证据（强度 0–1）</th></tr></thead><tbody>{supply_rows}</tbody></table></div>'
        # 四层缺口全量明细：汇总表 + 可展开的项目级明细
        + '<div class="src-block"><h3>四层缺口全量明细'
        '（Knowledge / Skill / Capability / Practice）</h3>'
        '<div class="sd">先看汇总：每层有多少需求项、多少已覆盖、多少有缺口、多少证据不足；'
        '展开可看到<b>具体项目名</b>。四层分别输出，不合成一个数字。</div>'
        + _micro_layers_html(micro)
        + '<p class="footnote">「证据不足」＝该项目没有出现在个人材料里，'
        '<b>不记 0 分</b>；补一份可核查材料即可重算。'
        '已覆盖＝个人证据足以支撑该项需求。</p></div>'
        + _micro_actions_html(micro)
        + "</div></section>"
    )


def _nav_subs(result: Mapping[str, Any]) -> dict[str, str]:
    """顶栏副标题：写清"这一层这次分析的是什么"，但**必须短到只占一行**。"""
    plan = result.get("plan") or {}
    supply = result.get("supply") or {}
    micro = result.get("micro_result") or {}
    school = str(plan.get("school") or "").strip()
    major = str(plan.get("major") or "").strip()
    # 不做字符串截断（会把校名截成半截），宽度交给 CSS：单行 + 超出省略号。
    n_pool = supply.get("peer_n_schools") or len(supply.get("peer_by_school") or [])
    level = micro.get("sparse_level")
    macro_sub = f"区域 · {n_pool} 所高校" if n_pool else "区域 · 覆盖样本"
    # 必须转义：校名/专业名可能含 < > &（零数据模板的占位就是 <院校>），
    # 不转义会被浏览器当标签吞掉，顶栏直接空一格。
    meso_sub = f"{C.e(school or '本院校')} · {C.e(major or '本专业')}"
    micro_sub = f"证据分层 L{level}" if level is not None else "待补充证据"
    return {"macro": macro_sub, "meso": meso_sub, "micro": micro_sub}


def render_result(
    result: Mapping[str, Any],
    scope: str = "all",
    *,
    micro: Mapping[str, Any] | None = None,
    banner: str = "",
) -> str:
    """渲染任意院校/专业的引擎结果；`scope` 只呈现该层级（all = 三视角）。"""
    if scope not in {"macro", "meso", "micro", "all"}:
        raise ValueError(f"unknown scope: {scope}")
    micro_data = micro or result.get("micro_result") or {}
    refs = C.RefBook(result, site_labels={"macro": "宏观", "meso": "中观",
                                          "micro": "微观", "source": "来源"})
    sections: list[str] = []
    if scope in ("macro", "all"):
        sections.append(_macro_section(result, refs))
    if scope in ("meso", "all"):
        sections.append(_meso_section(result, refs))
    if scope in ("micro", "all"):
        sections.append(_micro_section(result, micro_data, refs))
    # 顶栏只保留层级+极短副标题（单行）；院校/专业/岗位在封面与页头里给全。
    body = (C.nav_html(scope, subs=_nav_subs(result))
            + _cover(result, scope, banner)
            + (_overview_section(result) if scope == "all" else "")
            + "".join(sections) + _source_section(result, refs))
    plan = result.get("plan") or {}
    title = f"EduMatch · {plan.get('school') or ''}{plan.get('major') or ''} · {scope}"
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN" class="oncover">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{C.e(title)}</title>\n<style>{CSS}</style>\n"
        "<noscript><style>.view{display:block !important}"
        "html.oncover .scalenav{display:block}</style></noscript>\n"
        f"</head>\n<body>\n{body}\n<script>{JS}</script>\n</body>\n</html>\n"
    )


def _overview_section(result: Mapping[str, Any]) -> str:
    """独立总览页：三尺度阶梯 + 怎么读这张图 + 三视图对照表（结构对齐演示页面）。"""
    plan = result.get("plan") or {}
    primary = result.get("primary_tsi") or {}
    micro = result.get("micro_result") or {}
    supply = result.get("supply") or {}
    macro_info = supply.get("peer") or {}
    target = supply.get("target") or {}
    coverage = result.get("coverage") or {}
    n_pool = supply.get("peer_n_schools") or len(supply.get("peer_by_school") or [])
    n_school = n_pool or coverage.get("n_schools")
    rungs = [
        ("#macro", "宏观", "100%",
         (f"区域课程池 · {n_school} 所高校" if n_school else "覆盖高校 · 未获取"),
         "区域 · 覆盖高校培养能力 × 可观察岗位招聘记录"),
        ("#meso", "中观", "60%",
         (f"{plan.get('school') or '本院校'} · {target.get('n_courses') or '—'} 门课"),
         "专业 · 一个培养方案 × 一个具体岗位"),
        ("#micro", "微观", "26%",
         f"个人 · 证据分层 L{micro.get('sparse_level', '—')}",
         "个人 · 个人证据 → 三类缺口与补齐"),
    ]
    rungs_html = "".join(
        f'<a class="rung" href="{href}"><span class="r-name">{C.e(name)}</span>'
        f'<span class="r-bar" style="width:{width}"><span>{C.e(sub)}</span></span>'
        f'<span class="r-scope">{C.e(scope_txt)}</span></a>'
        for href, name, width, sub, scope_txt in rungs)
    ladder = ('<div class="wrap">'
              '<div class="eyebrow" style="margin-bottom:16px">三个尺度 · 纵向贯通</div>'
              f'<div class="ladder">{rungs_html}</div></div>')
    legend = (
        '<div class="wrap"><div class="sec-head" style="margin-top:56px;border-top:0">'
        '<div><div class="eyebrow">怎么读这张图</div>'
        '<h2 style="font-size:clamp(24px,3.4vw,40px)">先分清三层'
        '<em style="font-style:normal;color:var(--red)">证据边界</em></h2></div></div>'
        '<div class="sec-note">三种刻度共用一套阅读方式：<b>黑色</b>代表培养侧供给或中性量，'
        '<b>红色</b>代表岗位需求、缺口与「最紧迫」标记。每个数字都挂着来源等级——'
        '<span class="lv lv-a">A</span> 官方报告原文可定位，'
        '<span class="lv lv-b">B</span> 权威文献，'
        '<span class="lv lv-c">C</span> 平台语料测算，'
        '<span class="lv lv-d">D</span> 弱信号/间接，'
        '<span class="lv lv-e">E</span> 本地暂无证据。'
        '凡是确实拿不到的，一律标「<b>未获取</b>」，不补位、不估算。</div>'
        '<div class="src-grid">'
        '<div class="s"><h4>实测</h4><div class="sdesc">Primary TSI、技能缺口、供给/需求向量'
        "全部由 EduMatch 引擎在本地真实数据上跑出，页面数字与 JSON 逐一对应。</div></div>"
        '<div class="s"><h4>口径不串用</h4><div class="sdesc">目标校与区域基准严格分开；'
        "校级口径绝不冒充专业口径；专业级拿不到的写「未获取」。</div></div>"
        '<div class="s"><h4>来源可反查</h4><div class="sdesc">正文上标 [n] 可点，'
        "落到「来源与复现」的条目，并可回跳。</div></div>"
        '<div class="s"><h4>全面检索</h4><div class="sdesc">本地缓存 → 规范源 → 归档 → '
        "采集产物 → 联网插件；未命中要写明原因与补采计划。</div></div>"
        "</div></div>")
    # 三视图对照：三个尺度的供给 + 岗位需求（有数据才画，缺的显示「未获取」）
    macro_sup = {str(r.get("skill")): r.get("supply")
                 for r in clean_rows_quiet(list(macro_info.get("top_skills") or []))}
    meso_sup = {str(r.get("skill")): r.get("supply")
                for r in clean_rows_quiet(list(target.get("top_skills") or []))}
    micro_sup = {str(k): v for k, v in ((micro.get("personal_supply") or {}).get("skill") or {}).items()}
    demand = {str(r.get("skill")): r.get("demand") for r in (result.get("demand_rows") or [])}
    picked = sorted(demand, key=lambda s: -(demand.get(s) or 0))[:8]
    rows = ""
    if picked:
        maxv = max([abs(v) for v in list(demand.values()) + list(macro_sup.values())
                    + list(meso_sup.values()) + list(micro_sup.values())
                    if isinstance(v, (int, float))] or [1.0]) or 1.0

        def bar(value, cls=""):
            if not isinstance(value, (int, float)):
                return f'<div class="cellbar miss{cls}"><i style="width:0%"></i><span>未获取</span></div>'
            w = max(abs(value) / maxv * 100, 0.4)
            miss = " miss" if abs(value) <= 1e-6 else ""
            return (f'<div class="cellbar{cls}{miss}"><i style="width:{w:.1f}%"></i>'
                    f"<span>{C.f2(value)}</span></div>")

        rows = "".join(
            f'<tr><td><b>{C.e(s)}</b></td><td>{bar(macro_sup.get(s))}</td>'
            f'<td>{bar(meso_sup.get(s))}</td><td>{bar(micro_sup.get(s))}</td>'
            f'<td>{bar(demand.get(s), " cdem")}</td></tr>' for s in picked)
        compare = (
            '<section class="vsub" id="compare"><div class="wrap">'
            '<div class="sec-head"><div><div class="eyebrow">三视图对照</div>'
            "<h2>同一个技能，在三个尺度上的读数</h2></div>"
            '<div class="boundary"><b>怎么读</b>：黑条＝该尺度的供给，红条＝岗位需求。'
            "一眼看出差距是长在「区域/专业」层面，还是结构性地没有承载。</div></div>"
            '<table class="tbl cmp-tbl"><thead><tr><th>技能</th>'
            "<th>宏观供给<br><small>覆盖高校</small></th>"
            f"<th>中观供给<br><small>{C.e(plan.get('major') or '本专业')}</small></th>"
            "<th>微观供给<br><small>个人证据</small></th>"
            "<th>岗位需求<br><small>可观察招聘记录</small></th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            '<p class="footnote">三侧取自同一套技能本体与匹配规则；'
            "缺失显示「未获取」而不是 0，也不与其它尺度互相换算。</p></div></section>")
    else:
        compare = ('<section class="vsub" id="compare"><div class="wrap">'
                   '<div class="sec-head"><div><div class="eyebrow">三视图对照</div>'
                   "<h2>同一个技能，在三个尺度上的读数</h2></div></div>"
                   '<div class="sec-note">需求向量或供给向量缺失，本轮无法给出三视图对照'
                   "（未获取，不补位）。</div></div></section>")
    return f'<section class="view" id="overview">{ladder}{legend}{compare}</section>'


def _source_section(result: Mapping[str, Any], refs=None) -> str:
    """来源与复现：带交叉引用的编号来源清单 + run_id + 复现命令 + 口径说明。"""
    plan = result.get("plan") or {}
    query = result.get("query") or ""
    occ = ((result.get("occupation") or {}).get("occupation") or {}).get("name") or ""
    command = (f'python -m agent.runner --query "{query}"'
               + (f' --occupation "{occ}"' if occ else "")
               + " --auto-harvest"
               + " --json result.json")
    harvest = result.get("auto_harvest") or {}
    harvest_html = ""
    if harvest:
        rows = "".join(
            f'<tr><td>{C.e(a.get("school"))}</td><td>{C.e(a.get("domain") or "—")}</td>'
            f'<td>{C.e(a.get("entry") or "—")}</td>'
            f'<td>{C.e(a.get("status"))}</td>'
            f'<td>{C.e("、".join(f"{k}{v}" for k, v in (a.get("local_materials") or {}).items() if v) or "—")}</td>'
            f'<td class="n">{a.get("n_materials", 0)}</td>'
            f'<td>{C.e((a.get("reason") or "")[:80])}</td></tr>'
            for a in (harvest.get("attempts") or [])[:20])
        actions = "".join(f"<li>{C.e(a)}</li>" for a in (harvest.get("next_actions") or []))
        harvest_html = (
            '<div class="src-block"><h3>自动补采台账（插件流程）</h3>'
            f'<div class="sd">目标院校 {harvest.get("n_targets", 0)} 所 × 材料类型 '
            f'{C.e("、".join(harvest.get("kinds") or []))}；成功 {harvest.get("n_ok", 0)} 所，'
            f'本地已覆盖跳过联网 {harvest.get("n_local_only", 0)} 所，'
            f'入库材料 {harvest.get("n_materials", 0)} 份，耗时 {harvest.get("elapsed_s", 0)}s。'
            "顺序：<b>先本地 data/source</b>（本地已有该类型就跳过联网）→ "
            "<b>入口 A</b> 全站/栏目 → 没采到就<b>自动转入口 B</b> 承载页直采。"
            '失败逐条记录原因——**不猜域名、不假装采到**。</div>'
            '<table class="tbl"><thead><tr><th>院校</th><th>域名</th><th>入口</th><th>状态</th>'
            f'<th>本地已有材料</th><th class="n">采到材料</th><th>说明</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
            + (f'<div class="sd" style="margin-top:8px"><b>下一步动作</b></div><ul>{actions}</ul>'
               if actions else "")
            + "</div>")
    refs_html = refs.render() if refs is not None else (
        '<div class="src-block"><h3>参考来源</h3>'
        '<div class="sd">本轮没有登记可引用的证据（未获取，不补位）。</div></div>')
    # 数据资产总览：让读者一眼看到"这一版到底动了多少数据"。
    ds = result.get("dataset_summary") or {}
    src = result.get("data_source") or {}
    evidence = list(result.get("evidence") or [])
    by_level: dict[str, int] = {}
    for item in evidence:
        lv = str(item.get("evidence_level") or "E").upper()
        by_level[lv] = by_level.get(lv, 0) + 1
    level_chips = "".join(
        f'<span class="lv lv-{lv.lower()}">{lv}</span> {n} 条 &nbsp;'
        for lv, n in sorted(by_level.items()))
    asset_html = (
        '<div class="src-block"><h3>数据资产总览</h3>'
        '<div class="sd">这一版报告真正用到的本地/采集数据规模与口径：</div>'
        '<div class="stats" style="margin-top:0">'
        + C.stat_card(C.comma(ds.get("n_documents")), "份", "本地文档",
                      f'教育事实 {C.comma(ds.get("n_education_facts"))} 条 · '
                      f'PDF 事实 {C.comma(ds.get("n_pdf_facts"))} 条')
        + C.stat_card(C.comma(ds.get("n_courses")), "门", "课程记录",
                      f'其中本轮采集入库 {C.comma(src.get("harvest_courses"))} 门')
        + C.stat_card(C.comma(ds.get("n_policies")), "份", "政策文件",
                      f'年份 {C.e((ds.get("years") or ["—"])[0])}–'
                      f'{C.e((ds.get("years") or ["—"])[-1])}')
        + C.stat_card(str(len(evidence)), "条", "登记证据",
                      f'口径：{C.e(src.get("mode") or "local")}')
        + "</div>"
        f'<div class="sd" style="margin-top:8px">证据等级分布：{level_chips or "未获取"}</div>'
        + (f'<p class="footnote">{C.e("；".join(src.get("notes") or []))}</p>'
           if src.get("notes") else "")
        + "</div>")
    return (
        '<section class="view" id="source"><div class="wrap">'
        '<div class="sec-head"><div><div class="eyebrow">来源与复现</div>'
        "<h2>每个数字都能反查到来源</h2></div>"
        '<div class="boundary"><b>怎么读</b>：正文里数字后的上标 [n] 与本页条目双向对应，'
        "可点进、可回跳。</div></div>"
        f'<div class="src-block"><h3>复现</h3><div class="sd">运行编号 '
        f'<span class="path">{C.e(result.get("run_id") or "—")}</span></div>'
        f'<div><span class="cmd">{C.e(command)}</span></div>'
        '<p class="footnote">数值只由 analysis/ 确定性函数产出；缺失记 None，不记 0；'
        'Policy / Industry 只输出关联路径，不做因果断言。</p></div>'
        + asset_html
        + refs_html
        + harvest_html
        + "</div></section>"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把引擎结果渲染成既有版式的单文件 HTML")
    ap.add_argument("--result", required=True, help="agent.runner 产出的结果 JSON")
    ap.add_argument("--scope", default="all", choices=["macro", "meso", "micro", "all"])
    ap.add_argument("--micro", default=None, help="含 micro_result 的 JSON（可选）")
    ap.add_argument("--out", default=None, help="单文件输出路径（与 --out-dir 二选一）")
    ap.add_argument("--out-dir", default=None,
                    help="按层级各出一份文件（报告_macro.html / _meso.html / _micro.html / _all.html）；"
                         "**只新增不删除**：补做另一层级时直接再跑一次，已有文件保留")
    ap.add_argument("--prefix", default="报告", help="--out-dir 模式下的文件名前缀")
    args = ap.parse_args(argv)
    if not args.out and not args.out_dir:
        ap.error("请提供 --out 或 --out-dir")
    payload = json.loads(Path(args.result).read_text(encoding="utf-8"))
    result = payload.get("data") or payload
    micro = None
    if args.micro:
        micro_payload = json.loads(Path(args.micro).read_text(encoding="utf-8"))
        micro = (micro_payload.get("micro_result")
                 or (micro_payload.get("data") or {}).get("micro_result")
                 or micro_payload)
    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        scopes = ["macro", "meso", "micro"] if args.scope == "all" else [args.scope]
        if args.scope == "all":
            scopes.append("all")
        for scope in scopes:
            text = render_result(result, scope, micro=micro)
            path = out_dir / f"{args.prefix}_{scope}.html"
            path.write_text(text, encoding="utf-8")
            print(f"[ok] wrote {path}  ({len(text.encode('utf-8'))/1024:.0f} KB, scope={scope})")
        print("[note] 分层文件为**新增**：补做其它层级不会覆盖已有文件。")
        return 0
    html_out = render_result(result, args.scope, micro=micro)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")
    print(f"[ok] wrote {out}  ({len(html_out.encode('utf-8'))/1024:.0f} KB, scope={args.scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
