"""TSI 2.0 - 人才供需适配度（四维）。

Design rules that differ from the legacy TSI v1:

1. missing evidence -> ``value=None`` and removal from the weighted denominator
   (v1 wrote 0, which silently punished data availability);
2. every indicator publishes its formula, data source and evidence level;
3. employment-rate style indicators may only be fed from employment-quality
   reports, never from job-posting volume;
4. the LLM never produces a score; it only explains what this module computed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

from edumatch.evidence import LEVEL_LABEL, MetricValue

DIMENSIONS: dict[str, dict[str, Any]] = {
    "A_人才培养基础": {"weight": 0.20, "name": "人才培养基础"},
    "B_人才培养过程": {"weight": 0.25, "name": "人才培养过程"},
    "C_人才培养结果": {"weight": 0.25, "name": "人才培养结果"},
    "D_市场需求": {"weight": 0.30, "name": "市场需求"},
}


@dataclass(frozen=True)
class IndicatorSpec:
    id: str
    name: str
    dimension: str
    weight: float
    method: str  # ratio | ordinal | ratio_value | semantic | composite | count
    direction: str  # higher_is_better | lower_is_better | neutral
    definition: str
    data_source: str
    raw_field: str
    formula: str
    missing_policy: str = "null，不计入分母，降低该维度置信度"


SPECS: list[IndicatorSpec] = [
    IndicatorSpec("A1", "专业定位清晰度", "A_人才培养基础", 0.25, "semantic", "higher_is_better",
                  "培养目标是否清晰、可检验，并与岗位能力要求对应", "教学质量报告", "training_objective",
                  "S=lexical_alignment(培养目标, 岗位能力集合)×100"),
    IndicatorSpec("A2", "师资结构达标度", "A_人才培养基础", 0.25, "composite", "higher_is_better",
                  "高级职称比例与生师比综合", "教学质量报告", "senior_title_ratio / student_faculty_ratio",
                  "S=0.6·map(高级职称比例)+0.4·map_lower(生师比)"),
    IndicatorSpec("A3", "教学条件与实验资源", "A_人才培养基础", 0.20, "count", "higher_is_better",
                  "实验室、实训基地等可核查条件", "教学质量报告", "training_base_count / lab",
                  "S=map_count(实训基地数, benchmark=3)"),
    IndicatorSpec("A4", "培养条件投入强度", "A_人才培养基础", 0.15, "ratio", "higher_is_better",
                  "经费投入强度", "教学质量报告", "funding",
                  "S=map_ratio(生均/专项经费, 同类高校均值)"),
    IndicatorSpec("A5", "专业与产业方向匹配度", "A_人才培养基础", 0.15, "semantic", "higher_is_better",
                  "专业方向与区域重点产业方向的对应程度", "政策文件+产业目录", "industry_direction",
                  "S=lexical_alignment(专业方向, 产业方向词表)×100"),
    IndicatorSpec("B1", "课程体系覆盖度", "B_人才培养过程", 0.20, "ratio", "higher_is_better",
                  "课程对岗位需求技能的加权覆盖", "培养方案+招聘需求", "course_skill_matrix",
                  "S=matching_score×100"),
    IndicatorSpec("B2", "产业需求响应度", "B_人才培养过程", 0.20, "semantic", "higher_is_better",
                  "课程内容与产业技术需求的对应程度", "培养方案+招聘JD", "course_text_vs_jd",
                  "S=lexical_alignment(课程文本, 岗位技能需求)×100"),
    IndicatorSpec("B3", "课程更新时效性", "B_人才培养过程", 0.15, "ordinal", "higher_is_better",
                  "新兴技术课程出现与培养方案更新频率", "教学质量报告", "curriculum_update",
                  "S=ordinal(每年100/两年85/三年70/更久50/无0)", "无更新记录时 null 而非 0"),
    IndicatorSpec("B4", "实践教学强度", "B_人才培养过程", 0.20, "ratio", "higher_is_better",
                  "实践学分占比", "教学质量报告", "practice_credit_ratio",
                  "S=map_ratio(实践学分占比, 参考基准)"),
    IndicatorSpec("B5", "校企合作深度", "B_人才培养过程", 0.15, "ordinal", "higher_is_better",
                  "企业导师、课程共建、实习基地等真实证据强度", "教学质量报告", "industry_cooperation",
                  "S=ordinal(共建课程+基地>企业导师>仅实习>无)", "仅有表述无数据时记 D 级低置信度"),
    IndicatorSpec("B6", "技能覆盖广度", "B_人才培养过程", 0.10, "ratio", "higher_is_better",
                  "课程覆盖的需求技能比例", "课程-技能矩阵", "breadth.recall",
                  "S=覆盖需求技能数/需求技能总数×100"),
    IndicatorSpec("C1", "毕业去向落实率", "C_人才培养结果", 0.30, "ratio", "higher_is_better",
                  "就业结果指标（仅来自就业质量报告）", "就业质量报告", "placement_rate",
                  "S=map_ratio(落实率, 北京211同类专业中位数)", "严禁用招聘岗位数推算"),
    IndicatorSpec("C2", "就业稳定性", "C_人才培养结果", 0.15, "ratio", "higher_is_better",
                  "签约率", "就业质量报告", "signing_rate", "S=map_ratio(签约率, 基准)"),
    IndicatorSpec("C3", "深造与升学结构", "C_人才培养结果", 0.10, "ratio", "neutral",
                  "深造率（反映培养层次去向结构，非越高越好）", "就业质量报告", "further_study_rate",
                  "S=100−|深造率−同类中位数|/同类中位数×100"),
    IndicatorSpec("C4", "专业相关就业匹配", "C_人才培养结果", 0.20, "composite", "higher_is_better",
                  "岗位与专业的对口程度", "就业质量报告+招聘需求", "major_job_match",
                  "S=0.5·岗位匹配度+0.5·需求加权覆盖"),
    IndicatorSpec("C5", "薪资水平", "C_人才培养结果", 0.10, "ratio", "higher_is_better",
                  "毕业生起薪或薪资区间", "就业质量报告", "salary",
                  "S=map_ratio(起薪, 同类毕业生中位数)", "招聘薪资只用于需求侧薪资溢价"),
    IndicatorSpec("C6", "用人单位评价", "C_人才培养结果", 0.15, "ordinal", "higher_is_better",
                  "用人单位满意度与胜任度评价", "就业质量报告/用人单位调查", "employer_evaluation",
                  "S=ordinal(满意度)", "无调查数据时必须 null"),
    IndicatorSpec("D1", "岗位需求强度", "D_市场需求", 0.20, "ratio", "higher_is_better",
                  "去重后有效岗位规模相对基期", "招聘数据", "effective_count",
                  "S=map_ratio(effective_count, 基期有效岗位数)", "同时报告 raw/dedup/effective 三口径"),
    IndicatorSpec("D2", "技能需求强度", "D_市场需求", 0.20, "ratio", "higher_is_better",
                  "需求技能的加权频率", "招聘数据", "skill_frequency",
                  "S=Σ Demand(s) 的强度分位×100"),
    IndicatorSpec("D3", "新兴技能占比", "D_市场需求", 0.15, "ratio", "higher_is_better",
                  "大模型/Agent/MLOps 等新兴技能在岗位中的占比", "招聘数据", "emerging_skill_share",
                  "S=新兴技能岗位数/有效岗位数×100"),
    IndicatorSpec("D4", "技能增长趋势", "D_市场需求", 0.15, "ratio", "higher_is_better",
                  "技能需求的时间趋势", "招聘数据（≥2期）", "skill_trend",
                  "S=map_ratio(区间增长率, 0)", "只有一期数据时 null"),
    IndicatorSpec("D5", "薪资溢价", "D_市场需求", 0.10, "ratio", "higher_is_better",
                  "关键技能岗位相对市场均值的薪资溢价", "招聘数据", "salary_premium",
                  "S=min(溢价率/0.5,1)×100"),
    IndicatorSpec("D6", "学历门槛", "D_市场需求", 0.10, "ratio_value", "neutral",
                  "岗位学历门槛结构", "招聘数据", "education_requirement",
                  "S=本科占比×100（门槛过低或过高均需说明）"),
    IndicatorSpec("D7", "地区需求集中度", "D_市场需求", 0.10, "ratio", "higher_is_better",
                  "目标城市岗位占全部采集岗位比例", "招聘数据", "city_share",
                  "S=目标城市有效岗位/全部有效岗位×100"),
]

SPEC_BY_ID = {s.id: s for s in SPECS}
SPECS_BY_DIMENSION: dict[str, list[IndicatorSpec]] = {}
for _spec in SPECS:
    SPECS_BY_DIMENSION.setdefault(_spec.dimension, []).append(_spec)


def map_ratio_to_score(
    raw: float | None,
    benchmark: float | None,
    *,
    lower_anchor: float = 0.5,
    upper_anchor: float = 2.0,
    benchmark_score: float = 60.0,
) -> float | None:
    """Piecewise-linear mapping anchored at (lower,40) (1.0,60) (upper,100)."""
    if raw is None or benchmark in (None, 0):
        return None
    ratio = raw / benchmark
    if ratio >= 1:
        span = max(upper_anchor - 1.0, 1e-6)
        score = benchmark_score + (min(ratio, upper_anchor) - 1.0) / span * (100 - benchmark_score)
    else:
        span = max(1.0 - lower_anchor, 1e-6)
        floor = benchmark_score - 20
        score = benchmark_score - (1.0 - max(ratio, lower_anchor)) / span * (benchmark_score - floor)
    return round(max(0.0, min(score, 100.0)), 2)


def map_lower_is_better(raw: float | None, benchmark: float | None) -> float | None:
    """For 'smaller is better' metrics such as student-faculty ratio."""
    if raw is None or benchmark in (None, 0):
        return None
    if raw <= benchmark:
        return round(min(100.0, 60 + (benchmark - raw) / benchmark * 80), 2)
    return round(max(0.0, 60 - (raw - benchmark) / benchmark * 60), 2)


def map_ordinal(level: str | None, table: Mapping[str, float]) -> float | None:
    if level is None:
        return None
    return table.get(level)


def _metric(
    spec: IndicatorSpec,
    value: float | None,
    *,
    evidence_level: str = "C",
    confidence: float = 0.6,
    evidence_ids: list[str] | None = None,
    reason: str = "",
    detail: dict[str, Any] | None = None,
    n_observations: int | None = None,
) -> MetricValue:
    if value is None:
        return MetricValue.missing(spec.id, spec.name, reason or "原始数据缺失")
    return MetricValue(
        metric_id=spec.id,
        name=spec.name,
        value=value,
        unit="score",
        status="ok",
        confidence=confidence,
        evidence_level=evidence_level,  # type: ignore[arg-type]
        source_count=len(evidence_ids or []),
        evidence_ids=evidence_ids or [],
        available=True,
        reason=reason,
        n_observations=n_observations,
        detail=detail or {},
    )


def _alignment(semantic: dict[str, Any], key: str) -> tuple[float | None, str, str, float, bool]:
    """读取语义对齐值，并把"低于下限"当作证据不足。

    历史缺陷：TfidfCosineScorer 把低于校准下限的余弦压成 0.0 输出，调用方只判断
    ``is None``，于是把"这段文本不足以判断"误读成"完全不一致"（S1 恒为 0）。
    现在只有 status=ok 且 similarity 非空才计分，否则记 None（不记 0）。
    """
    data = (semantic or {}).get(key) or {}
    value = data.get("similarity")
    status = data.get("status")
    if value is not None and status in (None, "ok"):
        return (float(value), "", str(data.get("evidence_level") or "D"),
                float(data.get("confidence") or 0.5), bool(data.get("proxy_school_level")))
    reason = data.get("notes") or data.get("reason") or "语义信号未达到可用下限，记证据不足（不记 0）"
    return None, str(reason), "E", 0.0, False


def _alignment_detail(semantic: dict[str, Any], key: str) -> dict[str, Any]:
    data = (semantic or {}).get(key) or {}
    keys = ("provider", "status", "cosine", "basis", "method", "covered_skills",
            "missing_skills", "real_zero", "n_demanded", "n_covered")
    return {k: data.get(k) for k in keys if k in data}


def score_indicators(context: dict[str, Any], benchmark: dict[str, float] | None = None) -> list[MetricValue]:
    """Build all 24 indicator values from an analysis context.

    ``context`` keys (all optional - absent keys produce missing metrics):
      teaching, employment, matching, gaps, market, policy, semantic, evidence_ids
    """
    benchmark = benchmark or {}
    out: list[MetricValue] = []
    ctx: dict[str, Any] = context
    ids = ctx.get("evidence_ids", {})

    def ev(*keys: str) -> list[str]:
        found: list[str] = []
        for key in keys:
            found.extend(ids.get(key, []))
        return found

    teaching = ctx.get("teaching") or {}
    employment = ctx.get("employment") or {}
    matching = ctx.get("matching") or {}
    gaps = ctx.get("gaps") or {}
    market = ctx.get("market") or {}
    policy = ctx.get("policy") or {}
    semantic = ctx.get("semantic") or {}

    # ---- A ----
    sim, sim_reason, sim_level, sim_conf, sim_proxy = _alignment(
        semantic, "objective_job_alignment")
    if sim is not None and sim_proxy:
        # 只有校级培养目标代理：作为背景披露，但**不计入 Primary TSI 加权**
        # （避免用弱证据把"培养基础"维压成低分）。
        out.append(MetricValue(
            metric_id="A1", name=SPEC_BY_ID["A1"].name, value=None,
            status="insufficient_evidence", confidence=0.0, evidence_level="D",
            available=False,
            reason="仅有校级培养目标代理（非本专业原文），不计入 Primary TSI，仅作背景披露",
            detail={"proxy_value": round(sim * 100, 2), "proxy_school_level": True,
                    "alignment": _alignment_detail(semantic, "objective_job_alignment")}))
    else:
        out.append(_metric(SPEC_BY_ID["A1"], None if sim is None else round(sim * 100, 2),
                           evidence_level=sim_level, confidence=sim_conf if sim is not None else 0.0,
                           evidence_ids=ev("teaching"),
                           reason="" if sim is not None else sim_reason,
                           detail={"alignment": _alignment_detail(semantic, "objective_job_alignment")}))
    senior = teaching.get("senior_title_ratio")
    sfr = teaching.get("student_faculty_ratio")
    parts = [
        (map_ratio_to_score(senior, benchmark.get("senior_title_ratio", 0.55)), 0.6),
        (map_lower_is_better(sfr, benchmark.get("student_faculty_ratio", 18.0)), 0.4),
    ]
    avail = [(v, w) for v, w in parts if v is not None]
    value = round(sum(v * w for v, w in avail) / sum(w for _, w in avail), 2) if avail else None
    out.append(_metric(SPEC_BY_ID["A2"], value, evidence_level="B", confidence=0.8,
                       evidence_ids=ev("teaching"), reason="" if avail else "缺少师资结构数据",
                       detail={"senior_title_ratio": senior, "student_faculty_ratio": sfr}))
    bases = teaching.get("training_base_count")
    out.append(_metric(SPEC_BY_ID["A3"], None if bases is None else round(min(bases / 3.0, 1.0) * 100, 2),
                       evidence_level="B", confidence=0.75, evidence_ids=ev("teaching"),
                       reason="" if bases is not None else "缺少实验/实训条件数据"))
    funding = teaching.get("funding_per_student")
    out.append(_metric(SPEC_BY_ID["A4"], map_ratio_to_score(funding, benchmark.get("funding_per_student")),
                       evidence_level="B", confidence=0.7, evidence_ids=ev("teaching"),
                       reason="" if funding is not None else "缺少经费投入数据"))
    ind, ind_reason, ind_level, ind_conf, _ind_proxy = _alignment(
        semantic, "major_industry_alignment")
    out.append(_metric(SPEC_BY_ID["A5"], None if ind is None else round(ind * 100, 2),
                       evidence_level=ind_level, confidence=ind_conf if ind is not None else 0.0,
                       evidence_ids=ev("policy", "teaching"),
                       reason="" if ind is not None else ind_reason,
                       detail={"alignment": _alignment_detail(semantic, "major_industry_alignment")}))

    # ---- B ----
    out.append(_metric(SPEC_BY_ID["B1"], matching.get("matching_score_100"),
                       evidence_level="C", confidence=float(matching.get("confidence") or 0.5),
                       evidence_ids=ev("jobs", "courses"),
                       reason="" if matching.get("matching_score_100") is not None else "课程-技能矩阵为空"))
    curr_sim, curr_reason, curr_level, curr_conf, _curr_proxy = _alignment(
        semantic, "curriculum_market_alignment")
    out.append(_metric(SPEC_BY_ID["B2"], None if curr_sim is None else round(curr_sim * 100, 2),
                       evidence_level=curr_level, confidence=curr_conf if curr_sim is not None else 0.0,
                       evidence_ids=ev("courses", "jobs"),
                       reason="" if curr_sim is not None else curr_reason,
                       detail={"alignment": _alignment_detail(semantic, "curriculum_market_alignment")}))
    update_level = teaching.get("curriculum_update_level")
    out.append(_metric(SPEC_BY_ID["B3"], map_ordinal(update_level, {
        "yearly": 100.0, "every_2_years": 85.0, "every_3_years": 70.0,
        "older": 50.0, "unknown": None}),
        evidence_level="C", confidence=0.6, evidence_ids=ev("teaching"),
        reason="" if update_level else "培养方案更新频率无记录"))
    practice = teaching.get("practice_credit_ratio")
    out.append(_metric(SPEC_BY_ID["B4"], map_ratio_to_score(practice, benchmark.get("practice_credit_ratio", 0.25)),
                       evidence_level="B", confidence=0.85, evidence_ids=ev("teaching"),
                       reason="" if practice is not None else "缺少实践学分数据"))
    coop = teaching.get("industry_cooperation_level")
    out.append(_metric(SPEC_BY_ID["B5"], map_ordinal(coop, {
        "joint_course_and_base": 95.0, "enterprise_mentor": 80.0,
        "internship_only": 60.0, "mentioned_only": 45.0, "none": None}),
        evidence_level="D", confidence=0.45, evidence_ids=ev("teaching"),
        reason="" if coop else "校企合作缺少可核查证据"))
    recall = matching.get("recall")
    out.append(_metric(SPEC_BY_ID["B6"], None if recall is None else round(recall * 100, 2),
                       evidence_level="C", confidence=0.65, evidence_ids=ev("courses", "jobs"),
                       reason="" if recall is not None else "需求技能集合为空"))

    # ---- C ----
    place = employment.get("placement_rate")
    out.append(_metric(SPEC_BY_ID["C1"], map_ratio_to_score(place, benchmark.get("placement_rate", 0.92)),
                       evidence_level="A", confidence=0.95, evidence_ids=ev("employment"),
                       reason="" if place is not None else "缺少就业质量报告中的落实率",
                       detail={"raw_rate": place, "source_rule": "仅取自就业质量报告"}))
    sign = employment.get("signing_rate")
    out.append(_metric(SPEC_BY_ID["C2"], map_ratio_to_score(sign, benchmark.get("signing_rate", 0.90)),
                       evidence_level="A", confidence=0.9, evidence_ids=ev("employment"),
                       reason="" if sign is not None else "缺少签约率数据"))
    further = employment.get("further_study_rate")
    med = benchmark.get("further_study_rate")
    out.append(_metric(SPEC_BY_ID["C3"],
                       None if (further is None or not med) else round(max(0.0, 100 - abs(further - med) / med * 100), 2),
                       evidence_level="A", confidence=0.85, evidence_ids=ev("employment"),
                       reason="" if (further is not None and med) else "缺少深造率或同类基准"))
    m4 = matching.get("matching_score_100")
    out.append(_metric(SPEC_BY_ID["C4"], None if m4 is None else round(0.5 * m4 + 0.5 * m4, 2),
                       evidence_level="C", confidence=0.6, evidence_ids=ev("employment", "jobs"),
                       reason="" if m4 is not None else "缺少岗位匹配数据与需求数据"))
    salary = employment.get("salary")
    out.append(_metric(SPEC_BY_ID["C5"], map_ratio_to_score(salary, benchmark.get("salary")),
                       evidence_level="A", confidence=0.8, evidence_ids=ev("employment"),
                       reason="" if salary is not None else "缺少毕业生薪资数据"))
    emp_eval = employment.get("employer_rating")
    out.append(_metric(SPEC_BY_ID["C6"], None if emp_eval is None else round(emp_eval * 100, 2),
                       evidence_level="D", confidence=0.5, evidence_ids=ev("employment"),
                       reason="" if emp_eval is not None else "缺少用人单位调查数据"))

    # ---- D ----
    eff = market.get("effective_count")
    base = market.get("baseline_effective_count")
    out.append(_metric(SPEC_BY_ID["D1"], map_ratio_to_score(eff, base),
                       evidence_level="B", confidence=0.85, evidence_ids=ev("jobs"),
                       reason="" if (eff is not None and base) else "缺少去重后岗位数或基期岗位数",
                       detail={"raw_count": market.get("raw_count"),
                               "deduplicated_count": market.get("deduplicated_count"),
                               "effective_count": eff}))
    d2 = market.get("skill_demand_mean")
    out.append(_metric(SPEC_BY_ID["D2"], None if d2 is None else round(d2 * 100, 2),
                       evidence_level=str(market.get("evidence_level", "D")), confidence=float(market.get("confidence") or 0.5),
                       evidence_ids=ev("jobs"),
                       reason="" if d2 is not None else "缺少技能需求向量"))
    share = market.get("emerging_skill_share")
    out.append(_metric(SPEC_BY_ID["D3"], None if share is None else round(share * 100, 2),
                       evidence_level="B", confidence=0.75, evidence_ids=ev("jobs"),
                       reason="" if share is not None else "缺少新兴技能标注或岗位样本"))
    trend = market.get("skill_trend_growth")
    out.append(_metric(SPEC_BY_ID["D4"], None if trend is None else round(min(max(trend / 0.5, 0), 1) * 100, 2),
                       evidence_level="C", confidence=0.7, evidence_ids=ev("jobs"),
                       reason="" if trend is not None else "技能趋势需要至少两期数据"))
    prem = market.get("salary_premium")
    out.append(_metric(SPEC_BY_ID["D5"], None if prem is None else round(min(prem / 0.5, 1.0) * 100, 2),
                       evidence_level="B", confidence=0.8, evidence_ids=ev("jobs"),
                       reason="" if prem is not None else "缺少按技能分组的薪资数据"))
    edu = market.get("bachelor_share")
    out.append(_metric(SPEC_BY_ID["D6"], None if edu is None else round(edu * 100, 2),
                       evidence_level="B", confidence=0.75, evidence_ids=ev("jobs"),
                       reason="" if edu is not None else "缺少学历要求分布"))
    city = market.get("target_city_share")
    out.append(_metric(SPEC_BY_ID["D7"], None if city is None else round(city * 100, 2),
                       evidence_level="B", confidence=0.8, evidence_ids=ev("jobs"),
                       reason="" if city is not None else "缺少地区分布数据"))

    return out


def dimension_scores(metrics: list[MetricValue]) -> dict[str, dict[str, Any]]:
    by_dim: dict[str, list[MetricValue]] = {}
    for m in metrics:
        spec = SPEC_BY_ID.get(m.metric_id)
        if spec:
            by_dim.setdefault(spec.dimension, []).append(m)
    result: dict[str, dict[str, Any]] = {}
    for dim, meta in DIMENSIONS.items():
        items = by_dim.get(dim, [])
        specs = SPECS_BY_DIMENSION.get(dim, [])
        total_w = sum(s.weight for s in specs)
        avail = [(m, SPEC_BY_ID[m.metric_id].weight) for m in items if m.value is not None]
        avail_w = sum(w for _, w in avail)
        score = (sum(m.value * w for m, w in avail) / avail_w) if avail_w else None
        conf = (sum(m.confidence * w for m, w in avail) / avail_w) if avail_w else 0.0
        result[dim] = {
            "name": meta["name"],
            "weight": meta["weight"],
            "score": None if score is None else round(score, 2),
            "coverage": round(avail_w / total_w, 4) if total_w else 0.0,
            "confidence": round(conf * (avail_w / total_w if total_w else 0), 4),
            "n_available": len(avail),
            "n_total": len(specs),
            "missing_indicators": [m.metric_id for m in items if m.value is None],
        }
    return result


def compute_tsi(metrics: list[MetricValue], *, min_dimension_coverage: float = 0.34) -> dict[str, Any]:
    dims = dimension_scores(metrics)
    usable = {
        d: v for d, v in dims.items()
        if v["score"] is not None and v["coverage"] >= min_dimension_coverage
    }
    excluded = {d: v for d, v in dims.items() if d not in usable}
    total_w = sum(DIMENSIONS[d]["weight"] for d in usable)
    tsi = None
    if usable and total_w > 0:
        tsi = sum(DIMENSIONS[d]["weight"] * v["score"] for d, v in usable.items()) / total_w
    total_dimension_weight = sum(v["weight"] for v in DIMENSIONS.values())
    coverage = round(sum(DIMENSIONS[d]["weight"] for d in usable) / total_dimension_weight, 4)
    confidence = round(
        sum(DIMENSIONS[d]["weight"] * v["confidence"] for d, v in usable.items()) / total_w, 4
    ) if total_w else 0.0
    level_counts: dict[str, int] = {}
    for m in metrics:
        if m.value is not None:
            level_counts[m.evidence_level] = level_counts.get(m.evidence_level, 0) + 1
    n_available = sum(1 for m in metrics if m.value is not None)
    return {
        "tsi_v2": None if tsi is None else round(tsi, 2),
        "band": None if tsi is None else band_of(tsi),
        "dimensions": dims,
        "excluded_dimensions": {d: {"reason": "coverage below threshold", "coverage": v["coverage"]} for d, v in excluded.items()},
        "weighted_coverage": coverage,
        "confidence": confidence,
        "n_available": n_available,
        "n_total": len(SPECS),
        "evidence_level_distribution": level_counts,
        "missing_indicators": [m.metric_id for m in metrics if m.value is None],
        "method_note": "缺失指标不参与加权（不记 0）；维度覆盖率低于阈值时整维剔除并披露。",
    }


def band_of(score: float) -> str:
    if score >= 85:
        return "高度适配"
    if score >= 70:
        return "较适配"
    if score >= 55:
        return "基本适配"
    if score >= 40:
        return "适配不足"
    return "严重错配"


def spec_table() -> list[dict[str, Any]]:
    rows = []
    for spec in SPECS:
        row = asdict(spec)
        row["dimension_weight"] = DIMENSIONS[spec.dimension]["weight"]
        row["absolute_weight"] = round(DIMENSIONS[spec.dimension]["weight"] * spec.weight, 4)
        row["evidence_hint"] = "见 docs/tsi_v2_spec.md"
        rows.append(row)
    return rows


def compare_with_v1(result_v2: dict[str, Any], replay_v1: dict[str, Any]) -> dict[str, Any]:
    v2, v1 = result_v2.get("tsi_v2"), replay_v1.get("tsi_v1")
    return {
        "tsi_v1_replayed": v1,
        "tsi_v1_stated_by_legacy_llm": replay_v1.get("stated_final_tsi"),
        "tsi_v2": v2,
        "delta_v2_minus_v1": None if (v2 is None or v1 is None) else round(v2 - v1, 2),
        "v1_zero_indicators": replay_v1.get("n_zero_scores"),
        "v1_zero_ratio": round(replay_v1.get("n_zero_scores", 0) / max(replay_v1.get("n_indicators", 1), 1), 4),
        "v2_missing_indicators": result_v2.get("missing_indicators"),
        "note": "v1 把 13 个『信息不足』指标记为 0 分；v2 将其置为 null 并披露缺失。",
    }
