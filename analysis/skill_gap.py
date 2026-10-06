"""Skill Gap Index.

    Gap(skill) = Demand(skill) − Supply(skill)

A missing side is reported as ``status='insufficient_evidence'`` with
``gap=None``. It is never coerced to zero, because "we do not know" and
"there is no gap" are different research findings.

Aggregate severity is demand-weighted and only counts positive gaps:

    SkillGapIndex = Σ_s Demand(s) · max(Gap(s), 0) / Σ_s Demand(s)

``unlisted_supply_is_zero`` mirrors ``analysis.fit``: inside one examined
curriculum scope a demanded skill that never appears is an observed 0, not an
unknown. Such rows carry ``supply_basis='absent_in_scope'`` so the assumption is
visible in every downstream report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

DEFAULT_GAP_THRESHOLD = 0.15
DEFAULT_MATERIAL_THRESHOLD = 0.20


@dataclass
class SkillGapRow:
    skill: str
    demand: float | None
    supply: float | None
    gap: float | None
    status: str
    severity: str
    confidence: float
    evidence_level: str
    demand_tier: str | None = None
    evidence_chain: list[str] = field(default_factory=list)
    supply_basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "demand": None if self.demand is None else round(self.demand, 4),
            "supply": None if self.supply is None else round(self.supply, 4),
            "gap": None if self.gap is None else round(self.gap, 4),
            "status": self.status,
            "severity": self.severity,
            "confidence": round(self.confidence, 4),
            "evidence_level": self.evidence_level,
            "demand_tier": self.demand_tier,
            "evidence_chain": self.evidence_chain,
            "supply_basis": self.supply_basis,
        }


def _severity(gap: float | None, demand: float | None) -> str:
    if gap is None or demand is None:
        return "unknown"
    if gap >= 0.35 and demand >= 0.6:
        return "critical"
    if gap >= DEFAULT_MATERIAL_THRESHOLD and demand >= 0.4:
        return "material"
    if gap > DEFAULT_GAP_THRESHOLD:
        return "moderate"
    if gap < -DEFAULT_GAP_THRESHOLD:
        return "oversupply"
    return "balanced"


def compute_skill_gaps(
    demand: Mapping[str, float | None],
    supply: Mapping[str, float | None],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
    unlisted_supply_is_zero: bool = False,
) -> dict[str, Any]:
    demand_meta = demand_meta or {}
    skills = sorted(set(demand) | set(supply))
    rows: list[SkillGapRow] = []
    for skill in skills:
        d = demand.get(skill)
        s = supply.get(skill)
        meta = demand_meta.get(skill) or {}
        supply_basis: str | None = "covered"
        if s is None and unlisted_supply_is_zero and d is not None:
            s = 0.0
            supply_basis = "absent_in_scope"
        if d is None and s is None:
            status, gap, level = "insufficient_evidence", None, "E"
        elif d is None:
            status, gap, level = "insufficient_evidence", None, "E"
        elif s is None:
            status, gap, level, supply_basis = "insufficient_evidence", None, "E", None
        else:
            gap = d - s
            level = meta.get("evidence_level", "C")
            if gap > gap_threshold:
                status = "gap"
            elif gap < -gap_threshold:
                status = "oversupply"
            else:
                status = "balanced"
        chain = [f"demand[{skill}]", f"supply[{skill}]", f"gap[{skill}]"]
        rows.append(
            SkillGapRow(
                skill=skill,
                demand=d,
                supply=s,
                gap=gap,
                status=status,
                severity=_severity(gap, d),
                confidence=float(meta.get("confidence", 0.0)) if gap is not None else 0.0,
                evidence_level=level if gap is not None else "E",
                demand_tier=meta.get("tier"),
                evidence_chain=chain if gap is not None else ["insufficient_evidence"],
                supply_basis=supply_basis if gap is not None else None,
            )
        )
    comparable = [r for r in rows if r.gap is not None]
    den = sum(r.demand for r in comparable if r.demand)
    index = (sum(r.demand * max(r.gap, 0.0) for r in comparable if r.demand) / den) if den else None
    n_absent = sum(1 for r in comparable if r.supply_basis == "absent_in_scope")
    return {
        "skill_gap_index": None if index is None else round(index, 4),
        "skill_gap_index_100": None if index is None else round(index * 100, 2),
        "n_skills": len(rows),
        "n_comparable": len(comparable),
        "n_insufficient": len(rows) - len(comparable),
        "n_supply_absent_in_scope": n_absent,
        "coverage": round(len(comparable) / len(rows), 4) if rows else 0.0,
        "rows": [r.to_dict() for r in sorted(rows, key=lambda r: (r.status != "gap", -(r.gap or -9)))],
        "method_note": (
            "Gap = Demand − Supply，两侧取自同一向量；在课程口径内未出现的需求技能记为"
            "供给 0（supply_basis=absent_in_scope），需求侧缺失仍记 null。"
        ),
    }


def top_gaps(result: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return [r for r in result["rows"] if r["status"] == "gap"][:limit]
