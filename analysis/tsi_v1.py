"""Core TSI Engine V1 - the 27-indicator A/B/C system.

Weights and structure are taken verbatim from ``TSI指标搭建.docx``:

    TSI = 0.25A + 0.30B + 0.45C

Scoring rules follow the same document:

* continuous : ``clamp(60 + (raw - benchmark) / benchmark * 40, 0, 100)``
* ordinal    : lookup table (e.g. B12: yearly 100 / every-2-years 85 / ... )
* semantic   : ``similarity * 100``

Differences from the legacy Coze pipeline (both required by the task spec):

1. missing evidence -> ``value=None`` + ``status='insufficient_evidence'`` and the
   indicator is dropped from the weighted average (the legacy run wrote 0, which
   made ~39% of the total weight measure "did the report mention it");
2. no LLM ever produces a number here - every value comes from a rule or from a
   deterministic computation over extracted facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from edumatch.evidence import MetricValue

# ---------------------------------------------------------------- structure

#: indicator -> absolute weight inside the whole TSI (product of every level)
WEIGHTS: dict[str, float] = {
    # A 投入适配度 (0.25) = 0.32*A1 + 0.68*A2
    "A11": 0.25 * 0.32 * 0.25, "A12": 0.25 * 0.32 * 0.38, "A13": 0.25 * 0.32 * 0.37,
    "A21": 0.25 * 0.68 * 0.06, "A22": 0.25 * 0.68 * 0.24,
    "A23": 0.25 * 0.68 * 0.41, "A24": 0.25 * 0.68 * 0.29,
    # B 过程适配度 (0.30)
    "B11": 0.30 * 0.17 * 0.60, "B12": 0.30 * 0.17 * 0.40,
    "B21": 0.30 * 0.20 * 0.50, "B22": 0.30 * 0.20 * 0.50,
    "B31": 0.30 * 0.23 * 0.28, "B32": 0.30 * 0.23 * 0.43, "B33": 0.30 * 0.23 * 0.29,
    "B41": 0.30 * 0.20 * 0.33, "B42": 0.30 * 0.20 * 0.67,
    "B51": 0.30 * 0.20 * 0.33, "B52": 0.30 * 0.20 * 0.67,
    # C 产出适配度 (0.45)
    "C11": 0.45 * 0.36 * 0.25, "C12": 0.45 * 0.36 * 0.45, "C13": 0.45 * 0.36 * 0.30,
    "C21": 0.45 * 0.34 * 0.30, "C22": 0.45 * 0.34 * 0.25, "C23": 0.45 * 0.34 * 0.45,
    "C31": 0.45 * 0.30 * 0.20, "C32": 0.45 * 0.30 * 0.45, "C33": 0.45 * 0.30 * 0.35,
}

NAMES: dict[str, str] = {
    "A11": "专业设置依据科学性", "A12": "专业-产业匹配度", "A13": "培养目标与岗位能力一致性",
    "A21": "组织建设", "A22": "经费投入", "A23": "师资队伍", "A24": "硬软件投入",
    "B11": "培养方案对产业需求响应程度", "B12": "培养方案更新频率",
    "B21": "产业需求融入教学深度", "B22": "校企联合培养程度",
    "B31": "专业品牌", "B32": "行业声誉", "B33": "数字化教学水平",
    "B41": "校企共编教材", "B42": "企业参与课程开发",
    "B51": "实践学时设计合理性", "B52": "实践教学成效",
    "C11": "基本素养", "C12": "专业能力", "C13": "数字技能",
    "C21": "就业率", "C22": "就业稳定性", "C23": "专业-岗位匹配度",
    "C31": "用人单位总体满意度", "C32": "岗位胜任度", "C33": "创新与发展潜力",
}
DIMENSION_WEIGHTS = {"A": 0.25, "B": 0.30, "C": 0.45}
DIMENSION_NAMES = {"A": "投入适配度", "B": "过程适配度", "C": "产出适配度"}


def dimension_of(indicator: str) -> str:
    return indicator[0]


# ---------------------------------------------------------------- scoring

def score_continuous(raw: float | None, benchmark: float | None, *,
                     higher_is_better: bool = True) -> float | None:
    """The document's rule, with a direction flag (逆行指标如生师比用 lower)."""
    if raw is None or not benchmark:
        return None
    ratio = raw / benchmark
    if not higher_is_better:
        ratio = benchmark / raw if raw else None
        if ratio is None:
            return None
    score = 60 + (ratio - 1.0) * 40
    return round(max(0.0, min(score, 100.0)), 2)


