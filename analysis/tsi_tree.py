"""Build the TSI Tree - the answer to "why is Primary TSI this number?".

The tree is a pure presentation/decomposition object built from the already
computed results; it recomputes nothing.  Structure (spec §35):

    Primary TSI
    └── 维度 (Knowledge/Skill/Capability/Practice-aligned dimensions)
        └── 指标 (F1..M4)
            └── 分量 (per demanded skill: Demand / Supply / Gap / Mapping)
                └── 证据 (evidence_id, source, level)

Every leaf that carries a number also carries its evidence id, so any node can
be traced back to a source document through the existing Evidence Chain.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def _round(value: Any, digits: int = 4) -> Any:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _skill_leaf(row: Mapping[str, Any], evidence_ids: Sequence[str] | None) -> dict[str, Any]:
    demand = _round(row.get("demand"))
    supply = _round(row.get("supply"))
    gap = _round(row.get("gap"))
    return {
        "id": f"skill:{row.get('skill')}",
        "name": str(row.get("skill")),
        "type": "component",
        "value": None if demand is None or supply is None else _round(min(supply, 1.0) * 100, 2),
        "demand": demand,
        "supply": supply,
        "gap": gap,
        "status": row.get("status"),
        "supply_basis": row.get("supply_basis"),
        "evidence_level": row.get("evidence_level"),
        "evidence_ids": list(evidence_ids or []),
        "children": [
            {"id": f"skill:{row.get('skill')}:demand", "name": "需求证据",
             "type": "evidence", "value": demand, "source": "招聘语料 Demand 向量"},
            {"id": f"skill:{row.get('skill')}:supply", "name": "供给证据",
             "type": "evidence", "value": supply,
             "source": "课程-技能矩阵 Supply 向量"},
            {"id": f"skill:{row.get('skill')}:gap", "name": "缺口 = 需求 − 供给",
             "type": "calculation", "value": gap},
        ],
    }


def build_tsi_tree(
    primary: Mapping[str, Any],
    *,
    fit: Mapping[str, Any] | None = None,
    gaps: Mapping[str, Any] | None = None,
    evidence_index: Mapping[str, Mapping[str, Any]] | None = None,
    max_skills: int = 40,
) -> dict[str, Any]:
    """Return a JSON-serialisable decomposition of the Primary TSI result."""
    evidence_index = evidence_index or {}
    fit = _normalize_fit(fit)
    metrics = {m.get("metric_id"): m for m in (primary.get("metrics") or [])}
    per_skill = {str(r.get("skill")): r for r in ((fit or {}).get("per_skill") or [])}

    def evidence_ids(*names: str) -> list[str]:
        found: list[str] = []
        for name in names:
            item = evidence_index.get(name) or {}
            ids = item.get("evidence_ids") if isinstance(item, Mapping) else None
            if ids:
                found.extend(str(i) for i in ids)
        return sorted(set(found))

    dimension_children: list[dict[str, Any]] = []
    for dim_id, dim in (primary.get("dimensions") or {}).items():
        indicator_children: list[dict[str, Any]] = []
        for metric in (primary.get("metrics") or []):
            spec_dim = _dimension_of(metric.get("metric_id"), primary)
            if spec_dim != dim_id:
                continue
            node: dict[str, Any] = {
                "id": metric.get("metric_id"),
                "name": metric.get("name"),
                "type": "indicator",
                "value": _round(metric.get("value"), 2),
                "status": metric.get("status"),
                "evidence_level": metric.get("evidence_level"),
                "evidence_ids": list(metric.get("evidence_ids") or []),
                "detail": metric.get("detail") or {},
                "children": [],
            }
            metric_id = metric.get("metric_id")
            if metric_id in {"F1", "F2", "F3", "F4"} and per_skill:
                rows = sorted(per_skill.values(), key=lambda r: -(r.get("demand") or 0))
                node["children"] = [
                    _skill_leaf(row, metric.get("evidence_ids"))
                    for row in rows[:max_skills]
                ]
            indicator_children.append(node)
        dimension_children.append({
            "id": dim_id,
            "name": dim.get("name"),
            "type": "dimension",
            "value": _round(dim.get("score"), 2),
            "weight": dim.get("weight"),
            "coverage": dim.get("coverage"),
            "confidence": dim.get("confidence"),
            "n_available": dim.get("n_available"),
            "n_total": dim.get("n_total"),
            "missing_indicators": dim.get("missing_indicators") or [],
            "children": indicator_children,
        })

    root = {
        "id": "primary_tsi",
        "name": "Primary TSI",
        "type": "root",
        "value": _round(primary.get("primary_tsi"), 2),
        "band": primary.get("band"),
        "version": primary.get("version"),
        "coverage": primary.get("weighted_coverage"),
        "confidence": primary.get("confidence"),
        "n_available": primary.get("n_available"),
        "n_total": primary.get("n_total"),
        "missing_indicators": primary.get("missing_indicators") or [],
        "excluded_dimensions": primary.get("excluded_dimensions") or {},
        "method_note": primary.get("method_note"),
        "children": dimension_children,
    }
    return {
        "root": root,
        "evidence_count": len(evidence_index),
        "metric_ids": sorted(k for k in metrics if k),
        "gap_count": len((gaps or {}).get("rows") or []),
    }


def _normalize_fit(fit: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Accept either a fit result or the ``{primary/peer/target: {...}}`` bundle."""
    if not fit:
        return {}
    if fit.get("per_skill") is not None:
        return fit
    for key in ("primary", "peer", "target"):
        candidate = fit.get(key)
        if isinstance(candidate, Mapping) and candidate.get("per_skill"):
            return candidate
    return fit


def _dimension_of(metric_id: str | None, primary: Mapping[str, Any]) -> str | None:
    """Map an indicator id to its dimension from the primary spec if available."""
    if not metric_id:
        return None
    try:
        from . import primary_tsi

        spec = primary_tsi.SPEC_BY_ID.get(metric_id)
        if spec:
            return spec.dimension
    except Exception:  # pragma: no cover - spec table is optional for display
        pass
    return None


def flatten_tree(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Depth-first flatten, keeping the parent id (useful for tables/exports)."""
    out: list[dict[str, Any]] = []

    def walk(node: Mapping[str, Any], parent: str | None) -> None:
        out.append({
            "id": node.get("id"), "parent": parent, "name": node.get("name"),
            "type": node.get("type"), "value": node.get("value"),
            "status": node.get("status"), "evidence_level": node.get("evidence_level"),
            "evidence_ids": node.get("evidence_ids") or [],
        })
        for child in node.get("children") or []:
            walk(child, str(node.get("id")))

    walk(tree.get("root") or {}, None)
    return out
