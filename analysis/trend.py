"""Time-dimension analysis over real, dated observations only.

Two rules keep this module from producing "trends" that are not trends:

1. repeated observations inside the same year are collapsed (median) and the
   per-year sample size is published - a year is a period, not a sample;
2. a series needs at least ``min_periods`` **distinct** years. Otherwise the
   result is ``insufficient_evidence`` and no change value is emitted (the old
   behaviour reported "2022→2022 变化 0.47").

The module also answers the question the competition actually asks: is the
change in market skill demand being answered by a change in curriculum
coverage? ``response_analysis`` compares the two directions and refuses to
conclude when either side has no usable series.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Iterable, Mapping, Sequence


def dedupe_periods(points: Iterable[tuple[int, float]]) -> list[tuple[int, float, int]]:
    """Collapse same-year observations into one period (median) + sample size."""
    buckets: dict[int, list[float]] = {}
    for year, value in points:
        if year is None or value is None:
            continue
        buckets.setdefault(int(year), []).append(float(value))
    return [(year, median(vals), len(vals)) for year, vals in sorted(buckets.items())]


def build_series(points: Iterable[tuple[int, float]]) -> list[tuple[int, float]]:
    return [(y, v) for y, v, _n in dedupe_periods(points)]


def series_summary(
    points: Sequence[tuple[int, float]],
    *,
    label: str = "",
    min_periods: int = 2,
) -> dict[str, Any]:
    periods = dedupe_periods(points)
    series = [{"year": y, "value": round(v, 4), "n_samples": n} for y, v, n in periods]
    if len(periods) < min_periods:
        same_year = len(periods) == 1 and periods[0][2] > 1
        return {
            "label": label,
            "status": "insufficient_evidence",
            "n_periods": len(periods),
            "n_observations": sum(n for _, _, n in periods),
            "series": series,
            "reason": (
                f"仅 {len(periods)} 个不同年份"
                + (f"（同一年内有 {periods[0][2]} 条重复观测，已取中位数，不构成趋势）"
                   if same_year else "")
                + f"，少于 {min_periods} 期，不输出趋势结论"
            ),
            "cagr": None,
            "change": None,
        }
    first_year, first, _ = periods[0]
    last_year, last, _ = periods[-1]
    span = max(last_year - first_year, 1)
    change = last - first
    cagr = (last / first) ** (1 / span) - 1 if first > 0 and last > 0 else None
    return {
        "label": label,
        "status": "ok",
        "n_periods": len(periods),
        "n_observations": sum(n for _, _, n in periods),
        "series": series,
        "first_year": first_year,
        "last_year": last_year,
        "change": round(change, 4),
        "change_pct": round(change / first, 4) if first else None,
        "cagr": None if cagr is None else round(cagr, 4),
        "direction": "up" if change > 0 else "down" if change < 0 else "flat",
        "evidence_level": "B" if len(periods) >= 3 else "C",
        "caveat": "时间序列为公开数据点，未做因果识别；仅描述变化方向与幅度。",
    }


def compare_periods(
    current: Mapping[str, float], previous: Mapping[str, float], *, label: str = ""
) -> dict[str, Any]:
    skills = sorted(set(current) | set(previous))
    rows = []
    for skill in skills:
        c = current.get(skill)
        p = previous.get(skill)
        rows.append({
            "skill": skill,
            "current": None if c is None else round(c, 4),
            "previous": None if p is None else round(p, 4),
            "delta": None if (c is None or p is None) else round(c - p, 4),
            "status": "ok" if (c is not None and p is not None) else "insufficient_evidence",
        })
    return {"label": label, "rows": rows}


def response_analysis(
    market: Mapping[str, Any],
    curriculum: Mapping[str, Any],
    *,
    skill: str = "",
) -> dict[str, Any]:
    """Is the market's change being answered by a change in what is taught?"""
    m_status, c_status = market.get("status"), curriculum.get("status")
    if m_status != "ok" or c_status != "ok":
        return {
            "skill": skill or None,
            "status": "insufficient_evidence",
            "market_status": m_status,
            "curriculum_status": c_status,
            "reason": "市场侧或培养侧没有可用的多期数据，无法判断培养体系是否同步响应",
            "market": market,
            "curriculum": curriculum,
            "label": "响应关系（关联，非因果）",
        }
    m_dir, c_dir = market.get("direction"), curriculum.get("direction")
    if m_dir == "up" and c_dir in {"flat", "down"}:
        conclusion = "市场技能需求上升，而课程覆盖未同步上升：存在响应滞后或覆盖不足"
    elif m_dir == "down" and c_dir == "up":
        conclusion = "市场技能需求下降而课程覆盖上升：需检查供给是否过剩"
    elif m_dir == c_dir:
        conclusion = (
            "市场技能需求与课程覆盖同向变化：培养体系呈现同步响应"
            if m_dir == "up" and c_dir == "up"
            else "市场与课程变化方向一致，未发现结构性偏离"
        )
    else:
        conclusion = "市场与课程变化方向不一致，需要进一步核查口径"
    return {
        "skill": skill or None,
        "status": "ok",
        "market_direction": m_dir,
        "curriculum_direction": c_dir,
        "synchronised": m_dir == c_dir,
        "market_change": market.get("change"),
        "curriculum_change": curriculum.get("change"),
        "conclusion": conclusion,
        "label": "响应关系（关联，非因果）",
        "caveat": "仅为方向性关联描述，未做因果识别。",
    }
