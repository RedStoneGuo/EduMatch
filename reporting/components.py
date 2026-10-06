# -*- coding: utf-8 -*-
"""可复用版式构件（EduMatch Core 所有 HTML 交付物的唯一来源）。

包含：转义/数值小工具、图表构件（缺口条/双向条/雷达/横条/数字卡）、
TSI Tree、S1 与覆盖披露、检索台账、导航。
演示页面 `EduMatch-演示页面/_build/build_page.py` 直接 import 这里，
因此**不存在第二套版式**。
"""
from __future__ import annotations

import html
import math
from typing import Any, Mapping


DIM_ORDER = [
    ("F_供需适配", "供需适配", "F"),
    ("S_培养基础", "培养基础", "S"),
    ("O_人才结果", "人才结果", "O"),
    ("M_需求背景", "需求背景", "M"),
]


DIM_OF_INDICATOR = {"F": "F_供需适配", "S": "S_培养基础", "O": "O_人才结果", "M": "M_需求背景"}


DIM_NAME = {"F_供需适配": "供需适配", "S_培养基础": "培养基础", "O_人才结果": "人才结果", "M_需求背景": "需求背景"}


def e(s):
    return html.escape("" if s is None else str(s))


def comma(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return e(n)


def f2(x, d=2):
    try:
        return f"{float(x):.{d}f}"
    except Exception:
        return "—"


def pct(x, d=1):
    try:
        return f"{float(x) * 100:.{d}f}"
    except Exception:
        return "—"


def gap_bar(name, demand, supply, maxv, note=""):
    """缺口条：黑条=岗位需求强度，红=供给为 0 的最紧迫缺口，细竖线=实测供给位。"""
    w = min((demand / maxv * 100) if maxv else 0, 100.0)
    sw = min((supply / maxv * 100) if maxv else 0, 100.0)
    hot = " hot" if (supply or 0) <= 1e-6 else ""
    nt = f'<span class="gnote">{e(note)}</span>' if note else ""
    return (
        '<div class="gap">'
        f'<div class="top"><span class="name">{e(name)}{nt}</span>'
        f'<span class="val">需求 {f2(demand)} · 供给 {f2(supply)}</span></div>'
        f'<div class="track"><div class="fill{hot}" style="width:{w:.1f}%"></div>'
        f'<div class="zero" style="left:{min(sw, 99.4):.1f}%"></div></div>'
        "</div>"
    )


def dual_bar(name, supply, demand, maxv):
    """跨校供给 vs 岗位需求 双向条。"""
    def _w(v):
        # 供给可能是 None（该技能在本口径内没有读数）：画 0 宽 + 显示「—」，
        # 不要伪装成"供给 0"。
        if not isinstance(v, (int, float)) or not maxv:
            return 0.0
        return min(max(v, 0.0) / maxv * 100, 100.0)

    sw, dw = _w(supply), _w(demand)
    return (
        '<div class="dual">'
        f'<div class="dual-name">{e(name)}</div>'
        '<div class="dual-scale">'
        f'<div class="dbar sup"><i style="width:{sw:.1f}%"></i></div>'
        f'<div class="dbar dem"><i style="width:{dw:.1f}%"></i></div>'
        "</div>"
        f'<div class="dual-val"><b>{f2(supply)}</b><span>{f2(demand)}</span></div>'
        "</div>"
    )


def radar_svg(dims, size=320):
    cx = cy = size / 2
    R = size * 0.295
    angs = [-90, 0, 90, 180]
    anchor = {a: ("start" if a == 0 else "end" if a == 180 else "middle") for a in angs}
    off = {a: -6 if a == -90 else 14 if a == 90 else 0 for a in angs}

    def xy(a, r):
        ar = math.radians(a)
        return (cx + r * math.cos(ar), cy + r * math.sin(ar))

    rings = ""
    for fr in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{xy(a, R * fr)[0]:.1f},{xy(a, R * fr)[1]:.1f}" for a in angs)
        rings += f'<polygon points="{pts}" class="rg"></polygon>'

    axes = ""
    for a in angs:
        x, y = xy(a, R)
        axes += f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" class="ax"></line>'

    # 「缺失不记 0」：维度不可用时（None / 非数值）不画点、不连进多边形，标签显示「未获取」。
    raw_vals = [dims.get(k) for k, _, _ in DIM_ORDER]
    avail = [v for v in raw_vals if isinstance(v, (int, float))]
    vals = [float(v) if isinstance(v, (int, float)) else 0.0 for v in raw_vals]
    if len(avail) >= 3:
        poly = " ".join(
            f"{xy(a, R * (v / 100.0))[0]:.1f},{xy(a, R * (v / 100.0))[1]:.1f}"
            for a, v in zip(angs, vals))
    else:
        poly = ""      # 可用维度不足 3 个，画多边形会误导，直接留空
    dots = "".join(
        f'<circle cx="{xy(a, R * (v / 100.0))[0]:.1f}" cy="{xy(a, R * (v / 100.0))[1]:.1f}" '
        f'r="3.4" class="rdot"></circle>'
        for a, v, raw in zip(angs, vals, raw_vals) if isinstance(raw, (int, float))
    )

    labels = ""
    for a, (k, cn, code) in zip(angs, DIM_ORDER):
        raw = dims.get(k)
        v = float(raw) if isinstance(raw, (int, float)) else None
        lx, ly = xy(a, R + 26)
        an = anchor[a]
        vtxt = f2(v) if v is not None else "未获取"
        labels += (
            f'<text x="{lx:.1f}" y="{ly + off[a]:.1f}" text-anchor="{an}" class="rlab">{code} · {cn}</text>'
            f'<text x="{lx:.1f}" y="{ly + off[a] + 17:.1f}" text-anchor="{an}" '
            f'class="rval{" na" if v is None else ""}">{vtxt}</text>'
        )
    note = "" if len(avail) == len(DIM_ORDER) else (
        f'<text x="{cx:.1f}" y="{size - 6:.1f}" text-anchor="middle" class="rlab">'
        f'注：{len(DIM_ORDER) - len(avail)} 个维度证据不足（未获取），不按 0 分计入</text>')
    return (f'<svg viewBox="0 0 {size} {size}" class="radar" role="img">{rings}{axes}'
            f'<polygon points="{poly}" class="rpoly"></polygon>{dots}{labels}{note}</svg>')


def hbar(label, value, maxv, sub=""):
    w = min((value / maxv * 100) if maxv else 0, 100.0)
    return (
        '<div class="hbar">'
        f'<div class="hbar-l">{e(label)}</div>'
        f'<div class="hbar-t"><i style="width:{w:.1f}%"></i></div>'
        f'<div class="hbar-v">{e(sub)}</div>'
        "</div>"
    )


def stat_card(big, unit, label, note="", ref=""):
    return (
        '<div class="stat">'
        f'<div class="stat-v">{e(big)}<span class="stat-u">{e(unit)}</span></div>'
        f'<div class="stat-l">{e(label)}{ref}</div>'
        f'<div class="stat-n">{e(note)}</div>'
        "</div>"
    )


def chip_list(items):
    return "".join(f'<span class="chip">{e(x)}</span>' for x in items)


def indicator_grid(inds):
    out = []
    for m in inds:
        v = m.get("value")
        stat = m.get("status")
        if v is None:
            vtxt, cls = "未获取", "na"
        else:
            vtxt, cls = f2(v), "ok"
        dim = (m.get("id") or "")[:1]
        out.append(
            f'<div class="ind {cls}">'
            f'<div class="ind-h"><span class="ind-id">{e(m.get("id"))}</span><span class="ind-lv">{e(m.get("level"))}</span></div>'
            f'<div class="ind-n">{e(m.get("name"))}</div>'
            f'<div class="ind-v">{vtxt}</div>'
            "</div>"
        )
    return '<div class="inds">' + "".join(out) + "</div>"


def level_badge(lv):
    return f'<span class="lv lv-{e((lv or "E").lower())}">{e(lv or "E")}</span>'


def _n2(v):
    return "—" if v is None else f2(v)


def _skill_tree_rows(rows, demand_source, max_n=10):
    out = []
    for r in sorted(rows, key=lambda x: -(x.get("demand") or 0))[:max_n]:
        out.append(
            '<details class="tnode"><summary><b>' + e(str(r.get("skill"))) + '</b>'
            + f'<span class="tv-mini">需求 {_n2(r.get("demand"))} · 供给 {_n2(r.get("supply"))} · 缺口 {_n2(r.get("gap"))}</span>'
            + '</summary><div class="tleaf">'
            + f'需求证据：{e(demand_source)}<br>'
            + '供给证据：课程—技能矩阵 Supply 向量（供给 0 表示口径内未见承载）<br>'
            + '映射：05 技能本体归一 → 06 匹配模型<br>'
            + f'得分：min(供给,1)×100 = {_n2(None if r.get("supply") is None else min(float(r.get("supply")), 1.0) * 100)}'
            + '</div></details>'
        )
    return "".join(out)


def tsi_tree_html(obj, demand_source):
    """把已算好的 Primary TSI 结构渲染成可逐层展开的 TSI Tree。"""
    dims = obj.get("tsi_dimensions") or {}
    inds = obj.get("tsi_indicators") or []
    supply_lookup = obj.get("supply_scores") or {}
    skills = []
    for r in (obj.get("demand_top") or []):
        supply = r.get("supply")
        if supply is None:
            supply = supply_lookup.get(r.get("skill"))
        gap = r.get("gap")
        if gap is None and supply is not None:
            gap = (r.get("demand") or 0.0) - supply
        skills.append({**r, "supply": supply, "gap": gap})
    by_dim = {}
    for m in inds:
        key = DIM_OF_INDICATOR.get(str(m.get("id") or "")[:1])
        if key:
            by_dim.setdefault(key, []).append(m)
    dim_nodes = ""
    for dim_key in ("F_供需适配", "S_培养基础", "O_人才结果", "M_需求背景"):
        score = dims.get(dim_key)
        if score is None:
            continue
        ind_html = ""
        for m in by_dim.get(dim_key, []):
            leaves = (_skill_tree_rows(skills, demand_source)
                      if m.get("id") in ("F1", "F2", "F3", "F4") and skills else "")
            ind_html += (
                '<details class="tnode"><summary><span class="tid">' + e(str(m.get("id"))) + '</span>'
                + e(str(m.get("name")))
                + f'<span class="tv-mini">{_n2(m.get("value"))}</span></summary>'
                + '<div class="tleaf">证据等级 ' + e(str(m.get("level"))) + ' · 状态 ' + e(str(m.get("status")))
                + (leaves or '') + '</div></details>'
            )
        dim_nodes += (
            '<details class="tnode dim"><summary><b>' + e(DIM_NAME.get(dim_key, dim_key)) + '</b>'
            + f'<span class="tv-mini">{_n2(score)}</span></summary>'
            + '<div class="tleaf">' + ind_html + '</div></details>'
        )
    return (
        '<details class="tsi-tree"><summary><b>TSI Tree</b> · Primary TSI '
        + _n2(obj.get("tsi")) + ' 为什么是这个数？'
        + '<span></span></summary>'
        + '<div class="tleaf root-note">Primary TSI 是唯一正式总分；Match / Skill Fit 是子指标，'
        + '不与其并列。点击「维度 → 指标 → 技能」逐层展开，可看到需求、供给、缺口与各自来源。</div>'
        + dim_nodes + '</details>'
    )


def retrieval_ledger_html(obj, title="全面检索台账"):
    """把"本地缓存 → 规范源 → 归档 → 采集 → 联网"的检索台账画出来。"""
    ledger = obj.get("retrieval_ledger") or {}
    materials = ledger.get("materials") or {}
    if not materials:
        return ""
    rows = ""
    for material, block in materials.items():
        for attempt in (block.get("attempts") or [])[:16]:
            # 必须写清"哪所院校 / 哪个专业 / 哪份文件"——否则一屏都是同名的「培养目标」，
            # 读者无法判断这条到底查的是谁（用户反馈的核心问题）。
            school, major, filename = _split_reference(
                attempt.get("reference") or attempt.get("file") or "")
            rows += (
                f'<tr><td>{e(str(attempt.get("school") or school or "—"))}</td>'
                f'<td>{e(str(attempt.get("major") or major or "—"))}</td>'
                f'<td>{e(str(material))}</td>'
                f'<td>{e(str(attempt.get("kind")))}</td>'
                f'<td>{e(str(attempt.get("state")))}</td>'
                f'<td>{e((attempt.get("reason") or "")[:70])}</td>'
                f'<td class="path">{e(filename or "—")}</td></tr>')
    plans = ""
    for material, block in materials.items():
        plan = block.get("online_plan") or {}
        if plan.get("needed"):
            plans += (f'<p class="footnote"><b>联网补采（{e(str(material))}）</b>：域名 '
                      f'<span class="path">{e(str(plan.get("domain") or "未核实"))}</span>；'
                      f'入口 A {e(str(plan.get("entry_a")))}；入口 B {e(str(plan.get("entry_b")))}</p>')
    summary = ledger.get("summary") or {}
    return (
        '<div class="src-block" style="border-left:3px solid var(--ink)">'
        f'<h3>{e(title)}</h3>'
        f'<div class="sd">共检索 <b>{summary.get("n_attempts", "—")}</b> 条来源记录'
        f'（其中可读正文 {summary.get("n_hits", "—")} 条）；来源覆盖 '
        '本地正文缓存 → 规范一手材料 → 归档 → 采集产物 → 联网插件。'
        '每一条都记录命中/未命中与原因——<b>不因单一来源未命中就断言"没有"</b>。</div>'
        '<table class="tbl"><thead><tr><th>院校</th><th>专业</th><th>材料</th>'
        '<th>来源</th><th>状态</th><th>说明</th><th>文件</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>{plans}</div>'
    )


def _split_reference(reference: str) -> tuple[str, str, str]:
    """从文件路径里拆出（院校, 专业, 文件名）。

    兼容三类路径：
      data/raw/pdf_text/<院校>/<类型>/<年>_<专业>.txt
      data/source/<数据类型>/<院校>/...
      ../AI竞赛数据归档/.../<院校>/...
    拆不出来就返回空串，页面显示「—」，不猜。
    """
    text = str(reference or "").replace("\\", "/")
    if not text:
        return "", "", ""
    filename = text.rsplit("/", 1)[-1]
    parts = [p for p in text.split("/") if p and p not in {".", ".."}]
    roots = {"pdf_text", "source", "harvest", "AI竞赛数据归档", "archive", "归档文本缓存"}
    school = ""
    for index, part in enumerate(parts):
        if part in roots and index + 1 < len(parts):
            for candidate in parts[index + 1:index + 4]:
                if candidate.endswith(("大学", "学院", "学校")):
                    school = candidate
                    break
            if school:
                break
    if not school:
        for part in parts:
            if part.endswith(("大学", "学院", "学校")):
                school = part
                break
    major = ""
    stem = filename.rsplit(".", 1)[0]
    if "_" in stem:
        tail = stem.split("_", 1)[1]
        major = tail.strip()
    return school, major, filename


def alignment_html(obj, subject):
    """培养目标一致性（S1）与高校覆盖状态：把新模型的两条关键结论显式画出来。"""
    al = obj.get("objective_alignment") or {}
    cov = obj.get("coverage") or {}
    parts = []
    if al.get("similarity") is None:
        parts.append(
            '<div class="src-block" style="border-left:3px solid var(--clay)">'
            '<h3>培养目标—岗位能力一致性（S1）：证据不足，不记 0</h3>'
            f'<div class="sd">{e(subject)}未检索到可核查的培养目标原文，'
            'S1 记 <b>insufficient_evidence</b>（不是"完全不匹配"，也不是 0 分）；'
            '专业与岗位的适配由 F1（课程供给 × 岗位需求）给出。补到培养目标正文后可重算。</div></div>'
        )
    elif al.get("proxy_school_level"):
        parts.append(
            '<div class="src-block" style="border-left:3px solid var(--clay)">'
            '<h3>培养目标—岗位能力一致性（S1）：仅有校级代理</h3>'
            f'<div class="sd">{e(subject)}本地未检索到本专业培养目标原文；仅找到<b>校级</b>'
            f'培养目标表述，代理值 <b>{f2(al.get("similarity"))}</b>'
            f'（覆盖 {al.get("n_covered", "—")}/{al.get("n_demanded", "—")} 项需求能力）。'
            '该值<b>不计入 Primary TSI</b>，只作背景披露，不能当作专业级结论；'
            '补到本专业目标原文后可重算。</div></div>'
        )
    else:
        covered = al.get("covered_skills") or []
        missing = al.get("missing_skills") or []
        parts.append(
            '<div class="src-block" style="border-left:3px solid var(--clay)">'
            '<h3>培养目标—岗位能力一致性（S1）</h3>'
            f'<div class="sd">S1 = <b>{f2(al.get("similarity"))}</b>（需求加权覆盖 '
            f'{al.get("n_covered", "—")}/{al.get("n_demanded", "—")} 项）；'
            f'依据 <span class="path">{e(str(al.get("basis") or "—"))}</span>。'
            '度量的是"岗位要求的能力有多少被培养目标明确写出"（单侧覆盖），不是文本余弦。</div>'
            + (f'<div class="chips" style="margin-top:8px">' +
               "".join(f'<span class="chip">已覆盖 · {e(str(s))}</span>' for s in covered[:8]) +
               "".join(f'<span class="chip" style="border-color:var(--red);color:var(--red)">未覆盖 · {e(str(s))}</span>' for s in missing[:6]) +
               '</div>' if covered or missing else '')
            + '</div>'
        )
    audit = cov.get("school_audit") or {}
    if audit:
        materials = audit.get("materials") or {}
        def _state(entry):
            return str((entry or {}).get("state") or "—")

        chips = "".join(
            f'<span class="chip">{e(m)} · {e(_state(d))}</span>'
            for m, d in materials.items())
        parts.append(
            '<div class="src-block"><h3>高校资料覆盖状态机（材料级）</h3>'
            f'<div class="sd">{e(str(audit.get("school") or ""))}：'
            f'可分析材料 {e("、".join(audit.get("ready_materials") or []) or "—")}；'
            f'缺失 {e("、".join(audit.get("missing_materials") or []) or "—")}。'
            '搜索到 URL ≠ 已覆盖，只有到 READY_FOR_ANALYSIS 才算覆盖。</div>'
            f'<div class="chips">{chips}</div></div>'
        )
    return "".join(parts)


def nav_html(scope="all", subs=None, context=""):
    """导航条：**单行**、按层级切换。

    副标题只写"这一层这次分析的是什么"，最多一行、超出省略号（CSS 已锁）。
    顶栏**不再显示**院校/专业/岗位上下文小字——那行会把顶栏顶宽顶高，
    这些信息在封面与各层页头里都有。``context`` 参数仅为兼容旧调用保留，不再渲染。
    """
    def link(href, title, sub):
        return f'<a href="{href}"><b>{title}</b><span>{sub}</span></a>'

    # 默认副标题 = 标准演示页原文（保持既有页面逐字节不变）；通用渲染器会传入中性文案。
    subs = {"macro": "覆盖高校 · 区域", "meso": "北工大 · 专业适配",
            "micro": "个人 · 证据诊断", **(subs or {})}
    links = [link("#cover", "封面", "入口")]
    if scope == "all":
        links.append(link("#overview", "总览", "阶梯与对照"))
    if scope in ("all", "macro"):
        links.append(link("#macro", "宏观", subs["macro"]))
    if scope in ("all", "meso"):
        links.append(link("#meso", "中观", subs["meso"]))
    if scope in ("all", "micro"):
        links.append(link("#micro", "微观", subs["micro"]))
    links.append(link("#source", "来源", "数据与复现"))
    return (
        '<nav class="scalenav"><div class="in">'
        '<a class="sn-brand" href="#cover">EduMatch<b>·</b>观察</a>'
        + '<div class="sn-links">' + "".join(links) + "</div></div></nav>"
    )


class RefBook:
    """通用交叉引用：证据 → 编号来源 [n]，正文上标可点，来源清单可回跳。

    与演示页面 `cite()/backlinks()` 同一套标记与样式（``sup.ref`` / ``ol.refs`` /
    ``div.ru``），但来源来自**任意院校专业的 result["evidence"]**，不含任何案例数据。
    """

    def __init__(self, result, site_labels=None):
        self._items = []
        self._index = {}
        self._cites = []
        self._cur = "main"
        self.site_labels = dict(site_labels or {})
        for item in (result.get("evidence") or []):
            key = str(item.get("evidence_id") or "")
            if not key or key in self._index:
                continue
            self._index[key] = len(self._items) + 1
            self._items.append(item)

    def number(self, key):
        return self._index.get(str(key))

    def set_site(self, site):
        self._cur = site

    def cite(self, key, label=None):
        n = self.number(key)
        if not n:
            return ""
        cid = "c%d" % (len(self._cites) + 1)
        self._cites.append((self._cur, n, cid))
        title = label or f"来源 [{n}]"
        return (f'<sup class="ref"><a href="#ref-{n}" id="{cid}" '
                f'title="{e(title)}">[{n}]</a></sup>')

    def cite_first(self, *keys):
        for key in keys:
            if self.number(key):
                return self.cite(key)
        return ""

    def _backlinks(self, n):
        first = {}
        for site, cn, cid in self._cites:
            if cn == n and site not in first:
                first[site] = cid
        if not first:
            return ""
        links = "".join(f'<a href="#{cid}">{e(self.site_labels.get(site, site))}</a>'
                        for site, cid in first.items())
        return f'<div class="ru">↑ 回到引用处：{links}</div>'

    def render(self):
        if not self._items:
            return ('<div class="src-block"><h3>参考来源</h3>'
                    '<div class="sd">本轮没有登记可引用的证据（未获取，不补位）。</div></div>')
        lis = []
        for i, item in enumerate(self._items, start=1):
            level = e(item.get("evidence_level") or "E")
            lis.append(
                f'<li id="ref-{i}"><span class="rn">[{i}]</span>'
                '<div class="rbody">'
                f'<div class="rt"><span class="lv lv-{level.lower()}">{level}</span> '
                f'{e(item.get("title") or "证据")}</div>'
                f'<div class="rw"><b>出自</b>{e(item.get("locator") or "未获取")}</div>'
                + (f'<div class="rw"><b>原文</b>{e((item.get("quote") or "")[:160])}</div>'
                   if item.get("quote") else "")
                + (f'<div class="rw"><b>年份</b>{e(item.get("year"))}</div>'
                   if item.get("year") else "")
                + self._backlinks(i)
                + "</div></li>")
        return ('<div class="src-block"><h3>参考来源 · 正文序号可点回此处</h3>'
                '<div class="sd">正文里每个数字后的上标 [n] 都可点，落到下面相应条目；'
                "每条末尾的「↑ 回到引用处」再跳回正文，形成双向可追溯。</div>"
                f'<ol class="refs">{"".join(lis)}</ol></div>')