def continuous_basis(raw: float | None, benchmark: float | None, *,
                     higher_is_better: bool = True, label: str = "") -> dict[str, Any]:
    """Structured audit record: raw → benchmark → formula → score."""
    ratio = None
    if raw is not None and benchmark:
        ratio = (raw / benchmark) if higher_is_better else (benchmark / raw if raw else None)
    return {
        "type": "continuous",
        "metric": label,
        "raw": raw,
        "benchmark": benchmark,
        "ratio": None if ratio is None else round(ratio, 4),
        "direction": "higher_is_better" if higher_is_better else "lower_is_better",
        "formula": "clamp(60 + (ratio - 1) * 40, 0, 100)",
        "score": score_continuous(raw, benchmark, higher_is_better=higher_is_better),
    }


def ordinal_basis(level: str | None, table: Mapping[str, float], label: str = "") -> dict[str, Any]:
    return {
        "type": "ordinal",
        "metric": label,
        "level": level,
        "table": dict(table),
        "formula": "查表",
        "score": score_ordinal(level, table),
    }


def semantic_basis(alignment: dict[str, Any] | None, label: str = "") -> dict[str, Any]:
    alignment = alignment or {}
    return {
        "type": "semantic_vector",
        "metric": label,
        "provider": alignment.get("provider"),
        "cosine": alignment.get("cosine"),
        "calibration": alignment.get("calibration"),
        "similarity": alignment.get("similarity"),
        "top_terms": [t[0] for t in (alignment.get("top_terms") or [])[:6]],
        "status": alignment.get("status"),
        "formula": "score = calibrated_similarity × 100",
        "score": _semantic_score(alignment),
    }


def direct_basis(value: float | None, source: str, label: str = "") -> dict[str, Any]:
    return {"type": "direct", "metric": label, "source": source,
            "formula": "直接采用上游计算值", "score": value}


def score_ordinal(level: str | None, table: Mapping[str, float]) -> float | None:
    return None if level is None else table.get(level)


B12_TABLE = {"yearly": 100.0, "every_2_years": 85.0, "every_3_years": 70.0,
             "older": 50.0, "never": 0.0}

#: 语义型指标：使用校准后的 similarity（0-1）。status != ok 说明原始余弦低于
#: 打分器公布的锚点下限，即**文本证据不足**，按规范记 null 而不是接近 0 的分数。
SEMANTIC_FLOOR = 0.0


def _semantic_score(alignment: dict[str, Any] | None) -> float | None:
    if not alignment:
        return None
    if alignment.get("status") not in (None, "ok"):
        return None
    similarity = alignment.get("similarity")
    if similarity is None or similarity <= SEMANTIC_FLOOR:
        return None
    return round(similarity * 100, 2)


# ---------------------------------------------------------------- metrics

def _m(indicator: str, value: float | None, *, detail: dict[str, Any] | None = None,
       evidence_level: str = "B", confidence: float = 0.8, reason: str = "",
       evidence_ids: list[str] | None = None) -> MetricValue:
    """``reason`` explains a *missing* value; for present values it records the basis."""
    if value is None:
        return MetricValue.missing(indicator, NAMES[indicator], reason or "原始数据缺失")
    basis = detail.get("basis") if detail else None
    if isinstance(basis, dict):
        basis = "见 basis（原始值/基准/公式/分数）"
    return MetricValue(
        metric_id=indicator, name=NAMES[indicator], value=round(float(value), 2),
        unit="score", status="ok", confidence=confidence,
        evidence_level=evidence_level,  # type: ignore[arg-type]
        source_count=len(evidence_ids or []), available=True,
        evidence_ids=list(evidence_ids or []),
        reason=str(basis) if basis else "由确定性规则计算（见 detail.basis）",
        detail=detail or {},
    )


