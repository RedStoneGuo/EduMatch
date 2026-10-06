"""Primary TSI - the single formal adaptation score of the Core TSI Engine.

The legacy systems stay readable (``tsi_v1`` = historical_version,
``tsi_v2`` = research_comparison / benchmark_version), but the user-facing
model is one score built from the closed supply/demand/fit/gap mainline:

    Primary TSI = 0.40·供需适配(Fit) + 0.20·培养基础 + 0.25·人才结果 + 0.15·需求背景

Design rules:

1. **One mainline** - the 供需适配 dimension reads the unified ``Fit``/``Gap``
   objects, not a private copy of the matching result.
2. **No double counting** - every indicator declares its base variables and
   transform in :mod:`analysis.metric_graph`; the graph audit must come back
   clean. The legacy C4 ≡ B1 duplication is deliberately *removed* here.
3. **Missing stays missing** - a dimension whose coverage falls below the
   threshold is excluded from the weighted sum (never scored 0) and disclosed.
4. **Evidence carried** - each indicator keeps the legacy metric it was derived
   from (``detail.source_metric``) so the evidence chain and formula stay
   traceable from the executive report all the way down.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from edumatch.evidence import MetricValue

from . import metric_graph, tsi as tsi_v2_mod

VERSION = "primary-3.0"

DIMENSIONS: dict[str, dict[str, Any]] = {
    "F_供需适配": {"weight": 0.40, "name": "供需适配"},
    "S_培养基础": {"weight": 0.20, "name": "培养基础"},
    "O_人才结果": {"weight": 0.25, "name": "人才结果"},
    "M_需求背景": {"weight": 0.15, "name": "需求背景"},
}


@dataclass(frozen=True)
class PrimarySpec:
    id: str
    name: str
    dimension: str
    weight: float
    primitives: tuple[str, ...]
    transform: str
    definition: str
    data_source: str
    formula: str
    direction: str = "higher_is_better"
    source_metric: str | None = None
    missing_policy: str = "null，不计入分母，降低该维度置信度"


SPECS: list[PrimarySpec] = [
    PrimarySpec("F1", "技能适配度", "F_供需适配", 0.45, ("core.fit",), "demand_weighted_fit_scaled_100",
                "专业培养供给与市场需求技能的需求加权适配程度", "课程-技能矩阵+招聘需求",
                "S = Fit × 100，Fit = Σ_s Demand(s)·min(Supply(s),1)/Σ_s Demand(s)"),
    PrimarySpec("F2", "核心技能缺口严重度", "F_供需适配", 0.30, ("core.gap_index",), "inverted_scaled_100",
                "市场重要技能中培养供给不足的严重程度（缺口的反向表达）", "同一 Supply/Demand 向量",
                "S = (1 − min(SkillGapIndex/0.5, 1)) × 100"),
    PrimarySpec("F3", "技能覆盖广度", "F_供需适配", 0.15, ("core.breadth_recall",), "coverage_ratio_scaled_100",
                "需求技能集合被课程覆盖的比例（不加权，反映广度）", "课程-技能矩阵",
                "S = 已覆盖需求技能数 / 需求技能总数 × 100"),
    PrimarySpec("F4", "供给结构强度", "F_供需适配", 0.10, ("core.supply_channels",), "structured_supply_share",
                "被覆盖技能中由必修课或实践环节支撑的比例（结构性而非偶然覆盖）", "课程属性通道",
                "S = 有必修/实践支撑的已覆盖技能数 / 已覆盖技能数 × 100"),
    PrimarySpec("S1", "培养目标—岗位能力一致性", "S_培养基础", 0.35,
                ("semantic.objective_job_alignment",), "semantic_similarity_scaled_100",
                "培养目标原文与岗位能力需求的对应程度", "教学质量报告+招聘需求",
                "S = calibrated_similarity × 100", source_metric="A1"),
    PrimarySpec("S2", "师资结构达标度", "S_培养基础", 0.30,
                ("teaching.senior_title_ratio", "teaching.student_faculty_ratio"), "composite_ratio_map",
                "高级职称比例与生师比综合", "教学质量报告",
                "S = 0.6·map(高级职称比例) + 0.4·map_lower(生师比)", source_metric="A2"),
    PrimarySpec("S3", "实践教学强度", "S_培养基础", 0.20, ("teaching.practice_credit_ratio",), "ratio_map",
                "实践学分占比相对同类基准", "教学质量报告",
                "S = map_ratio(实践学分占比, 参考基准)", source_metric="B4"),
    PrimarySpec("S4", "教学条件与实验资源", "S_培养基础", 0.15, ("teaching.training_base_count",), "threshold_map",
                "实验室/实训基地等可核查条件", "教学质量报告",
                "S = map_count(实训基地数, benchmark=3)", source_metric="A3"),
    PrimarySpec("O1", "毕业去向落实率", "O_人才结果", 0.35, ("employment.placement_rate",), "ratio_map",
                "就业结果指标（仅来自就业质量报告）", "就业质量报告",
                "S = map_ratio(落实率, 同类专业中位数)", source_metric="C1"),
    PrimarySpec("O2", "就业稳定性", "O_人才结果", 0.20, ("employment.signing_rate",), "ratio_map",
                "签约率", "就业质量报告", "S = map_ratio(签约率, 基准)", source_metric="C2"),
    PrimarySpec("O3", "深造结构合理性", "O_人才结果", 0.15, ("employment.further_study_rate",), "distance_to_benchmark",
                "深造率与同类基准的接近程度（非越高越好）", "就业质量报告",
                "S = 100 − |深造率−同类中位数|/同类中位数 × 100", direction="neutral", source_metric="C3"),
    PrimarySpec("O4", "用人单位评价", "O_人才结果", 0.30, ("employment.employer_rating",), "ordinal_satisfaction",
                "用人单位满意度调查", "就业质量报告/用人单位调查",
                "S = 满意度 × 100", source_metric="C6"),
    PrimarySpec("M1", "技能需求强度", "M_需求背景", 0.40, ("market.skill_demand_mean",), "demand_mean_scaled_100",
                "市场需求技能的平均强度（背景变量，反映需求侧热度）", "招聘数据",
                "S = 平均 Demand(skill) × 100", source_metric="D2"),
    PrimarySpec("M2", "新兴技能占比", "M_需求背景", 0.30, ("market.emerging_skill_share",), "share_scaled_100",
                "大模型/Agent/MLOps 等新兴技能在岗位中的占比", "招聘数据",
                "S = 新兴技能岗位数 / 有效岗位数 × 100", source_metric="D3"),
    PrimarySpec("M3", "岗位需求规模", "M_需求背景", 0.15, ("market.effective_count",), "ratio_map",
                "去重有效岗位规模相对基期（单期数据时缺失）", "招聘数据",
                "S = map_ratio(有效岗位数, 基期有效岗位数)", source_metric="D1"),
    PrimarySpec("M4", "薪资溢价", "M_需求背景", 0.15, ("market.salary_premium",), "capped_ratio_scaled_100",
                "关键技能岗位相对市场均值的薪资溢价", "招聘数据",
                "S = min(溢价率/0.5, 1) × 100", source_metric="D5"),
]

SPEC_BY_ID = {s.id: s for s in SPECS}
SPECS_BY_DIMENSION: dict[str, list[PrimarySpec]] = {}
for _spec in SPECS:
    SPECS_BY_DIMENSION.setdefault(_spec.dimension, []).append(_spec)

#: F 维指标直接读核心对象；其余指标沿用 TSI 2.0 的计算结果（同一计算路径）。
LEGACY_SOURCE: dict[str, str] = {s.id: s.source_metric for s in SPECS if s.source_metric}
SPEC_BY_ID_INV: dict[str, PrimarySpec] = {s.source_metric: s for s in SPECS if s.source_metric}


def _metric(
    spec: PrimarySpec,
    value: float | None,
    *,
    evidence_level: str = "C",
    confidence: float = 0.6,
    evidence_ids: list[str] | None = None,
    reason: str = "",
    detail: dict[str, Any] | None = None,
) -> MetricValue:
    if value is None:
        return MetricValue.missing(spec.id, spec.name, reason or "原始数据缺失")
    return MetricValue(
        metric_id=spec.id,
        name=spec.name,
        value=round(float(value), 2),
        unit="score",
        status="ok",
        confidence=confidence,
        evidence_level=evidence_level,  # type: ignore[arg-type]
        source_count=len(evidence_ids or []),
        evidence_ids=list(evidence_ids or []),
        available=True,
        reason=reason,
        detail={"source_metric": spec.source_metric, "formula": spec.formula, **(detail or {})},
    )


def _from_legacy(legacy: Sequence[MetricValue]) -> dict[str, MetricValue]:
    return {m.metric_id: m for m in legacy}


def score_indicators(
    context: dict[str, Any],
    benchmark: dict[str, float] | None = None,
    *,
    legacy_metrics: Sequence[MetricValue] | None = None,
) -> list[MetricValue]:
    """Build the Primary TSI indicator set (16 indicators, four dimensions)."""
    benchmark = benchmark or {}
    legacy = _from_legacy(legacy_metrics if legacy_metrics is not None
                          else tsi_v2_mod.score_indicators(context, benchmark))
    fit = context.get("fit") or {}
    gaps = context.get("gaps") or {}
    matching = context.get("matching") or {}
    supply_channels = context.get("supply_channels") or {}
    ids = context.get("evidence_ids") or {}

    def ev(*keys: str) -> list[str]:
        found: list[str] = []
        for key in keys:
            found.extend(ids.get(key, []))
        return found

    def reuse(legacy_id: str, fallback_reason: str) -> MetricValue:
        source = legacy.get(legacy_id)
        if source is None or source.value is None:
            return MetricValue.missing(SPEC_BY_ID_INV[legacy_id].id,
                                       SPEC_BY_ID_INV[legacy_id].name,
                                       (source.reason if source else "") or fallback_reason)
        spec = SPEC_BY_ID_INV[legacy_id]
        return _metric(spec, source.value, evidence_level=source.evidence_level,
                       confidence=source.confidence, evidence_ids=source.evidence_ids,
                       reason=source.reason,
                       detail={"legacy_metric": legacy_id, "legacy_detail": source.detail})

    out: list[MetricValue] = []
    partial_supply = bool(fit.get("partial_supply"))
    conf_scale = 0.5 if partial_supply else 1.0

    fit_value = fit.get("fit_100")
    out.append(_metric(
        SPEC_BY_ID["F1"], fit_value,
        evidence_level="C", confidence=round(float(fit.get("confidence") or 0.5) * conf_scale, 4),
        evidence_ids=ev("jobs", "courses"),
        reason="" if fit_value is not None else (
            fit.get("supply_reason") or "目标供给或需求向量缺失，无法计算适配度"),
        detail={"fit": fit.get("fit"), "supply_provenance": fit.get("supply_provenance"),
                "supply_reliability": fit.get("supply_reliability"),
                "partial_supply": partial_supply,
                "n_skills_compared": fit.get("n_skills_compared")},
    ))

    gap_index = gaps.get("skill_gap_index")
    severity = None if gap_index is None else round((1 - min(float(gap_index) / 0.5, 1.0)) * 100, 2)
    out.append(_metric(
        SPEC_BY_ID["F2"], severity,
        evidence_level="C", confidence=round(0.65 * conf_scale, 4), evidence_ids=ev("jobs", "courses"),
        reason="" if severity is not None else "缺口与需求向量不足，无法计算缺口严重度",
        detail={"skill_gap_index": gap_index},
    ))

    rows = fit.get("per_skill") or []
    comparable = [r for r in rows if r.get("demand") is not None and r.get("supply") is not None]
    covered = [r for r in comparable if (r.get("supply") or 0) > 0]
    recall = (len(covered) / len(comparable)) if comparable else matching.get("recall")
    out.append(_metric(
        SPEC_BY_ID["F3"], None if recall is None else round(recall * 100, 2),
        evidence_level="C", confidence=round(0.65 * conf_scale, 4), evidence_ids=ev("jobs", "courses"),
        reason="" if recall is not None else "需求技能集合为空",
        detail={"n_covered": len(covered), "n_comparable": len(comparable)},
    ))

    covered = {r["skill"]: r.get("supply") for r in (fit.get("per_skill") or [])
               if (r.get("supply") or 0) > 0}
    structured = 0
    for skill in covered:
        channel = supply_channels.get(skill) or {}
        if (channel.get("required_courses") or 0) > 0 or (channel.get("practice_courses") or 0) > 0:
            structured += 1
    structure_score = round(structured / len(covered) * 100, 2) if covered else None
    out.append(_metric(
        SPEC_BY_ID["F4"], structure_score,
        evidence_level="D", confidence=round(0.5 * conf_scale, 4), evidence_ids=ev("courses"),
        reason="" if structure_score is not None else "课程通道信息不足，无法判断供给结构",
        detail={"n_covered_skills": len(covered), "n_structured": structured},
    ))

    for legacy_id in ("A1", "A2", "B4", "A3", "C1", "C2", "C3", "C6", "D2", "D3", "D1", "D5"):
        fallback = {
            "A1": "缺少培养目标/岗位能力文本", "A2": "缺少师资结构数据",
            "B4": "缺少实践学分数据", "A3": "缺少实验/实训条件数据",
            "C1": "缺少就业质量报告中的落实率", "C2": "缺少签约率数据",
            "C3": "缺少深造率或同类基准", "C6": "缺少用人单位调查数据",
            "D2": "缺少技能需求向量", "D3": "缺少新兴技能标注或岗位样本",
            "D1": "缺少去重后岗位数或基期岗位数", "D5": "缺少按技能分组的薪资数据",
        }[legacy_id]
        out.append(reuse(legacy_id, fallback))
    return out


def dependency_graph() -> metric_graph.MetricGraph:
    graph = metric_graph.MetricGraph()
    for spec in SPECS:
        absolute = DIMENSIONS[spec.dimension]["weight"] * spec.weight
        graph.add(metric_graph.MetricNode(
            metric_id=spec.id, name=spec.name, dimension=spec.dimension,
            primitives=spec.primitives, transform=spec.transform,
            weight=round(absolute, 4), version=VERSION,
        ))
    return graph


def dimension_scores(metrics: Sequence[MetricValue]) -> dict[str, dict[str, Any]]:
    by_dim: dict[str, list[MetricValue]] = {}
    for metric in metrics:
        spec = SPEC_BY_ID.get(metric.metric_id)
        if spec:
            by_dim.setdefault(spec.dimension, []).append(metric)
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


def compute(
    metrics: Sequence[MetricValue],
    *,
    min_dimension_coverage: float = 0.34,
    required_dimensions: Sequence[str] = ("F_供需适配",),
) -> dict[str, Any]:
    dims = dimension_scores(metrics)
    usable = {d: v for d, v in dims.items()
              if v["score"] is not None and v["coverage"] >= min_dimension_coverage}
    excluded = {d: v for d, v in dims.items() if d not in usable}
    # 供需适配是 Primary TSI 的定义性维度：它不可用时，"人才供需适配度"这个概念
    # 本身不成立，不能拿剩下的人才结果/需求背景拼一个分数冒充适配结论。
    missing_required = [d for d in required_dimensions if d not in usable]
    total_w = sum(DIMENSIONS[d]["weight"] for d in usable)
    tsi = None
    if not missing_required and usable and total_w:
        tsi = sum(DIMENSIONS[d]["weight"] * v["score"] for d, v in usable.items()) / total_w
    coverage = round(sum(DIMENSIONS[d]["weight"] for d in usable)
                     / sum(v["weight"] for v in DIMENSIONS.values()), 4)
    confidence = (round(sum(DIMENSIONS[d]["weight"] * v["confidence"] for d, v in usable.items())
                        / total_w, 4) if total_w else 0.0)
    level_counts: dict[str, int] = {}
    for metric in metrics:
        if metric.value is not None:
            level_counts[metric.evidence_level] = level_counts.get(metric.evidence_level, 0) + 1
    graph = dependency_graph()
    return {
        "version": VERSION,
        "primary_tsi": None if tsi is None else round(tsi, 2),
        "band": None if tsi is None else tsi_v2_mod.band_of(tsi),
        "dimensions": dims,
        "excluded_dimensions": {
            d: {"reason": "coverage below threshold", "coverage": v["coverage"]}
            for d, v in excluded.items()
        },
        "required_dimensions": list(required_dimensions),
        "missing_required_dimensions": missing_required,
        "not_computable_reason": (
            "供需适配维不可用（" + "、".join(missing_required) + "）：缺少可核查的供给或需求向量，"
            "Primary TSI 不予计算；其余维度只作背景展示。"
        ) if missing_required else "",
        "not_computable_short": (
            "供需适配维不可用（缺少可核查的供给或需求向量，且不使用同类基准替代）"
        ) if missing_required else "",
        "weighted_coverage": coverage,
        "confidence": confidence,
        "n_available": sum(1 for m in metrics if m.value is not None),
        "n_total": len(SPECS),
        "evidence_level_distribution": level_counts,
        "missing_indicators": [m.metric_id for m in metrics if m.value is None],
        "metrics": [m.to_dict() for m in metrics],
        "dependency_graph": graph.to_dict(),
        "method_note": (
            "Primary TSI = 0.40·供需适配 + 0.20·培养基础 + 0.25·人才结果 + 0.15·需求背景；"
            "缺失指标不参与加权（不记 0）；维度覆盖率低于阈值时整维剔除并披露。"
        ),
    }


def spec_table() -> list[dict[str, Any]]:
    rows = []
    for spec in SPECS:
        row = asdict(spec)
        row["dimension_weight"] = DIMENSIONS[spec.dimension]["weight"]
        row["absolute_weight"] = round(DIMENSIONS[spec.dimension]["weight"] * spec.weight, 4)
        rows.append(row)
    return rows


def version_registry(
    primary: Mapping[str, Any],
    v1: Mapping[str, Any] | None,
    v2: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Publish exactly one formal score and demote the rest to named roles."""
    return {
        "formal": {
            "role": "primary",
            "id": "primary_tsi",
            "version": primary.get("version"),
            "score": primary.get("primary_tsi"),
            "dimensions": list(DIMENSIONS),
            "note": "对用户唯一露出的正式主指标。",
        },
        "historical_version": {
            "role": "historical_version",
            "id": "tsi_v1",
            "version": "1.0",
            "score": (v1 or {}).get("tsi"),
            "n_indicators": (v1 or {}).get("n_indicators"),
            "note": "27 三级指标 A/B/C，权重取自 TSI指标搭建.docx；仅作历史对照，不进入结论页。",
        },
        "research_comparison": {
            "role": "research_comparison",
            "id": "tsi_v2",
            "version": "2.0",
            "score": (v2 or {}).get("tsi_v2"),
            "n_indicators": (v2 or {}).get("n_total"),
            "note": "四维 24 指标，含 B1≡C4 的重复输入；作为研究对照版本保留。",
        },
        "benchmark_version": {
            "role": "benchmark_version",
            "id": "tsi_v2",
            "version": "2.0",
            "score": (v2 or {}).get("tsi_v2"),
            "note": "供 Benchmark 横向比较使用的口径（与 research_comparison 同一计算）。",
        },
    }
