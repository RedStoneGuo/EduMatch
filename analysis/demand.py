"""Demand Vector - the single demand-side object of the Core TSI Engine.

``Demand(skill)`` is a weighted blend of the components the招聘数据 can actually
support::

    frequency            岗位中该技能的出现频率
    position_coverage    覆盖的岗位比例
    occupation_coverage  覆盖的岗位族（不同岗位名称）比例
    salary_premium       该技能岗位相对市场中位的薪资溢价
    policy_relevance     政策文本中的相关性（背景变量，非因果）
    industry_weight      产业方向权重（背景变量）
    trend                跨期变化，仅当有 ≥2 个时间窗口
    stability            需求普遍性/稳定性，仅当有 ≥2 个时间窗口

Components that cannot be computed are ``None``: they leave both numerator and
denominator, and their absence is published in ``unavailable_components`` so the
demand score is never inflated by a guess. This module is a thin, auditable
façade over :mod:`edumatch.jobs.demand`; it owns no scoring logic of its own.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

try:  # 允许 analysis 在无 edumatch 依赖的场景下单独使用
    from edumatch.jobs.demand import COMPONENT_WEIGHTS
except Exception:  # noqa: BLE001
    COMPONENT_WEIGHTS = {
        "frequency": 0.25, "position_coverage": 0.20, "occupation_coverage": 0.15,
        "salary_premium": 0.10, "policy_relevance": 0.15, "industry_weight": 0.05,
        "trend": 0.05, "stability": 0.05,
    }

COMPONENT_LABELS = {
    "frequency": "出现频率",
    "position_coverage": "岗位覆盖",
    "occupation_coverage": "岗位族覆盖",
    "salary_premium": "薪资溢价",
    "policy_relevance": "政策相关度",
    "industry_weight": "产业方向权重",
    "trend": "跨期趋势",
    "stability": "需求稳定性",
}


def build_demand_vector(demands: Iterable[Any]) -> dict[str, Any]:
    """Turn ``SkillDemand`` objects into the engine's demand vector."""
    rows: list[dict[str, Any]] = []
    score: dict[str, float] = {}
    meta: dict[str, dict[str, Any]] = {}
    missing: set[str] = set()
    levels: dict[str, int] = {}
    for item in demands:
        name = getattr(item, "skill_name", None)
        value = getattr(item, "demand", None)
        if not name:
            continue
        missing |= set(getattr(item, "missing_components", []) or [])
        if value is None:
            continue
        level = str(getattr(item, "evidence_level", "D"))
        levels[level] = levels.get(level, 0) + 1
        score[name] = round(float(value), 4)
        meta[name] = {
            "confidence": round(float(getattr(item, "confidence", 0.0) or 0.0), 4),
            "evidence_level": level,
            "tier": getattr(item, "tier", None),
            "components": dict(getattr(item, "components", {}) or {}),
            "n_postings": getattr(item, "n_postings", None),
            "detail": dict(getattr(item, "detail", {}) or {}),
        }
        rows.append({
            "skill": name,
            "demand": score[name],
            "confidence": meta[name]["confidence"],
            "evidence_level": level,
            "components": {k: (None if v is None else round(float(v), 4))
                           for k, v in meta[name]["components"].items()},
        })
    rows.sort(key=lambda r: (-r["demand"], r["skill"]))
    return {
        "score": score,
        "meta": meta,
        "rows": rows,
        "n_skills": len(score),
        "top_skills": rows[:12],
        "component_weights": dict(COMPONENT_WEIGHTS),
        "component_labels": dict(COMPONENT_LABELS),
        "unavailable_components": sorted(missing),
        "evidence_level_distribution": levels,
        "method_note": (
            "Demand = Σ w_k·component_k / Σ w_k，仅对可用分量求和；"
            "不可用分量（如单期数据下的 trend/stability）不参与计算并在报告中披露。"
        ),
    }


def demand_score_map(vector: Mapping[str, Any]) -> dict[str, float]:
    return dict(vector.get("score") or {})


def demand_meta_map(vector: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        skill: {"confidence": m.get("confidence", 0.0),
                "evidence_level": m.get("evidence_level", "D"),
                "tier": m.get("tier")}
        for skill, m in (vector.get("meta") or {}).items()
    }
