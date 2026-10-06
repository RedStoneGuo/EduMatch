"""Finding-driven 报告骨架：Finding → Evidence → Model → Action → Simulation。

报告不再只是"指标罗列 + 建议"，而是先把**发现**说清楚，再挂证据、模型、行动与
模拟结果。这里生成的是结构化 findings（同时写进 `result["findings"]`），
Markdown/HTML 只负责渲染同一份数据，保证两版内容一致。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass
class Finding:
    id: str
    title: str
    statement: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    action: str = ""
    simulation: str = ""
    audience: list[str] = field(default_factory=list)
    confidence: float | None = None
    severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def build_findings(result: Mapping[str, Any], *, limit: int = 12) -> list[Finding]:
    """Derive the findings list from an engine result (deterministic, no LLM)."""
    out: list[Finding] = []
    plan = result.get("plan") or {}
    primary = result.get("primary_tsi") or {}
    fit_block = result.get("skill_fit") or {}
    fit = fit_block.get("primary") or fit_block.get("target") or fit_block.get("peer") or {}
    gaps = result.get("skill_gaps") or {}
    occ = result.get("occupation") or {}
    job_match = result.get("occupation_match") or {}
    semantic = result.get("semantic") or {}
    quality = result.get("data_quality") or {}
    mechanism = result.get("mechanism") or {}
    sim = result.get("simulation") or {}
    conflicts = result.get("conflict_resolution") or {}

    # F1 总体适配
    out.append(Finding(
        id="F-tsi",
        title="总体供需适配：Primary TSI",
        statement=(f"{plan.get('school') or '研究对象'}{plan.get('major') or ''} 的 Primary TSI = "
                   f"{_fmt(primary.get('primary_tsi'))}（{primary.get('band') or '—'}），"
                   f"证据覆盖率 {_fmt((primary.get('weighted_coverage') or 0) * 100, 0)}%、"
                   f"置信度 {_fmt(primary.get('confidence'))}。"
                   + (f" 未纳入的指标：{'、'.join(primary.get('missing_indicators') or [])}。"
                      if primary.get("missing_indicators") else "")),
        evidence=[{"type": "metric", "id": "primary_tsi",
                   "note": "由 analysis/primary_tsi.py 确定性计算"}],
        model="Primary TSI = 0.40F + 0.20S + 0.25O + 0.15M；缺失不入分母",
        action="按下方缺口清单确定优先干预方向；不要用单一分数替代结构判断。",
        audience=["政府", "专业负责人"],
        confidence=primary.get("confidence"),
        severity="info",
    ))

    # 关键缺口
    rows = [r for r in (gaps.get("rows") or []) if r.get("status") == "gap"]
    rows.sort(key=lambda r: -(r.get("gap") or 0))
    for index, row in enumerate(rows[:3], start=1):
        skill = row.get("skill")
        out.append(Finding(
            id=f"F-gap-{index}",
            title=f"关键缺口：{skill}",
            statement=(f"目标岗位对「{skill}」的需求强度 {_fmt(row.get('demand'))}，"
                       f"当前供给 {_fmt(row.get('supply'))}，缺口 {_fmt(row.get('gap'))}"
                       f"（供给依据：{row.get('supply_basis') or '已覆盖'}）。"),
            evidence=[{"type": "gap_row", "id": skill,
                       "note": "Fit 与 Gap 取自同一 Supply/Demand 向量"},
                      {"type": "evidence_ids", "id": "jobs/courses",
                       "note": "需求侧：可观察岗位招聘记录；供给侧：课程-技能矩阵"}],
            model="Gap(s) = Demand(s) − Supply(s)；同源向量",
            action=(f"评估将「{skill}」纳入必修或实践环节，并留下可核查产出"
                    "（课程项目 / 实习 / 交付记录）。"),
            simulation=_simulation_for(sim, skill),
            audience=["专业负责人", "政府"],
            severity="high" if (row.get("gap") or 0) >= 0.25 else "medium",
        ))

    # Match 与 TSI 的关系（防止读者把子指标当第二总分）
    if job_match.get("match_100") is not None:
        out.append(Finding(
            id="F-match",
            title="子指标口径：岗位匹配度 vs Primary TSI",
            statement=(f"岗位匹配度 {_fmt(job_match.get('match_100'))}"
                       f"（{job_match.get('band')}）是 Primary TSI 供需适配维的子指标，"
                       f"覆盖需求技能 {job_match.get('n_skills_covered')}/"
                       f"{job_match.get('n_skills_compared')}；它不构成第二个总分。"),
            evidence=[{"type": "sub_indicator", "id": "occupation_match.match_100"}],
            model="Match 与 F1 同为需求加权 Fit，口径不同、不互相换算",
            action="对外只引用 Primary TSI 作为正式结论，Match 仅用于解释供需适配维。",
            audience=["全部"],
            severity="info",
        ))

    # 培养目标一致性（S1）
    alignment = (semantic.get("objective_job_alignment") or {})
    if alignment:
        if alignment.get("similarity") is None:
            out.append(Finding(
                id="F-objective",
                title="培养目标一致性：证据不足（不记 0）",
                statement=("本地未检索到可核查的培养目标原文，S1（培养目标—岗位能力一致性）"
                           "记证据不足，不记 0 分，也不代表「完全不匹配」。"),
                evidence=[{"type": "semantic", "id": "objective_job_alignment",
                           "note": alignment.get("notes") or ""}],
                model="S1 = 需求能力被培养目标文本覆盖的加权比例；无文本 → None",
                action="补充该校该专业培养方案正文（培养目标/毕业要求段落）后可重算。",
                audience=["专业负责人", "政府"],
                severity="medium",
            ))
        else:
            out.append(Finding(
                id="F-objective",
                title="培养目标与岗位能力的一致性",
                statement=(f"培养目标文本覆盖 {alignment.get('n_covered')}/{alignment.get('n_demanded')} "
                           f"项需求能力（需求加权 {_fmt(alignment.get('similarity'))}，"
                           f"依据 {alignment.get('basis')}）。"),
                evidence=[{"type": "semantic", "id": "objective_job_alignment",
                           "note": alignment.get("notes") or ""}],
                model="S1 = 需求能力被培养目标文本覆盖的加权比例（单侧覆盖，非对称余弦）",
                action=("对未被培养目标覆盖的需求能力，检查是「确实没写」还是「写了但用词不同」，"
                        "再决定是否修订培养目标表述。"),
                audience=["专业负责人"],
                severity="info",
            ))

    # 证据冲突
    if conflicts.get("records"):
        out.append(Finding(
            id="F-conflict",
            title="证据冲突已消解（局部重算）",
            statement=(f"发现 {len(conflicts.get('records') or [])} 处引擎结果与高等级原始证据冲突，"
                       f"已按证据修正并只重算受影响技能：{'、'.join(conflicts.get('changed_skills') or [])}。"),
            evidence=[{"type": "conflict_record", "id": r.get("changed_skill"),
                       "note": r.get("mapping_reason")} for r in (conflicts.get("records") or [])[:5]],
            model="Evidence Conflict Resolver：source_evidence_overrides_engine",
            action="复核 Skill Mapping 规则，避免同类冲突重复出现。",
            audience=["专业负责人"],
            severity="medium",
        ))

    # 数据边界
    out.append(Finding(
        id="F-boundary",
        title="数据边界与口径",
        statement=(f"招聘记录口径为 Observed Job Posting Demand；供给为覆盖高校样本，非全市全量。"
                   + (f"缺失指标：{'、'.join(primary.get('missing_indicators') or [])}。"
                      if primary.get("missing_indicators") else "")),
        evidence=[{"type": "data_quality", "id": "quality",
                   "note": "缺失记 None，不记 0"}],
        model="缺失不参与加权；覆盖率与置信度单独披露",
        action="按缺失项补数据（培养目标正文、岗位基期规模、专业级就业结果）。",
        audience=["政府", "专业负责人"],
        severity="info",
    ))

    # 政策—产业—岗位关联路径
    if mechanism.get("paths"):
        out.append(Finding(
            id="F-policy",
            title="政策—产业—岗位—技能关联路径",
            statement=(f"共跟踪 {len(mechanism.get('paths') or [])} 条技能路径；"
                       "输出的是关联路径（association），不是因果结论。"),
            evidence=[{"type": "mechanism", "id": "policy_paths"}],
            model="Policy → Industry → Job → Skill → Education（关联，不做因果断言）",
            action="把政策重点与岗位/课程的共同缺口对齐，作为资源投放参考。",
            audience=["政府"],
            severity="info",
        ))

    out.extend(_micro_findings(result.get("micro_result")))
    return out[:limit]


def _simulation_for(sim: Mapping[str, Any], skill: str) -> str:
    for scenario in (sim.get("scenarios") or []):
        if skill in (scenario.get("supply_delta") or {}):
            return (f"实施「{scenario.get('name')}」预计 Skill Fit "
                    f"{_fmt(scenario.get('fit_100_before'))} → {_fmt(scenario.get('fit_100_after'))}"
                    f"（ΔTSI≈{_fmt(scenario.get('delta_tsi_estimate'))}，近似值）。")
    return ""


def _micro_findings(micro: Mapping[str, Any] | None) -> list[Finding]:
    if not micro:
        return []
    out: list[Finding] = []
    gaps = micro.get("gaps") or {}
    for layer, label in (("skill", "技能缺口"), ("knowledge", "知识缺口"),
                         ("capability", "能力缺口"), ("practice", "实践缺口")):
        block = gaps.get(layer) or {}
        if block.get("status") != "ok":
            continue
        top = block.get("top_gaps") or []
        if not top:
            continue
        names = "、".join(str(r.get("item")) for r in top[:4])
        out.append(Finding(
            id=f"F-micro-{layer}",
            title=f"个人 {label}",
            statement=f"最大{label}：{names}。",
            evidence=[{"type": "personal_evidence", "id": layer}],
            model="Personal Supply → 同一 Fit 主线；分层输出缺口",
            action="按优先级补齐，并留下可核查产出。",
            audience=["学生"],
            severity="medium" if layer in {"skill", "practice"} else "info",
        ))
    return out


def render_findings(findings, limit: int = 4) -> list[str]:
    """Render findings as markdown lines (Finding → Evidence → Model → Action → Simulation)."""
    lines: list[str] = []
    for index, finding in enumerate(findings[:limit], start=1):
        data = finding if isinstance(finding, dict) else finding.to_dict()
        lines.append(f"**发现 {index}｜{data.get('title')}**")
        lines.append("")
        lines.append(f"- **Finding**：{data.get('statement')}")
        if data.get("model"):
            lines.append(f"- **Model**：{data['model']}")
        if data.get("action"):
            lines.append(f"- **Action**：{data['action']}")
        if data.get("simulation"):
            lines.append(f"- **Simulation**：{data['simulation']}")
        lines.append("")
    return lines