def score_indicators_v1(context: dict[str, Any], benchmark: dict[str, float] | None = None,
                        evidence: dict[str, Any] | None = None) -> list[MetricValue]:
    """Compute the 27 indicators from an analysis context.

    ``context`` keys mirror the V2 engine (teaching / employment / matching / gaps /
    market / semantic / skills), so the same run can produce both versions.
    """
    benchmark = benchmark or {}
    ctx = context
    teaching = ctx.get("teaching") or {}
    employment = ctx.get("employment") or {}
    matching = ctx.get("matching") or {}
    semantic = ctx.get("semantic") or {}
    evidence = evidence or {}
    signals = evidence.get("text_signals") or {}
    ev_map: dict[str, list[str]] = evidence.get("evidence_map") or {}

    def ev(key: str) -> list[str]:
        return list(ev_map.get(key) or [])

    metrics: list[MetricValue] = []

    def sem(name: str) -> float | None:
        return _semantic_score(semantic.get(name))

    semantic_signals = ctx.get("semantic_signals") or {}

    def sig(name: str) -> tuple[float | None, dict[str, Any]]:
        """语义证据优先，余弦低于锚点时退回关键词规则（并在依据中标注来源）。"""
        from analysis.semantic_evidence import semantic_score

        item = semantic_signals.get(name)
        value = semantic_score(name, item, SIGNAL_SCORES)
        if value is not None:
            return value, {
                "type": "semantic_anchor",
                "signal": name,
                "level": (item or {}).get("level"),
                "cosine": (item or {}).get("cosine"),
                "anchor": (item or {}).get("anchor"),
                "quote": (item or {}).get("evidence_quote"),
                "provider": (item or {}).get("provider"),
                "formula": "锚点等级基准分 × (0.95 + 0.10 × 校准余弦)",
                "score": value,
            }
        keyword_level = signals.get(name)
        fallback = signal_score(name, keyword_level)
        return fallback, {
            "type": "keyword_rule",
            "signal": name,
            "level": keyword_level,
            "note": "向量余弦低于锚点下限，回退关键词规则",
            "table": SIGNAL_SCORES.get(name),
            "formula": "查表",
            "score": fallback,
        }

    # ---- A ----
    _v, _b = sig("setup_basis")
    metrics.append(_m("A11", _v, detail={"basis": _b}, evidence_ids=ev("text.report"),
        evidence_level="D", confidence=0.45,
        reason="教学质量报告中未见专业设置论证（语义与关键词均未命中）"))
    metrics.append(_m("A12", sem("major_industry_alignment"), evidence_ids=ev("text.report"),
                      detail={"basis": semantic_basis(semantic.get("major_industry_alignment"),
                                                      "专业方向 + 岗位技能 × 政策产业方向")},
                      evidence_level="D", confidence=0.5, reason="缺少专业方向或产业方向文本"))
    metrics.append(_m("A13", sem("objective_job_alignment"), evidence_ids=ev("text.report"),
                      detail={"basis": semantic_basis(semantic.get("objective_job_alignment"),
                                                      "培养目标原文 × 岗位能力需求")},
                      evidence_level="D", confidence=0.5, reason="报告中未定位到培养目标原文"))
    _v, _b = sig("organization")
    metrics.append(_m("A21", _v, detail={"basis": _b}, evidence_ids=ev("text.report"),
        evidence_level="D", confidence=0.4,
        reason="报告中无教学组织建设描述"))
    metrics.append(_m("A22", score_continuous(teaching.get("funding_per_student"),
                                              benchmark.get("funding_per_student")),
                      reason="报告未披露经费投入"))
    senior = teaching.get("senior_title_ratio")
    sfr = teaching.get("student_faculty_ratio")
    a23_parts = [
        (score_continuous(senior, benchmark.get("senior_title_ratio", 0.55)), 0.6),
        (score_continuous(sfr, benchmark.get("student_faculty_ratio", 18.0),
                          higher_is_better=False), 0.4),
    ]
    usable = [(v, w) for v, w in a23_parts if v is not None]
    a23 = round(sum(v * w for v, w in usable) / sum(w for _, w in usable), 2) if usable else None
    metrics.append(_m("A23", a23, evidence_ids=ev("teaching.senior_title_ratio") + ev("teaching.student_faculty_ratio"),
                      detail={"senior_title_ratio": senior, "student_faculty_ratio": sfr,
                                          "basis": {"type": "composite", "weights": {"高级职称比例": 0.6, "生师比": 0.4},
                                                    "senior": continuous_basis(senior, benchmark.get("senior_title_ratio", 0.55)),
                                                    "student_faculty": continuous_basis(
                                                        sfr, benchmark.get("student_faculty_ratio", 18.0),
                                                        higher_is_better=False),
                                                    "formula": "0.6×高级职称分 + 0.4×生师比分", "score": a23}},
                      reason="缺少师资结构数据"))
    bases = teaching.get("training_base_count")
    metrics.append(_m("A24", None if bases is None else round(min(bases / 3.0, 1.0) * 100, 2),
                      evidence_ids=ev("teaching.training_base_count"),
                      detail={"training_base_count": bases,
                              "basis": {"type": "threshold", "raw": bases, "anchor": 3,
                                        "formula": "min(基地数 / 3, 1) × 100",
                                        "score": None if bases is None else round(min(bases / 3.0, 1.0) * 100, 2)}},
                      reason="缺少实验/实训条件数据"))

    # ---- B ----
    metrics.append(_m("B11", matching.get("matching_score_100"), evidence_ids=ev("matching"),
                      detail={"basis": direct_basis(matching.get("matching_score_100"),
                                                    "analysis.matching.demand_weighted_match")},
                      evidence_level="C",
                      confidence=float(matching.get("confidence") or 0.5),
                      reason="课程-技能矩阵为空，无法计算产业需求响应程度"))
    metrics.append(_m("B12", score_ordinal(teaching.get("curriculum_update_level"), B12_TABLE),
                      evidence_level="C", confidence=0.5, reason="培养方案更新频率无记录"))
    metrics.append(_m("B21", sem("curriculum_market_alignment"), evidence_ids=ev("text.report"),
                      detail={"basis": semantic_basis(semantic.get("curriculum_market_alignment"),
                                                      "课程文本 × 岗位技能需求")},
                      evidence_level="D",
                      confidence=0.5, reason="缺少课程文本或岗位需求文本"))
    _v, _b = sig("industry_cooperation")
    metrics.append(_m("B22", _v, detail={"basis": _b}, evidence_ids=ev("text.report"),
        evidence_level="D", confidence=0.4, reason="校企合作缺少可核查证据"))
    metrics.append(_m("B31", None, evidence_level="E", confidence=0.0,
                      reason="专业品牌无客观数据来源，按规范记 null 而非主观打分"))
    metrics.append(_m("B32", None, evidence_level="E", confidence=0.0,
                      reason="行业声誉无客观数据来源，按规范记 null"))
    _v, _b = sig("digital_teaching")
    metrics.append(_m("B33", _v, detail={"basis": _b}, evidence_ids=ev("text.report"),
        evidence_level="D", confidence=0.45,
        reason="数字化教学无证据"))
    _v, _b = sig("joint_textbook")
    metrics.append(_m("B41", _v, detail={"basis": _b}, evidence_ids=ev("text.report"),
        evidence_level="D", confidence=0.4, reason="未见校企共编教材证据"))
    _v, _b = sig("enterprise_course")
    metrics.append(_m("B42", _v, detail={"basis": _b}, evidence_ids=ev("text.report"),
        evidence_level="D", confidence=0.45,
        reason="未见企业参与课程开发证据"))
    practice = teaching.get("practice_credit_ratio")
    metrics.append(_m("B51", score_continuous(practice, benchmark.get("practice_credit_ratio", 0.25)),
                      evidence_ids=ev("teaching.practice_credit_ratio"),
                      detail={"basis": continuous_basis(practice, benchmark.get("practice_credit_ratio", 0.25),
                                                        label="实践学分占比")},
                      reason="缺少实践学分数据"))
    metrics.append(_m("B52", None if bases is None else round(min(bases / 5.0, 1.0) * 100, 2),
                      detail={"training_base_count": bases}, evidence_level="D",
                      confidence=0.45, reason="缺少实践教学成效证据"))

    # ---- C ----
    metrics.append(_m("C11", None, evidence_level="E", confidence=0.0,
                      reason="报告未提供毕业生基本素养调查数据"))
    metrics.append(_m("C12", None, evidence_level="E", confidence=0.0,
                      reason="报告未提供专业能力评价数据"))
    metrics.append(_m("C13", None, evidence_level="E", confidence=0.0,
                      reason="数字技能无供给侧评价数据（岗位要求属需求侧，不用于此处）"))
    metrics.append(_m("C21", score_continuous(employment.get("placement_rate"),
                                              benchmark.get("placement_rate", 0.92)),
                      evidence_ids=ev("employment.placement_rate"),
                      detail={"raw": employment.get("placement_rate"), "scope_rule": "仅就业质量报告",
                              "basis": continuous_basis(employment.get("placement_rate"),
                                                        benchmark.get("placement_rate", 0.92),
                                                        label="毕业去向落实率")},
                      evidence_level="A", confidence=0.9, reason="缺少就业质量报告中的落实率"))
    metrics.append(_m("C22", score_continuous(employment.get("signing_rate"),
                                              benchmark.get("signing_rate", 0.90)),
                      evidence_ids=ev("employment.signing_rate"),
                      detail={"basis": continuous_basis(employment.get("signing_rate"),
                                                        benchmark.get("signing_rate", 0.90),
                                                        label="签约率")},
                      evidence_level="A", confidence=0.85, reason="缺少签约率数据"))
    metrics.append(_m("C23", matching.get("matching_score_100"), evidence_ids=ev("matching"),
                      evidence_level="C",
                      confidence=0.6, reason="缺少岗位匹配与需求数据"))
    metrics.append(_m("C31", score_continuous(employment.get("employer_rating"),
                                              benchmark.get("employer_rating", 0.90)),
                      evidence_ids=ev("employment.employer_rating"),
                      detail={"basis": continuous_basis(employment.get("employer_rating"),
                                                        benchmark.get("employer_rating", 0.90),
                                                        label="用人单位满意度")},
                      evidence_level="A", confidence=0.85, reason="缺少用人单位满意度数据"))
    metrics.append(_m("C32", None, evidence_level="E", confidence=0.0,
                      reason="岗位胜任度需用人单位调查；按规范禁止用招聘 JD 反推"))
    metrics.append(_m("C33", None, evidence_level="E", confidence=0.0,
                      reason="创新与发展潜力无客观数据，按规范记 null"))
    return metrics


