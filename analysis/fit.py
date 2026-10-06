"""Skill Fit - the single supply/demand comparison used by the whole engine.

Before this module the same comparison existed in two places (``matching.py``
for the report, and an indirect reuse inside the TSI indicators), which is how
the legacy TSI ended up weighting one matching result twice. From now on there
is exactly one implementation:

    Fit        = Σ_s Demand(s) · min(Supply(s), 1) / Σ_s Demand(s)
    Gap(s)     = Demand(s) − Supply(s)

``Fit`` is the level of适配, ``Gap`` is the signed per-skill difference computed
from the *same* vectors, so the two objects can never drift apart. ``matching``
and ``skill_gap`` both build on this module.

Missing data stays missing: a skill whose demand or supply is unknown is
reported with ``fit``/``gap`` = ``None`` and ``insufficient_evidence``, and is
excluded from both the numerator and the denominator.

One deliberate exception is controlled by ``unlisted_supply_is_zero``. When the
supply vector was built over the *same skill universe as the demand vector*
(i.e. we examined the whole curriculum against the demanded skills), a demanded
skill that never appears is not "unknown" - it is an observed supply of 0. The
engine turns this on for programme analysis so that "market-important skill,
never taught" shows up as a full gap instead of being silently dropped. Each
such row is labelled ``supply_basis='absent_in_scope'`` so the assumption is
auditable.
"""

from __future__ import annotations

from typing import Any, Mapping

DEFAULT_FIT_THRESHOLD = 0.0


def skill_fit(
    supply: Mapping[str, float | None],
    demand: Mapping[str, float | None],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    supply_provenance: str = "peer",
    supply_status: str = "ok",
    supply_reliability: str = "medium",
    supply_reason: str = "",
    unlisted_supply_is_zero: bool = False,
) -> dict[str, Any]:
    """Demand-weighted skill fit in [0, 1] with a per-skill audit trail."""
    demand_meta = demand_meta or {}
    rows: list[dict[str, Any]] = []
    num = 0.0
    den = 0.0
    comparable = 0
    uncovered = 0
    for skill in sorted(set(demand) | set(supply)):
        d = demand.get(skill)
        s = supply.get(skill)
        meta = demand_meta.get(skill) or {}
        supply_basis = "covered"
        if s is None and unlisted_supply_is_zero and supply_status == "ok":
            s = 0.0
            supply_basis = "absent_in_scope"
            uncovered += 1
        if d is None or s is None or supply_status != "ok":
            rows.append({
                "skill": skill,
                "demand": None if d is None else round(d, 4),
                "supply": None if s is None else round(s, 4),
                "fit_component": None,
                "gap": None,
                "status": "insufficient_evidence",
                "confidence": 0.0,
                "demand_tier": meta.get("tier"),
                "supply_basis": None,
            })
            continue
        d = float(d)
        s = float(s)
        covered = min(max(s, 0.0), 1.0)
        num += d * covered
        den += d
        comparable += 1
        gap = d - s
        rows.append({
            "skill": skill,
            "demand": round(d, 4),
            "supply": round(s, 4),
            "fit_component": round(d * covered, 4),
            "gap": round(gap, 4),
            "status": "ok",
            "confidence": round(float(meta.get("confidence") or 0.0), 4),
            "demand_tier": meta.get("tier"),
            "evidence_level": meta.get("evidence_level"),
            "supply_basis": supply_basis,
        })

    fit = (num / den) if den else None
    if supply_status != "ok":
        status = "insufficient_evidence"
    elif fit is None:
        status = "insufficient_evidence"
    else:
        status = "ok"

    weight_total = sum(float(v) for v in demand.values() if v)
    conf_num = sum(
        float((demand_meta.get(k) or {}).get("confidence") or 0.0) * float(v)
        for k, v in demand.items() if v and demand_meta.get(k)
    )
    confidence = round(conf_num / weight_total, 4) if weight_total else 0.0
    if supply_reliability == "low":
        confidence = round(confidence * 0.6, 4)

    return {
        "fit": None if fit is None else round(fit, 4),
        "fit_100": None if fit is None else round(fit * 100, 2),
        "status": status,
        "supply_provenance": supply_provenance,
        "supply_reliability": supply_reliability,
        "supply_reason": supply_reason,
        "n_skills_compared": comparable,
        "n_skills_total": len(rows),
        "n_uncovered_in_scope": uncovered,
        "coverage": round(comparable / len(rows), 4) if rows else 0.0,
        "confidence": confidence,
        "unlisted_supply_is_zero": unlisted_supply_is_zero,
        "per_skill": sorted(rows, key=lambda r: (-(r.get("demand") or 0), r["skill"])),
    }


def fit_gap_closure(fit_result: Mapping[str, Any]) -> dict[str, Any]:
    """Verify that every comparable row satisfies gap == demand − supply."""
    bad = []
    rows = list(fit_result.get("per_skill") or [])
    for row in rows:
        d, s, g = row.get("demand"), row.get("supply"), row.get("gap")
        if d is None or s is None or g is None:
            continue
        if abs((d - s) - g) > 1e-6:
            bad.append(row["skill"])
    return {
        "consistent": not bad,
        "n_rows": len(rows),
        "violations": bad,
        "note": "Fit 与 Gap 由同一 Supply/Demand 向量导出，本检查用于证明两者闭合。",
    }
