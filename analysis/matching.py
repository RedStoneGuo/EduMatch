"""Course–Skill matrix and demand-weighted matching.

The model is explicitly *not* TF-IDF + cosine. Supply is derived from an
ontology-backed course→skill mapping, then compared with a job-skill demand
vector. The formulas live in :mod:`analysis.supply` and :mod:`analysis.fit`;
this module only assembles the matrix object and keeps the historical public
API (``CourseSkillMatrix``, ``demand_weighted_match``) working.

    Supply(s)  = min( Σ_c w_c / C_ref , 1 )        # see analysis/supply.py
    Match      = Fit = Σ_s Demand(s) · min(Supply(s), 1) / Σ_s Demand(s)

where ``w_c`` blends course credits and practice flag. Hierarchy propagation in
the ontology means "PyTorch" also credits "深度学习" and "人工智能".

``C_ref`` is a *reference instruction volume* (default 6 credits) rather than
total programme credits: a skill taught by several courses should approach a
supply of 1, which makes Supply comparable with the demand intensity scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import fit as fit_mod
from . import supply as supply_mod


@dataclass
class CourseSkillMatrix:
    course_ids: list[str]
    skills: list[str]
    weights: list[float]
    matrix: list[list[float]]
    supply: dict[str, float]          # normalised 0-1, comparable with demand
    supply_share: dict[str, float]    # share of total programme weight (diagnostic)
    credits_by_skill: dict[str, float]
    reference_credits: float
    unmapped_courses: list[str] = field(default_factory=list)
    supply_channels: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: str = "peer"
    reliability: str = "medium"
    supply_status: str = "ok"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_ids": self.course_ids,
            "skills": self.skills,
            "weights": self.weights,
            "matrix": self.matrix,
            "supply": {k: round(v, 4) for k, v in self.supply.items()},
            "supply_share": {k: round(v, 4) for k, v in self.supply_share.items()},
            "credits_by_skill": {k: round(v, 2) for k, v in self.credits_by_skill.items()},
            "reference_credits": self.reference_credits,
            "unmapped_courses": self.unmapped_courses,
            "provenance": self.provenance,
            "reliability": self.reliability,
            "supply_status": self.supply_status,
            "reason": self.reason,
            "supply_channels": self.supply_channels,
        }


def course_weight(course: dict[str, Any]) -> float:
    """One course's contribution to the supply sum.

    Kept as a public helper: ``analysis.supply.course_supply_weight`` implements
    the credit/practice/required/depth channels. For a plain course (credits and
    practice flag only) the two are numerically identical, which is what keeps
    the historical results comparable.
    """
    weight, _audit = supply_mod.course_supply_weight(course)
    return weight


def build_course_skill_matrix(
    courses: Sequence[dict[str, Any]],
    resolve_skills,
    *,
    skill_universe: Sequence[str] | None = None,
    reference_credits: float = 6.0,
    provenance: str = "peer",
    objective_skills: Sequence[str] | None = None,
    min_courses: int = 3,
    vector: Any = None,
) -> CourseSkillMatrix:
    """Build the course × skill matrix from the continuous supply model.

    ``resolve_skills(course_name, description) -> list[skill_id]`` is injected so
    this function stays independent of the ontology implementation.
    """
    if vector is None:
        vector = supply_mod.build_supply_vector(
            courses, resolve_skills, provenance=provenance, skill_universe=skill_universe,
            reference_credits=reference_credits, objective_skills=objective_skills,
            min_courses=min_courses,
        )
    course_ids: list[str] = []
    weights: list[float] = []
    rows: list[set[str]] = []
    unmapped: list[str] = []
    for idx, course in enumerate(courses):
        name = str(course.get("name") or course.get("course") or f"course_{idx}")
        cid = str(course.get("course_id") or f"c{idx:03d}")
        skills = set(resolve_skills(name, str(course.get("description") or "")))
        if not skills:
            unmapped.append(name)
        course_ids.append(cid)
        weights.append(course_weight(course))
        rows.append(skills)

    skills = vector.skills
    matrix = [[1.0 if s in row else 0.0 for s in skills] for row in rows]
    # ``credits_by_skill`` keeps the historical meaning: the summed course
    # weight covering the skill (not the raw credit number), so old results and
    # the manual recomputation in the evaluation stay comparable.
    credits_by_skill = {s: c.weight for s, c in vector.channels.items()}
    return CourseSkillMatrix(
        course_ids=course_ids,
        skills=skills,
        weights=weights,
        matrix=matrix,
        supply=dict(vector.score),
        supply_share=vector.supply_share(),
        credits_by_skill=credits_by_skill,
        reference_credits=reference_credits,
        unmapped_courses=unmapped,
        supply_channels={s: c.to_dict() for s, c in vector.channels.items()},
        provenance=provenance,
        reliability=vector.reliability,
        supply_status=vector.status,
        reason=vector.reason,
    )


def demand_weighted_match(
    supply: dict[str, float],
    demand: dict[str, float],
    *,
    demand_confidence: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Demand-weighted supply coverage in [0, 1] - delegates to ``fit.skill_fit``."""
    demand_confidence = demand_confidence or {}
    demand_meta = {
        skill: {"confidence": demand_confidence.get(skill, 0.0)} for skill in demand
    }
    result = fit_mod.skill_fit(
        supply, demand, demand_meta=demand_meta, unlisted_supply_is_zero=True
    )
    per_skill = [
        {
            "skill": row["skill"],
            "demand": row["demand"],
            "supply": row["supply"],
            "contribution": row["fit_component"] if row["fit_component"] is not None else 0.0,
            "gap": row["gap"],
            "status": row["status"],
            "confidence": row["confidence"],
        }
        for row in result["per_skill"] if row["demand"] is not None
    ]
    return {
        "matching_score": result["fit"],
        "matching_score_100": result["fit_100"],
        "n_skills_compared": len(per_skill),
        "confidence": result["confidence"],
        "per_skill": per_skill,
        "fit_closure": fit_mod.fit_gap_closure(result),
    }


