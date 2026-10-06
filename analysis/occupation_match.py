"""Occupational fit: 该院校专业 与 目标岗位 的匹配度。

The math is the same closed mainline as the rest of the engine - there is no
second scoring system:

    Occupation Match = Σ_s Demand_occ(s)·min(Supply(s),1) / Σ_s Demand_occ(s)

where ``Demand_occ`` is the demand vector computed from the postings of the
*target occupation family* only (see :mod:`edumatch.occupation`). The module adds
the presentation layer a reader needs when the question is "能匹配这个岗位吗":

* match band（高度匹配 / 较匹配 / 部分匹配 / 匹配不足 / 证据不足）；
* how many of the occupation's required skills the programme covers;
* the concrete skills to add (按需求强度排序）;
* the requirement context of that occupation (学历/薪资分布), if available.

Evidence rules are unchanged: a missing supply or demand side yields
``insufficient_evidence`` with the reason, never a made-up score.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from edumatch.evidence import MetricValue

from . import fit as fit_mod

BANDS: list[tuple[float, str]] = [
    (0.80, "高度匹配"),
    (0.65, "较匹配"),
    (0.45, "部分匹配"),
    (0.00, "匹配不足"),
]


def band_of(score: float | None) -> str | None:
    if score is None:
        return None
    for threshold, label in BANDS:
        if score >= threshold:
            return label
    return "匹配不足"


def match_occupation(
    supply: Mapping[str, float | None],
    demand: Mapping[str, float | None],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    supply_status: str = "ok",
    supply_reliability: str = "medium",
    supply_reason: str = "",
    supply_provenance: str = "target",
    occupation: Mapping[str, Any] | None = None,
    extra_demand: Sequence[str] | None = None,
    top_gaps: int = 8,
) -> dict[str, Any]:
    occupation = occupation or {}
    extra_demand = [s for s in (extra_demand or []) if s]
    # 岗位族自带的典型技能（如"大模型/Transformer/RAG"）若在该族岗位文本里没被抽到，
    # 仍以最小需求权重纳入分母：它们是该岗位的定义性技能，缺了就不能算匹配。
    demand_used = dict(demand)
    meta_used = dict(demand_meta or {})
    for skill in extra_demand:
        if skill not in demand_used:
            demand_used[skill] = 0.30
            meta_used.setdefault(skill, {"confidence": 0.5, "evidence_level": "D",
                                         "tier": "definitional"})

    fit_result = fit_mod.skill_fit(
        supply, demand_used, demand_meta=meta_used,
        supply_provenance=supply_provenance, supply_status=supply_status,
        supply_reliability=supply_reliability, supply_reason=supply_reason,
        unlisted_supply_is_zero=True,
    )
    score = fit_result.get("fit")
    rows = [r for r in fit_result.get("per_skill", []) if r.get("demand") is not None]
    covered = [r for r in rows if (r.get("supply") or 0) > 0]
    missing = [r for r in rows if (r.get("supply") or 0) <= 0 and r.get("supply") is not None]
    missing.sort(key=lambda r: -(r.get("demand") or 0))
    definitional = [s for s in extra_demand]
    definitional_covered = [s for s in definitional if (supply.get(s) or 0) > 0]

    status = "ok" if score is not None else "insufficient_evidence"
    reason = "" if score is not None else (
        supply_reason or "缺少可核查的专业供给或目标岗位需求向量"
    )
    return {
        "status": status,
        "reason": reason,
        "occupation": dict(occupation),
        "match_score": score,
        "match_100": fit_result.get("fit_100"),
        "band": band_of(score),
        "supply_provenance": supply_provenance,
        "supply_reliability": supply_reliability,
        "n_skills_total": fit_result.get("n_skills_total"),
        "n_skills_compared": fit_result.get("n_skills_compared"),
        "n_skills_covered": len(covered),
        "n_skills_missing": len(missing),
        "coverage": round(len(covered) / len(rows), 4) if rows else 0.0,
        "confidence": fit_result.get("confidence"),
        "definitional_skills": definitional,
        "definitional_covered": definitional_covered,
        "definitional_missing": [s for s in definitional if s not in definitional_covered],
        "top_required_skills": [
            {"skill": r["skill"], "demand": r["demand"], "supply": r["supply"],
             "gap": r["gap"], "covered": bool((r.get("supply") or 0) > 0)}
            for r in sorted(rows, key=lambda r: -(r.get("demand") or 0))[:12]
        ],
        "top_missing_skills": [
            {"skill": r["skill"], "demand": r["demand"], "gap": r["gap"]} for r in missing[:top_gaps]
        ],
        "covered_skills": [
            {"skill": r["skill"], "demand": r["demand"], "supply": r["supply"]}
            for r in sorted(covered, key=lambda r: -(r.get("demand") or 0))[:10]
        ],
        "per_skill": rows,
        "method_note": (
            "岗位匹配度 = Σ Demand_occ(s)·min(Supply(s),1)/Σ Demand_occ(s)；"
            "Demand_occ 只由目标岗位族的岗位计算，Supply 只取研究对象自身口径；"
            "岗位族定义性技能即使未被抽取也以最小权重计入分母。"
        ),
    }


def to_metric(result: Mapping[str, Any], *, metric_id: str = "JOB1",
              name: str = "目标岗位匹配度") -> MetricValue:
    """Expose the occupation match as a first-class, evidence-carrying metric."""
    score = result.get("match_score")
    if score is None:
        return MetricValue.missing(
            metric_id, name, str(result.get("reason") or "缺少供给或岗位需求向量"))
    return MetricValue(
        metric_id=metric_id, name=name, value=round(float(score) * 100, 2), unit="score",
        status="ok", confidence=float(result.get("confidence") or 0.5),
        evidence_level="C",  # type: ignore[arg-type]
        source_count=1, available=True,
        reason=f"目标岗位：{(result.get('occupation') or {}).get('name') or '—'}",
        detail={k: result.get(k) for k in (
            "match_score", "band", "n_skills_covered", "n_skills_missing",
            "definitional_skills", "definitional_missing", "method_note")},
    )
