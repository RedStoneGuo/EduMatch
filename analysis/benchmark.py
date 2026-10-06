"""Cross-school / cross-major benchmarking with explicit sample disclosure.

Rankings are only emitted when the sample size passes ``min_n``; otherwise the
result is returned as ``insufficient_evidence`` with the raw observations.
"""

from __future__ import annotations

from statistics import mean, median
from typing import Any, Iterable, Sequence

DEFAULT_DIRECTION = "higher_is_better"


def _values(records: Sequence[dict], metric: str) -> list[float]:
    out = []
    for r in records:
        v = r.get(metric)
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def benchmark_table(
    records: Sequence[dict],
    metrics: Sequence[str],
    *,
    entity_key: str = "school",
    min_n: int = 3,
    direction: str = DEFAULT_DIRECTION,
) -> dict[str, Any]:
    entities: dict[str, dict[str, Any]] = {}
    for r in records:
        entity = str(r.get(entity_key) or "未知")
        bucket = entities.setdefault(entity, {"entity": entity, "metrics": {}, "n_records": 0})
        bucket["n_records"] += 1
        for metric in metrics:
            v = r.get(metric)
            if isinstance(v, (int, float)):
                bucket["metrics"].setdefault(metric, []).append(float(v))

    stats = {m: _values(records, m) for m in metrics}
    benchmarks = {}
    for m, vals in stats.items():
        benchmarks[m] = {
            "n": len(vals),
            "mean": round(mean(vals), 4) if vals else None,
            "median": round(median(vals), 4) if vals else None,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        }

    rows: list[dict[str, Any]] = []
    for entity, bucket in entities.items():
        row: dict[str, Any] = {"entity": entity, "n_records": bucket["n_records"]}
        missing: list[str] = []
        for metric in metrics:
            vals = bucket["metrics"].get(metric, [])
            if vals:
                row[metric] = round(mean(vals), 4)
                bench = benchmarks[metric]["median"]
                row[f"{metric}_vs_median"] = None if bench in (None, 0) else round(mean(vals) - bench, 4)
                if len(vals) < min_n:
                    row.setdefault("small_sample_metrics", []).append(metric)
            else:
                row[metric] = None
                missing.append(metric)
        row["missing_metrics"] = missing
        rows.append(row)

    rankable = all(benchmarks[m]["n"] >= min_n for m in metrics) and len(rows) >= 2
    primary = metrics[0] if metrics else None
    if rankable and primary:
        rows.sort(key=lambda r: (r[primary] is None, -(r[primary] or 0) if direction == "higher_is_better" else (r[primary] or 0)))
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
    return {
        "entities": rows,
        "benchmarks": benchmarks,
        "rankable": rankable,
        "min_n": min_n,
        "sample_note": (
            f"每个指标的样本量见 benchmarks；样本量小于 {min_n} 的单元格不做排序结论。"
        ),
        "metrics": list(metrics),
    }


def radar_data(row: dict[str, Any], metrics: Sequence[str]) -> dict[str, Any]:
    """Values normalised to 0-1 for radar charts, missing kept as null."""
    vals = [row.get(m) for m in metrics]
    present = [v for v in vals if isinstance(v, (int, float))]
    if not present:
        return {"labels": list(metrics), "values": [None] * len(metrics)}
    top = max(present) or 1.0
    return {
        "labels": list(metrics),
        "values": [None if v is None else round(float(v) / top, 4) for v in vals],
        "scale_max": top,
    }