def breadth_metrics(supply: dict[str, float], demand: dict[str, float]) -> dict[str, Any]:
    """Breadth-style diagnostics that do not depend on weights."""
    demand_skills = {s for s, d in demand.items() if d}
    supply_skills = {s for s, v in supply.items() if v > 0}
    if not demand_skills:
        return {"jaccard": None, "precision": None, "recall": None}
    inter = demand_skills & supply_skills
    union = demand_skills | supply_skills
    return {
        "jaccard": round(len(inter) / len(union), 4) if union else None,
        "precision": round(len(inter) / len(supply_skills), 4) if supply_skills else None,
        "recall": round(len(inter) / len(demand_skills), 4),
        "matched_skills": sorted(inter),
        "unmet_demand_skills": sorted(demand_skills - supply_skills),
    }


def major_skill_job_matching(
    matrix: CourseSkillMatrix,
    demands: Iterable[Any],
    *,
    supply_getter=None,
) -> dict[str, Any]:
    """Convenience wrapper: Course×Skill matrix -> major–skill–job matching."""
    supply = supply_getter(matrix) if supply_getter else matrix.supply
    demand: dict[str, float] = {}
    conf: dict[str, float] = {}
    for item in demands:
        name = getattr(item, "skill_name", None) or item.get("skill")
        value = getattr(item, "demand", None) if not isinstance(item, dict) else item.get("demand")
        if name is None or value is None:
            continue
        demand[name] = float(value)
        conf[name] = float(getattr(item, "confidence", 0.0) if not isinstance(item, dict) else item.get("confidence", 0.0))
    result = demand_weighted_match(supply, demand, demand_confidence=conf)
    result.update(breadth_metrics(supply, demand))
    result["demand_used"] = {k: round(v, 4) for k, v in demand.items()}
    return result