# ---------------------------------------------------------------- aggregation

def aggregate(metrics: list[MetricValue]) -> dict[str, Any]:
    """A/B/C with missing indicators dropped from the weighted average."""
    by_id = {m.metric_id: m for m in metrics}
    dimensions: dict[str, dict[str, Any]] = {}
    for dimension in ("A", "B", "C"):
        keys = [k for k in WEIGHTS if dimension_of(k) == dimension]
        usable = [k for k in keys if by_id.get(k) is not None and by_id[k].value is not None]
        total_weight = sum(WEIGHTS[k] for k in keys)
        used_weight = sum(WEIGHTS[k] for k in usable)
        score = (sum(WEIGHTS[k] * by_id[k].value for k in usable) / used_weight) if used_weight else None
        confidence = (sum(by_id[k].confidence * WEIGHTS[k] for k in usable) / used_weight) if used_weight else 0.0
        dimensions[dimension] = {
            "name": DIMENSION_NAMES[dimension],
            "level_weight": DIMENSION_WEIGHTS[dimension],
            "score": None if score is None else round(score, 2),
            "coverage": round(used_weight / total_weight, 4) if total_weight else 0.0,
            "confidence": round(confidence * (used_weight / total_weight), 4) if total_weight else 0.0,
            "n_available": len(usable),
            "n_total": len(keys),
            "missing_indicators": [k for k in keys if k not in usable],
        }
    usable_dims = [d for d in ("A", "B", "C") if dimensions[d]["score"] is not None]
    weight_sum = sum(DIMENSION_WEIGHTS[d] for d in usable_dims)
    tsi = (sum(DIMENSION_WEIGHTS[d] * dimensions[d]["score"] for d in usable_dims) / weight_sum
           if weight_sum else None)
    return {
        "tsi_version": "v1",
        "formula": "TSI = 0.25A + 0.30B + 0.45C",
        "tsi": None if tsi is None else round(tsi, 2),
        "dimensions": dimensions,
        "n_indicators": len(WEIGHTS),
        "n_available": sum(1 for m in metrics if m.value is not None),
        "weighted_coverage": round(weight_sum, 4),
        "missing_indicators": [k for k in WEIGHTS if by_id.get(k) is None or by_id[k].value is None],
        "method_note": "缺失指标不计入加权平均（不等于 0 分）；权重取自 TSI指标搭建.docx。",
    }


