"""Simulation 重新定位为决策辅助（spec §19、§41）。

Simulation 不是 Agent 的上级约束，而是 Agent 提出方案之后的**量化验证**：

    Agent（证据/政策/产业/教育逻辑）→ 可形式化的方案 → Simulation
    → ΔFit / ΔTSI / 缺口减少 → 回到 Agent 解释

因此本模块只接受"已经提出的方案"，把它们写成 supply 增量，重算受影响的
Fit/Gap，并给出**明确标注为近似**的 ΔTSI。写不成优化变量的建议照样可以提出，
只是没有量化结果 - 不会被 Simulation 拦下。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import fit as fit_mod

#: F1 在 Primary TSI 中的绝对权重 = F 维权重 0.40 × F1 维内权重 0.45。
F1_ABSOLUTE_WEIGHT = 0.40 * 0.45


@dataclass
class Intervention:
    """一个可形式化的培养方案措施。"""

    name: str
    supply_delta: dict[str, float] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "supply_delta": dict(self.supply_delta), "note": self.note}


def quantify_intervention(
    supply: Mapping[str, float | None],
    demand: Mapping[str, float | None],
    intervention: Intervention | Mapping[str, Any],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    baseline_fit_100: float | None = None,
    supply_provenance: str = "target",
    supply_reliability: str = "medium",
) -> dict[str, Any]:
    """量化单个方案：新增供给 → ΔFit → ΔGap → 近似 ΔTSI。"""
    item = (intervention if isinstance(intervention, Intervention)
            else Intervention(name=str(intervention.get("name") or "方案"),
                              supply_delta={str(k): float(v) for k, v in
                                            (intervention.get("supply_delta") or {}).items()
                                            if isinstance(v, (int, float))},
                              note=str(intervention.get("note") or "")))
    before = fit_mod.skill_fit(
        supply, demand, demand_meta=demand_meta or {},
        supply_provenance=supply_provenance, supply_reliability=supply_reliability,
        unlisted_supply_is_zero=True,
    )
    updated: dict[str, float | None] = dict(supply)
    for skill, delta in item.supply_delta.items():
        base = updated.get(skill)
        base = 0.0 if base is None else float(base)
        updated[skill] = min(base + float(delta), 1.0)
    after = fit_mod.skill_fit(
        updated, demand, demand_meta=demand_meta or {},
        supply_provenance=supply_provenance, supply_reliability=supply_reliability,
        unlisted_supply_is_zero=True,
    )
    before_100 = before.get("fit_100")
    after_100 = after.get("fit_100")
    delta_fit = (None if before_100 is None or after_100 is None
                 else round(after_100 - before_100, 2))
    delta_tsi = (None if delta_fit is None
                 else round(delta_fit * F1_ABSOLUTE_WEIGHT, 2))

    residual = []
    for row in after.get("per_skill") or []:
        gap = row.get("gap")
        if gap is None or gap <= 0.05:
            continue
        residual.append({"skill": row["skill"], "demand": row.get("demand"),
                         "supply": row.get("supply"), "gap": round(gap, 4)})
    residual.sort(key=lambda r: -(r["gap"] or 0))
    return {
        "name": item.name,
        "fit_100_before": before_100,
        "fit_100_after": after_100,
        "delta_fit_100": delta_fit,
        "delta_tsi_estimate": delta_tsi,
        "gaps_closed": (sum(1 for r in (before.get("per_skill") or []) if (r.get("gap") or 0) > 0.05)
                        - len(residual)),
        "residual_gaps": residual[:10],
        "supply_delta": dict(item.supply_delta),
        "note": item.note or "方案量化是近似：ΔTSI 只按 F1 的绝对权重折算，其他维度视为不变。",
        "approximation": ("ΔTSI ≈ ΔSkillFit × 0.18；真实 TSI 变化还取决于该方案对"
                          "S/O/M 维的间接影响与数据可用性。"),
    }


def compare_interventions(
    supply: Mapping[str, float | None],
    demand: Mapping[str, float | None],
    interventions: Sequence[Intervention | Mapping[str, Any]],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    include_combination: bool = True,
) -> dict[str, Any]:
    """比较多个方案，并按需给出"A+B"组合方案。"""
    rows = [quantify_intervention(supply, demand, item, demand_meta=demand_meta)
            for item in interventions]
    if include_combination and len(rows) > 1:
        merged: dict[str, float] = {}
        for item in interventions:
            delta = (item.supply_delta if isinstance(item, Intervention)
                     else item.get("supply_delta") or {})
            for skill, value in delta.items():
                if isinstance(value, (int, float)):
                    merged[str(skill)] = merged.get(str(skill), 0.0) + float(value)
        combined = quantify_intervention(
            supply, demand,
            Intervention(name=" + ".join(str(item.name if isinstance(item, Intervention)
                                          else item.get("name")) for item in interventions),
                         supply_delta=merged, note="组合方案（各子方案供给增量相加）"),
            demand_meta=demand_meta)
        rows.append(combined)
    rows.sort(key=lambda r: -(r.get("delta_fit_100") or 0))
    return {
        "scenarios": rows,
        "best": rows[0]["name"] if rows else None,
        "role": "decision_support",
        "note": ("Simulation 只对已提出的方案做量化验证，不对 Agent 的建议范围设限；"
                 "无法形式化的建议仍可提出，只是没有量化结果。"),
    }
