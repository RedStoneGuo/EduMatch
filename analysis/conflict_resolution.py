"""Evidence Conflict Resolver (spec §18).

The engine results and the raw source evidence can disagree - the known case is
"Python supply = 0" while the programme's course material explicitly teaches
Python.  That is a *mapping* problem, not a capability problem:

    Engine Result → Evidence Cross-check → high-level evidence conflict
    → Skill Mapping Review → local correction → Recompute (affected skills only)
    → keep old + new result → record the reason

This module detects such conflicts and produces the audit record the spec
demands: ``original_result`` / ``reconciled_result`` / ``evidence_source`` /
``mapping_reason`` / ``changed_skill`` / ``recalculation_scope`` /
``timestamp`` / ``run_id``.  It never silently rewrites a whole run: only the
affected skills are corrected and only those contributions are recomputed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from . import fit as fit_mod

HIGH_LEVELS = ("A", "B")


@dataclass
class Conflict:
    skill: str
    engine_value: float | None
    source_value: float | None
    source_level: str
    source_evidence_id: str
    source_quote: str = ""
    kind: str = "engine_under_reports_source"   # or over_reports / missing_vs_present
    severity: str = "conflict"
    mapping_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconcileRecord:
    changed_skill: str
    original_result: float | None
    reconciled_result: float | None
    evidence_source: str
    evidence_level: str
    mapping_reason: str
    recalculation_scope: list[str]
    run_id: str
    timestamp: str
    resolution: str = "source_evidence_overrides_engine"
    previous_weight: float | None = None
    source_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_conflicts(
    supply: Mapping[str, float | None],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    present_threshold: float = 0.05,
    only_high_levels: bool = True,
) -> list[Conflict]:
    """Find skills where high-level raw evidence contradicts the engine output."""
    out: list[Conflict] = []
    for skill, item in evidence.items():
        level = str(item.get("evidence_level") or "D")
        if only_high_levels and level not in HIGH_LEVELS:
            continue
        source_value = item.get("value")
        engine_value = supply.get(skill)
        try:
            source_float = None if source_value is None else float(source_value)
        except (TypeError, ValueError):
            source_float = None
        engine_float = None if engine_value is None else float(engine_value)
        if source_float is None:
            continue
        if engine_float is None:
            kind = "missing_vs_present"
        elif engine_float < present_threshold <= source_float:
            kind = "engine_under_reports_source"
        elif source_float < present_threshold <= engine_float:
            kind = "engine_over_reports_source"
        else:
            continue
        out.append(Conflict(
            skill=skill, engine_value=engine_float, source_value=source_float,
            source_level=level,
            source_evidence_id=str(item.get("evidence_id") or ""),
            source_quote=str(item.get("quote") or ""),
            kind=kind,
            mapping_reason=str(item.get("mapping_reason")
                               or "原始课程材料明确出现该技能，结构化映射未命中上游映射规则"),
        ))
    return sorted(out, key=lambda c: c.skill)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_conflicts(
    supply: Mapping[str, float | None],
    demand: Mapping[str, float | None],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    supply_provenance: str = "target",
    supply_status: str = "ok",
    supply_reliability: str = "medium",
    unlisted_supply_is_zero: bool = False,
    run_id: str = "",
    timestamp: str | None = None,
    present_threshold: float = 0.05,
) -> dict[str, Any]:
    """Detect, apply and audit conflicts; recompute only affected contributions."""
    conflicts = detect_conflicts(supply, evidence, present_threshold=present_threshold)
    if not conflicts:
        return {
            "status": "no_conflict",
            "changed_skills": [],
            "recalculation_scope": [],
            "records": [],
            "original_supply": {k: v for k, v in supply.items()},
            "reconciled_supply": {k: v for k, v in supply.items()},
            "original_result": _fit(supply, demand, demand_meta, supply_provenance,
                                    supply_status, supply_reliability, unlisted_supply_is_zero),
            "reconciled_result": _fit(supply, demand, demand_meta, supply_provenance,
                                      supply_status, supply_reliability, unlisted_supply_is_zero),
            "run_id": run_id,
            "timestamp": timestamp or _now(),
        }

    corrected: dict[str, float | None] = dict(supply)
    changed = sorted({c.skill for c in conflicts})
    records: list[ReconcileRecord] = []
    for conflict in conflicts:
        corrected[conflict.skill] = conflict.source_value
        records.append(ReconcileRecord(
            changed_skill=conflict.skill,
            original_result=conflict.engine_value,
            reconciled_result=conflict.source_value,
            evidence_source=conflict.source_evidence_id,
            evidence_level=conflict.source_level,
            mapping_reason=conflict.mapping_reason,
            recalculation_scope=[conflict.skill],
            run_id=run_id,
            timestamp=timestamp or _now(),
            resolution="source_evidence_overrides_engine",
            previous_weight=conflict.source_value,
            source_value=conflict.source_value,
        ))

    before = _fit(supply, demand, demand_meta, supply_provenance, supply_status,
                  supply_reliability, unlisted_supply_is_zero)
    after = _fit(corrected, demand, demand_meta, supply_provenance, supply_status,
                 supply_reliability, unlisted_supply_is_zero)
    return {
        "status": "reconciled",
        "changed_skills": changed,
        "recalculation_scope": changed,
        "records": [r.to_dict() for r in records],
        "conflicts": [c.to_dict() for c in conflicts],
        "original_supply": {k: v for k, v in supply.items()},
        "reconciled_supply": corrected,
        "original_result": before,
        "reconciled_result": after,
        "delta_fit_100": (None if before.get("fit_100") is None or after.get("fit_100") is None
                          else round(after["fit_100"] - before["fit_100"], 2)),
        "run_id": run_id,
        "timestamp": timestamp or _now(),
        "policy": "只重算受影响技能及其上层指标；不因单个 Skill 冲突而重跑整个系统。",
    }


def _fit(
    supply: Mapping[str, float | None],
    demand: Mapping[str, float | None],
    demand_meta: Mapping[str, Any] | None,
    supply_provenance: str,
    supply_status: str,
    supply_reliability: str,
    unlisted_supply_is_zero: bool,
) -> dict[str, Any]:
    result = fit_mod.skill_fit(
        supply, demand, demand_meta=demand_meta or {},
        supply_provenance=supply_provenance, supply_status=supply_status,
        supply_reliability=supply_reliability,
        unlisted_supply_is_zero=unlisted_supply_is_zero,
    )
    return {"fit": result.get("fit"), "fit_100": result.get("fit_100"),
            "n_skills_compared": result.get("n_skills_compared")}
