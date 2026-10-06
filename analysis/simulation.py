"""Curriculum change simulator.

The simulator is a *what-if* on the current data and model assumptions. It never
claims to predict real labour-market outcomes, and every scenario carries an
explicit assumption block that must be shown to judges/users.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .matching import build_course_skill_matrix, demand_weighted_match
from .skill_gap import compute_skill_gaps


@dataclass
class CurriculumChange:
    """One simulated intervention."""

    kind: str  # add_course | remove_course | change_credits | add_practice
    course_name: str
    credits: float = 3.0
    skills: list[str] = field(default_factory=list)
    target_course: str | None = None
    delta_credits: float = 0.0
    practice_hours: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


ASSUMPTIONS = [
    "课程→技能映射由统一技能本体给出，不含教师实际授课质量的差异。",
    "技能供给按学分加权，选修课与必修课同等计入（如需区分请在输入中标注）。",
    "岗位需求侧向量在模拟中保持不变，即假设市场需求短期稳定。",
    "结果为模型假设下的相对变化，不是就业结果的预测。",
]


def apply_change(
    courses: Sequence[dict[str, Any]],
    change: CurriculumChange,
    resolve_skills,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    updated = [dict(c) for c in courses]
    log: dict[str, Any] = {"change": change.to_dict(), "applied": False}
    if change.kind == "add_course":
        updated.append(
            {
                "course_id": f"sim_{len(updated):03d}",
                "name": change.course_name,
                "credits": change.credits,
                "description": " ".join(change.skills),
                "is_practice": change.practice_hours > 0 or change.kind == "add_practice",
                "practice_hours": change.practice_hours,
                "simulated": True,
            }
        )
        log["applied"] = True
    elif change.kind == "remove_course":
        for c in updated:
            if c.get("name") == change.course_name or c.get("course_id") == change.course_name:
                c["credits"] = 0
                c["_removed"] = True
                log["applied"] = True
                break
    elif change.kind == "change_credits":
        for c in updated:
            if c.get("name") == change.target_course:
                c["credits"] = max(0.0, float(c.get("credits") or 0) + change.delta_credits)
                log["applied"] = True
                break
    else:
        log["error"] = f"unknown change kind: {change.kind}"
    if change.skills:
        log["declared_skills"] = change.skills
    return updated, log


def simulate_curriculum_change(
    *,
    courses: Sequence[dict[str, Any]],
    change: CurriculumChange,
    resolve_skills,
    demand: dict[str, float],
    demand_meta: dict[str, Any] | None = None,
    tsi_fn=None,
    base_context: dict[str, Any] | None = None,
    skill_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compare baseline curriculum against one simulated modification."""
    demand_meta = demand_meta or {}
    skill_names = skill_names or {}

    def supply_from(matrix) -> dict[str, float]:
        return {skill_names.get(k, k): v for k, v in matrix.supply.items()}

    base_matrix = build_course_skill_matrix(courses, resolve_skills)
    base_supply = supply_from(base_matrix)
    base_match = demand_weighted_match(base_supply, demand)

    updated, log = apply_change(courses, change, resolve_skills)
    new_matrix = build_course_skill_matrix(updated, resolve_skills)
    new_supply = supply_from(new_matrix)
    new_match = demand_weighted_match(new_supply, demand)

    base_gaps = compute_skill_gaps(demand, base_supply, demand_meta=demand_meta)
    new_gaps = compute_skill_gaps(demand, new_supply, demand_meta=demand_meta)

    def gap_map(result: dict[str, Any]) -> dict[str, float | None]:
        return {row["skill"]: row["gap"] for row in result["rows"]}

    base_gap_map, new_gap_map = gap_map(base_gaps), gap_map(new_gaps)
    closed: list[dict[str, Any]] = []
    for skill in sorted(set(base_gap_map) | set(new_gap_map)):
        b, n = base_gap_map.get(skill), new_gap_map.get(skill)
        if b is None or n is None:
            continue
        if abs(n - b) > 1e-6:
            closed.append(
                {
                    "skill": skill,
                    "gap_before": round(b, 4),
                    "gap_after": round(n, 4),
                    "change": round(n - b, 4),
                    "direction": "narrowed" if n < b else "widened",
                }
            )
    closed.sort(key=lambda r: r["change"])

    result: dict[str, Any] = {
        "scenario": change.to_dict(),
        "applied": log.get("applied", False),
        "matching_before": base_match,
        "matching_after": new_match,
        "base_supply": {k: round(v, 4) for k, v in base_supply.items()},
        "new_supply": {k: round(v, 4) for k, v in new_supply.items()},
        "base_channels": base_matrix.supply_channels,
        "new_channels": new_matrix.supply_channels,
        "gaps_before": base_gaps,
        "gaps_after": new_gaps,
        "matching_delta": (
            None
            if base_match["matching_score"] is None or new_match["matching_score"] is None
            else round(new_match["matching_score"] - base_match["matching_score"], 4)
        ),
        "skill_gap_index_before": base_gaps["skill_gap_index"],
        "skill_gap_index_after": new_gaps["skill_gap_index"],
        "gaps_changed": closed,
        "new_courses": [c["name"] for c in updated if c.get("simulated")],
        "assumptions": ASSUMPTIONS,
        "disclaimer": "模拟结果基于当前数据与模型假设，不是对未来就业的预测。",
        "evidence_level": "C",
    }
    if tsi_fn and base_context is not None:
        base_ctx = dict(base_context)
        base_ctx["matching"] = base_match
        base_ctx["gaps"] = base_gaps
        new_ctx = dict(base_context)
        new_ctx["matching"] = new_match
        new_ctx["gaps"] = new_gaps
        before, after = tsi_fn(base_ctx), tsi_fn(new_ctx)
        result["tsi_before"] = before.get("tsi_v2")
        result["tsi_after"] = after.get("tsi_v2")
        result["tsi_delta"] = (
            None
            if before.get("tsi_v2") is None or after.get("tsi_v2") is None
            else round(after["tsi_v2"] - before["tsi_v2"], 2)
        )
        result["tsi_before_detail"] = before
        result["tsi_after_detail"] = after
    return result