def compute_v1(context: dict[str, Any], benchmark: dict[str, float] | None = None,
               evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = score_indicators_v1(context, benchmark, evidence)
    return {"metrics": [m.to_dict() for m in metrics], **aggregate(metrics)}


# ---------------------------------------------------------------- text signals

#: 每个信号给出"分级 → 关键词列表"，按强度从高到低匹配；全部未命中则记 None。
SIGNAL_RULES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "setup_basis": [
        ("论证充分", ("专业设置论证", "设置论证", "新增专业论证", "专业建设论证", "需求调研报告")),
        ("有依据", ("设置依据", "主动布局", "增设", "新增专业", "优化专业结构")),
        ("仅提及", ("专业设置", "专业布局")),
    ],
    "organization": [
        ("设有专业负责人与教学组织", ("专业负责人", "专业建设委员会", "教学指导委员会", "教研室")),
        ("仅提及组织", ("教学组织", "基层教学组织")),
    ],
    "digital_teaching": [
        ("平台化+数据驱动", ("知识图谱", "智能助教", "数字化教学平台", "智慧课堂", "学情分析")),
        ("有在线课程/平台", ("在线课程", "慕课", "虚拟仿真", "智慧教学", "混合式教学")),
        ("仅提及", ("数字化", "信息技术")),
    ],
    "joint_textbook": [
        ("有共编教材", ("校企共编", "联合编写教材", "合作编写教材", "共同开发教材", "共编教材")),
        ("仅提及", ("教材建设", "自编教材")),
    ],
    "enterprise_course": [
        ("企业参与课程开发", ("企业参与课程", "企业共同开发课程", "校企共建课程", "企业专家参与")),
        ("企业导师参与", ("企业导师", "产业导师", "行业导师", "企业教师")),
        ("仅提及", ("校企合作", "产教融合")),
    ],
    "industry_cooperation": [
        ("joint_course_and_base", ("校企共建课程", "共建实习基地", "联合实验室", "产业学院")),
        ("enterprise_mentor", ("企业导师", "产业导师", "企业专家授课")),
        ("internship_only", ("实习基地", "实践基地", "顶岗实习")),
        ("mentioned_only", ("校企合作", "产教融合", "产学研")),
    ],
}


