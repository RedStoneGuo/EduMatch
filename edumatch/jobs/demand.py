"""Demand index for skills.

``Demand(skill)`` is a weighted blend of *available* components only. When a
component cannot be computed (e.g. no raw posting counts, fewer than two time
periods) it is excluded from the denominator and the per-skill confidence drops.
This is the direct fix for the legacy habit of scoring missing data as 0.

Weight semantics are published in ``docs/tsi_v2_spec.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .normalize import normalize_job

TIER_VALUE = {"high": 1.0, "medium": 0.6, "low": 0.3, "none": 0.0}

#: Demand(skill) blends only the components that the data can actually support.
#: ``occupation_coverage`` is the share of distinct job titles asking for the
#: skill (岗位族覆盖程度); ``stability`` needs at least two time windows and is
#: therefore ``None`` for a single snapshot - it is never imputed.
COMPONENT_WEIGHTS: dict[str, float] = {
    "frequency": 0.25,
    "position_coverage": 0.20,
    "occupation_coverage": 0.15,
    "salary_premium": 0.10,
    "policy_relevance": 0.15,
    "industry_weight": 0.05,
    "trend": 0.05,
    "stability": 0.05,
}

LEVEL_CONFIDENCE = {"A": 1.0, "B": 0.85, "C": 0.7, "D": 0.5, "E": 0.0}


@dataclass
class SkillDemand:
    skill_name: str
    demand: float | None
    components: dict[str, float | None]
    available_components: list[str]
    missing_components: list[str]
    confidence: float
    evidence_level: str
    n_postings: int | None = None
    tier: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill_name,
            "demand": None if self.demand is None else round(self.demand, 4),
            "components": {k: (None if v is None else round(v, 4)) for k, v in self.components.items()},
            "available_components": self.available_components,
            "missing_components": self.missing_components,
            "confidence": round(self.confidence, 4),
            "evidence_level": self.evidence_level,
            "n_postings": self.n_postings,
            "tier": self.tier,
            "detail": self.detail,
        }


def _blend(components: dict[str, float | None]) -> float | None:
    num = 0.0
    den = 0.0
    for name, weight in COMPONENT_WEIGHTS.items():
        value = components.get(name)
        if value is None:
            continue
        num += weight * float(value)
        den += weight
    return None if den == 0 else num / den


def load_market_evidence(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def demand_from_aggregate(
    evidence: dict[str, Any],
    *,
    policy_relevance: dict[str, float] | None = None,
    industry_weight: dict[str, float] | None = None,
) -> list[SkillDemand]:
    """Demand vector when only aggregated evidence survives (no raw postings)."""
    tiers: dict[str, str] = evidence.get("skill_frequency_tiers") or {}
    position_map: dict[str, list[str]] = evidence.get("position_skill_map") or {}
    positions = evidence.get("positions") or list(position_map)
    total_positions = max(len(positions), 1)
    level = str(evidence.get("evidence_level", "D"))
    counts = evidence.get("counts") or {}
    n_postings = counts.get("effective_count")

    coverage: dict[str, int] = {}
    for _position, skills in position_map.items():
        for skill in skills:
            coverage[skill] = coverage.get(skill, 0) + 1

    policy_relevance = policy_relevance or {}
    industry_weight = industry_weight or {}
    results: list[SkillDemand] = []
    # Skills that appear in position_skill_map but not in the legacy frequency
    # tier table must still enter the demand vector: we know positions ask for
    # them, we simply do not know their frequency tier. ``frequency`` stays None
    # (unknown) instead of being guessed.
    all_skills = sorted(set(tiers) | set(coverage))
    for skill in all_skills:
        tier = tiers.get(skill)
        components: dict[str, float | None] = {
            "frequency": TIER_VALUE.get(tier) if tier else None,
            "position_coverage": coverage.get(skill, 0) / total_positions if position_map else None,
            "occupation_coverage": (
                coverage.get(skill, 0) / len(position_map) if position_map else None
            ),
            "salary_premium": None,
            "policy_relevance": policy_relevance.get(skill),
            "industry_weight": industry_weight.get(skill),
            "trend": None,
            "stability": None,
        }
        available = [k for k, v in components.items() if v is not None]
        missing = [k for k, v in components.items() if v is None]
        demand = _blend(components)
        # confidence = fraction of weight that is evidence-backed * evidence level
        den = sum(COMPONENT_WEIGHTS.values())
        coverage_ratio = sum(COMPONENT_WEIGHTS[k] for k in available) / den
        confidence = coverage_ratio * LEVEL_CONFIDENCE.get(level, 0.5)
        results.append(
            SkillDemand(
                skill_name=skill,
                demand=demand,
                components=components,
                available_components=available,
                missing_components=missing,
                confidence=confidence,
                evidence_level=level,
                n_postings=n_postings,
                tier=tier,
                detail={"n_positions_considered": len(positions), "counts_status": "aggregate_only"},
            )
        )
    results.sort(key=lambda d: (-(d.demand or 0), d.skill_name))
    return results


def demand_from_jobs(
    rows: Iterable[dict[str, Any]],
    *,
    extract_skills,
    policy_relevance: dict[str, float] | None = None,
    industry_weight: dict[str, float] | None = None,
    trend: dict[str, float] | None = None,
    evidence_level: str = "C",
) -> list[SkillDemand]:
    """Demand vector from a deduplicated job table (the production path).

    ``evidence_level`` defaults to ``C``: platform postings are third-party
    public data, not official statistics, so they may not be presented as
    A-level evidence even though they are primary for the demand side.
    """
    rows = list(rows)
    total = len(rows)
    if total == 0:
        return []
    freq: dict[str, int] = {}
    salary_by_skill: dict[str, list[float]] = {}
    salaries: list[float] = []
    titles: set[str] = set()
    titles_by_skill: dict[str, set[str]] = {}
    for row in rows:
        salary = row.get("salary_max_norm") or row.get("salary_min_norm")
        if isinstance(salary, (int, float)) and salary > 0:
            salaries.append(float(salary))
        title = str(row.get("position") or "").strip()
        if title:
            titles.add(title)
        text = " ".join(str(row.get(k) or "") for k in ("position", "job_description", "skills"))
        skills = extract_skills(text)
        for skill in skills:
            freq[skill] = freq.get(skill, 0) + 1
            if title:
                titles_by_skill.setdefault(skill, set()).add(title)
            if isinstance(salary, (int, float)) and salary > 0:
                salary_by_skill.setdefault(skill, []).append(float(salary))
    median_all = sorted(salaries)[len(salaries) // 2] if salaries else None
    # 岗位族覆盖的参考刻度：一个技能出现在 30% 的不同岗位名称中即视为满覆盖。
    # 直接用 占比 会把所有技能压到 0.1-0.3，使 Demand 与 Supply 的量纲不再可比。
    OCCUPATION_FULL_COVERAGE_SHARE = 0.30
    policy_relevance = policy_relevance or {}
    industry_weight = industry_weight or {}
    trend = trend or {}
    results: list[SkillDemand] = []
    for skill, count in freq.items():
        values = salary_by_skill.get(skill, [])
        premium = None
        if values and median_all:
            premium = max(0.0, min((sorted(values)[len(values) // 2] / median_all) - 1.0, 1.0))
        components: dict[str, float | None] = {
            "frequency": min(count / total * 2, 1.0),
            "position_coverage": count / total,
            "occupation_coverage": (
                min(len(titles_by_skill.get(skill, ())) / len(titles) / OCCUPATION_FULL_COVERAGE_SHARE, 1.0)
                if titles else None
            ),
            "salary_premium": premium,
            "policy_relevance": policy_relevance.get(skill),
            "industry_weight": industry_weight.get(skill),
            "trend": trend.get(skill),
            # 单期抓包无法评估需求稳定性：留 None 并由置信度披露，禁止猜测。
            "stability": None,
        }
        available = [k for k, v in components.items() if v is not None]
        missing = [k for k, v in components.items() if v is None]
        demand = _blend(components)
        coverage_ratio = sum(COMPONENT_WEIGHTS[k] for k in available) / sum(COMPONENT_WEIGHTS.values())
        results.append(
            SkillDemand(
                skill_name=skill,
                demand=demand,
                components=components,
                available_components=available,
                missing_components=missing,
                confidence=coverage_ratio * LEVEL_CONFIDENCE.get(evidence_level, 0.7),
                evidence_level=evidence_level,
                n_postings=total,
                tier=None,
                detail={"observed_postings": count, "median_salary": median_all,
                        "n_distinct_titles": len(titles),
                        "n_titles_with_skill": len(titles_by_skill.get(skill, ()))},
            )
        )
    results.sort(key=lambda d: (-(d.demand or 0), d.skill_name))
    return results