def skill_benchmark(
    *,
    demand: dict[str, float | None],
    target_supply: dict[str, float | None] | None,
    peer_supply: dict[str, float | None],
    target_gaps: dict[str, float | None] | None = None,
    peer_gaps: dict[str, float | None] | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    """Skill-level benchmark: target institution vs regional peer pool vs market.

    This replaces "school ranking on employment rates" with the comparison the
    research question needs: under the *same* industry demand, why does this
    institution produce a different supply structure than its peers?
    """
    target_supply = target_supply or {}
    target_gaps = target_gaps or {}
    peer_gaps = peer_gaps or {}
    skills = sorted(
        set(demand) | set(target_supply) | set(peer_supply),
        key=lambda s: (-(demand.get(s) or 0), s),
    )[:limit]
    rows: list[dict[str, Any]] = []
    for skill in skills:
        t = target_supply.get(skill)
        p = peer_supply.get(skill)
        row = {
            "skill": skill,
            "market_demand": None if demand.get(skill) is None else round(demand[skill], 4),
            "target_supply": None if t is None else round(t, 4),
            "peer_supply": None if p is None else round(p, 4),
            "target_gap": None if target_gaps.get(skill) is None else round(target_gaps[skill], 4),
            "peer_gap": None if peer_gaps.get(skill) is None else round(peer_gaps[skill], 4),
            "target_vs_peer": None if (t is None or p is None) else round(t - p, 4),
            "status": "insufficient_evidence",
        }
        if row["market_demand"] is None:
            row["reading"] = "该技能无市场需求数据，仅作参考"
        elif row["target_supply"] is None:
            row["status"] = "insufficient_evidence"
            row["reading"] = "目标高校缺少该技能的可核查课程证据（不得用同类基准替代）"
        elif row["target_supply"] < row["market_demand"] - 0.15:
            row["status"] = "target_gap"
            row["reading"] = "目标高校供给低于市场需求"
        elif row["target_vs_peer"] is not None and row["target_vs_peer"] < -0.15:
            row["status"] = "below_peer"
            row["reading"] = "目标高校供给低于北京同类专业基准"
        elif row["target_vs_peer"] is not None and row["target_vs_peer"] > 0.15:
            row["status"] = "above_peer"
            row["reading"] = "目标高校供给高于北京同类专业基准"
        else:
            row["status"] = "consistent"
            row["reading"] = "与市场需求和同类基准基本一致"
        rows.append(row)
    return {
        "rows": rows,
        "metrics": ["market_demand", "target_supply", "peer_supply", "target_gap", "peer_gap"],
        "n_rows": len(rows),
        "n_target_gap": sum(1 for r in rows if r["status"] == "target_gap"),
        "n_below_peer": sum(1 for r in rows if r["status"] == "below_peer"),
        "note": (
            "技能级基准：目标高校供给 / 北京同类专业基准 / 市场需求三者并列；"
            "目标高校缺证据的单元格保持 null，不使用基准值顶替。"
        ),
    }


def triangle(
    *,
    target: dict[str, Any],
    peer: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, Any]:
    """目标高校 vs 北京同类专业基准 vs 市场需求 的画像对比（非排行榜）。"""
    def _get(bucket: dict[str, Any], *path: str) -> Any:
        cur: Any = bucket
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    rows = [
        {"dimension": "供给范围", "target": target.get("scope"), "peer": peer.get("scope"),
         "market": market.get("scope")},
        {"dimension": "可核查课程数", "target": target.get("n_courses"),
         "peer": peer.get("n_courses"), "market": None},
        {"dimension": "技能供给可靠性", "target": target.get("reliability"),
         "peer": peer.get("reliability"), "market": market.get("reliability")},
        {"dimension": "Skill Fit", "target": _get(target, "fit", "fit_100"),
         "peer": _get(peer, "fit", "fit_100"), "market": None},
        {"dimension": "Skill Gap Index", "target": _get(target, "gap", "skill_gap_index"),
         "peer": _get(peer, "gap", "skill_gap_index"), "market": None},
        {"dimension": "岗位样本数", "target": None, "peer": None,
         "market": market.get("n_effective_jobs")},
    ]
    findings: list[str] = []
    t_fit, p_fit = _get(target, "fit", "fit_100"), _get(peer, "fit", "fit_100")
    if t_fit is None:
        findings.append("目标高校供给证据不足，无法给出该校 Skill Fit（不得用同类基准替代）")
    elif p_fit is not None:
        delta = round(t_fit - p_fit, 2)
        findings.append(
            f"目标高校 Skill Fit {t_fit}，北京同类专业基准 {p_fit}，差值 {delta:+}"
            "（差异解释优先于排序）"
        )
    t_gap, p_gap = _get(target, "gap", "skill_gap_index"), _get(peer, "gap", "skill_gap_index")
    if t_gap is not None and p_gap is not None:
        findings.append(
            f"Skill Gap Index 目标 {t_gap} vs 基准 {p_gap}"
            f"（{'高于' if t_gap > p_gap else '低于或等于'}基准）"
        )
    return {
        "rows": rows,
        "findings": findings,
        "label": "目标高校 VS 北京同类专业基准 VS 市场需求",
        "note": "三角比较用于解释差异来源，不产出高校排行榜。",
    }