def detect_signals(text: str) -> dict[str, str | None]:
    """Rule-based ordinal signals from report prose (evidence level D).

    Returns ``None`` for a signal with no supporting sentence - the indicator is
    then reported as missing instead of receiving a made-up score.

    The top tier of each signal requires **at least two** distinct keywords, so a
    single passing mention cannot earn the maximum score.
    """
    if not text:
        return {name: None for name in SIGNAL_RULES}
    out: dict[str, str | None] = {}
    for name, levels in SIGNAL_RULES.items():
        found = None
        for index, (level, keywords) in enumerate(levels):
            hits = sum(1 for keyword in keywords if keyword in text)
            required = 2 if index == 0 else 1
            if hits >= required:
                found = level
                break
        out[name] = found
    return out


#: 信号分级 → 分数。最高档留出余量（90 而非 100），避免"单句命中=满分"。
SIGNAL_SCORES: dict[str, dict[str, float]] = {
    "setup_basis": {"论证充分": 90.0, "有依据": 75.0, "仅提及": 50.0},
    "organization": {"设有专业负责人与教学组织": 85.0, "仅提及组织": 65.0},
    "digital_teaching": {"平台化+数据驱动": 90.0, "有在线课程/平台": 75.0, "仅提及": 50.0},
    "joint_textbook": {"有共编教材": 85.0, "仅提及": 50.0},
    "enterprise_course": {"企业参与课程开发": 85.0, "企业导师参与": 70.0, "仅提及": 50.0},
    "industry_cooperation": {"joint_course_and_base": 90.0, "enterprise_mentor": 75.0,
                             "internship_only": 60.0, "mentioned_only": 45.0},
}


def signal_score(name: str, level: str | None) -> float | None:
    if level is None:
        return None
    return SIGNAL_SCORES.get(name, {}).get(level)
