"""Mechanism analysis: association, regression, importance.

Statistical association is not causal identification. All narrative helpers
rewrite causal verbs so that Agent output stays defensible.
"""

from __future__ import annotations

import math
import re
from typing import Any, Sequence

import numpy as np

CAUSAL_PATTERNS = [
    (r"政策导致", "政策与……呈现关联"),
    (r"导致", "与……呈现关联"),
    (r"决定了", "在模型中具有较高解释贡献"),
    (r"说明了.*必然", "提示可能存在……路径"),
    (r"证明", "提示"),
    (r"必然", "可能"),
]


def guard_causal_language(text: str) -> str:
    out = text
    for pattern, replacement in CAUSAL_PATTERNS:
        out = re.sub(pattern, replacement, out)
    return out


def _to_array(values: Sequence[float | None]) -> np.ndarray:
    """None -> NaN so that mask-based row dropping works uniformly."""
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def pearson(x: Sequence[float], y: Sequence[float]) -> dict[str, Any]:
    pairs = [(float(a), float(b)) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3:
        return {"r": None, "n": len(pairs), "status": "insufficient_evidence", "p_value": None}
    xs = np.array([p[0] for p in pairs])
    ys = np.array([p[1] for p in pairs])
    if xs.std() == 0 or ys.std() == 0:
        return {"r": None, "n": len(pairs), "status": "insufficient_evidence", "p_value": None,
                "reason": "零方差"}
    r = float(np.corrcoef(xs, ys)[0, 1])
    # two-sided t approximation
    n = len(pairs)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = r * math.sqrt((n - 2) / max(1 - r * r, 1e-12))
    from math import erf
    p = 2 * (1 - 0.5 * (1 + erf(abs(t) / math.sqrt(2))))
    return {
        "r": round(r, 4),
        "n": n,
        "p_value_approx": round(float(p), 4),
        "status": "ok",
        "caveat": "相关不等于因果；未做因果识别。",
    }


def spearman(x: Sequence[float], y: Sequence[float]) -> dict[str, Any]:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 5:
        return {"rho": None, "n": len(pairs), "status": "insufficient_evidence"}

    def rank(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = rank([float(p[0]) for p in pairs]), rank([float(p[1]) for p in pairs])
    return pearson(rx, ry) | {"rho": pearson(rx, ry).get("r")}


def ols(features: dict[str, Sequence[float]], target: Sequence[float]) -> dict[str, Any]:
    names = list(features)
    y = _to_array(target)
    cols = [_to_array(features[n]) for n in names]
    n = len(y)
    if n < len(names) + 2 or any(len(c) != n for c in cols):
        return {"status": "insufficient_evidence", "n": n, "coefficients": {}}
    mask = ~np.isnan(y) & np.all([~np.isnan(c) for c in cols], axis=0)
    n_eff = int(mask.sum())
    if n_eff < len(names) + 2:
        return {"status": "insufficient_evidence", "n": n_eff, "coefficients": {}}
    design = np.column_stack([np.ones(n_eff)] + [c[mask] for c in cols])
    yy = y[mask]
    beta, *_ = np.linalg.lstsq(design, yy, rcond=None)
    pred = design @ beta
    ss_res = float(((yy - pred) ** 2).sum())
    ss_tot = float(((yy - yy.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    return {
        "status": "ok",
        "n": n_eff,
        "r2": None if r2 is None else round(r2, 4),
        "intercept": round(float(beta[0]), 4),
        "coefficients": {name: round(float(b), 4) for name, b in zip(names, beta[1:])},
        "caveat": "OLS 系数解释为条件关联，不代表因果效应。",
    }


def permutation_importance(
    features: dict[str, Sequence[float]],
    target: Sequence[float],
    *,
    n_repeats: int = 20,
    seed: int = 7,
) -> dict[str, Any]:
    """Model-agnostic importance using a shallow random forest (sklearn optional)."""
    try:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import cross_val_score
    except Exception:  # noqa: BLE001
        return {"status": "sklearn_unavailable", "importance": {}}
    names = list(features)
    X = np.column_stack([_to_array(features[n]) for n in names])
    y = _to_array(target)
    mask = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    X, y = X[mask], y[mask]
    if len(y) < 12:
        return {"status": "insufficient_evidence", "n": int(len(y)), "importance": {}}
    model = RandomForestRegressor(n_estimators=200, max_depth=4, random_state=seed)
    model.fit(X, y)
    base = model.score(X, y)
    rng = np.random.default_rng(seed)
    importance: dict[str, float] = {}
    for j, name in enumerate(names):
        drops = []
        for _ in range(n_repeats):
            Xp = X.copy()
            rng.shuffle(Xp[:, j])
            drops.append(base - model.score(Xp, y))
        importance[name] = round(float(np.mean(drops)), 4)
    cv = cross_val_score(model, X, y, cv=min(5, max(3, len(y) // 6)), scoring="r2")
    return {
        "status": "ok",
        "n": int(len(y)),
        "importance": dict(sorted(importance.items(), key=lambda kv: -kv[1])),
        "in_sample_r2": round(float(base), 4),
        "cv_r2_mean": round(float(cv.mean()), 4),
        "caveat": "重要性反映模型内解释贡献，不构成因果路径证明。",
    }


def association_path(
    *,
    policy_topics: Sequence[str],
    policy_skills: Sequence[str],
    demand: dict[str, float | None],
    supply: dict[str, float | None],
    gaps: dict[str, float | None] | None = None,
    industry_counts: dict[str, int] | None = None,
    top_skills: int = 10,
    min_demand: float = 0.15,
) -> dict[str, Any]:
    """政策 → 产业方向 → 岗位技能 → 课程覆盖 → 缺口 的关联路径。

    This is the part of the mechanism analysis that *is* computable with the
    current data. It links the policy corpus (topics and the skills its text
    mentions) to the market demand vector ({skill: demand}) and the curriculum
    supply vector ({skill: supply}).

    Every path is labelled as an **association path**, not a causal finding:
    the policy text is a background/explanatory variable here, and the module
    never claims that a policy produced a skill gap. When either side of the
    chain has no usable data the whole result is ``insufficient_evidence`` with
    the reason - "no statistical causal identification" and "no mechanism
    analysis at all" are different outcomes and this function keeps them apart.
    """
    gaps = gaps or {}
    industry_counts = industry_counts or {}
    topics = [t for t in policy_topics if t][:6]
    mentioned = sorted({s for s in policy_skills if s})
    ranked = sorted(
        (s for s, d in demand.items() if d is not None and d >= min_demand),
        key=lambda s: (-(demand.get(s) or 0), s),
    )
    candidates = [s for s in ranked if s in mentioned] or ranked
    candidates = candidates[:top_skills]

    if not topics or not candidates:
        return {
            "status": "insufficient_evidence",
            "label": "政策—产业—岗位—技能—课程 关联路径（非因果）",
            "reason": (
                "缺少可用的政策主题" if not topics else "缺少可用的岗位技能需求"
            ),
            "n_paths": 0,
            "paths": [],
            "topics": topics,
            "caveat": "本模块只输出关联路径，不做因果识别。",
        }

    paths: list[dict[str, Any]] = []
    for skill in candidates:
        d = demand.get(skill)
        s = supply.get(skill)
        g = gaps.get(skill)
        if s is None:
            coverage = "insufficient_evidence"
        elif s > 0:
            coverage = "covered"
        else:
            coverage = "absent_in_scope"
        paths.append({
            "skill": skill,
            "demand": None if d is None else round(float(d), 4),
            "supply": None if s is None else round(float(s), 4),
            "gap": None if g is None else round(float(g), 4),
            "curriculum_status": coverage,
            "policy_mentioned": skill in mentioned,
            "policy_topics": topics[:3],
            "chain": [
                f"政策主题（{len(topics)} 类重点产业方向）",
                f"技能「{skill}」",
                f"市场需求 {None if d is None else round(float(d), 3)}",
                f"课程覆盖 {None if s is None else round(float(s), 3)}",
                f"缺口 {None if g is None else round(float(g), 3)}",
            ],
        })
    paths.sort(key=lambda r: (-(r["demand"] or 0), r["skill"]))
    n_covered = sum(1 for p in paths if p["curriculum_status"] == "covered")
    n_uncovered_gap = sum(
        1 for p in paths
        if p["curriculum_status"] != "covered" and (p["gap"] or 0) > 0.15
    )
    return {
        "status": "association_path",
        "label": "政策—产业—岗位—技能—课程 关联路径（非因果）",
        "n_paths": len(paths),
        "n_gap_paths": sum(1 for p in paths if (p["gap"] or 0) > 0.15),
        "n_uncovered_gap_paths": n_uncovered_gap,
        "n_covered_paths": n_covered,
        "paths": paths,
        "topics": topics,
        "industry_counts": dict(sorted(industry_counts.items(), key=lambda kv: -kv[1])[:8]),
        "summary": (
            f"在 {len(paths)} 条被跟踪的技能路径中，{n_covered} 条已被课程覆盖，"
            f"{n_uncovered_gap} 条处于市场需求高位但课程供给不足（缺口）。"
        ),
        "method_note": (
            "路径基于政策文本提及、招聘需求向量与课程供给向量的共现/差值构造，"
            "属于关联与解释路径，不是因果结论；样本不足以做统计识别时不输出效应量。"
        ),
        "caveat": "关联不等于因果；本输出未做因果识别。",
    }
