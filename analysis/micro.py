"""Micro scale: Personal Evidence Profile → personal supply → three gap classes.

The micro scale is the third projection of the same model.  It uses the same
``Fit`` mainline as macro/meso, so a personal score and a major score are never
computed by two different formulas:

    Personal Supply(layer, item) → Fit = Σ Demand·min(Supply,1)/Σ Demand

Three gap classes are reported separately (spec §24) and never collapsed into a
single number:

* **Knowledge Gap**  - 缺哪些知识
* **Skill Gap**      - 缺哪些可执行技能
* **Experience / Practice Gap** - 有知识有技能但缺项目/实习/真实系统

Missing evidence is never a zero: a layer with no demand vector is reported as
``insufficient_evidence``; a declared absence ("没有正式实习") is carried as
``declared_absent`` rather than scored 0.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from edumatch.personal_extract import CAPABILITY_LEXICON, KNOWLEDGE_LEXICON
from edumatch.profiles import LAYERS, PersonalEvidenceProfile, SupplyProfile

from . import fit as fit_mod

#: 自述证据的强度上限（自述永远达不到 A 级；此处只用于相对强度，不对外当能力分）
EVIDENCE_TYPE_STRENGTH: dict[str, float] = {
    "self_report": 0.7,
    "inferred_from_text": 0.5,
    "Learning Practice": 0.5,
    "Project Practice": 0.75,
    "Industry Practice": 0.9,
    "Research Practice": 0.85,
    "Portfolio": 0.6,
    "Certificate": 0.5,
}

#: 招聘语料自动构建的技能词表里含少量无区分度的通用词（宏观报告已披露）。
#: 微观是"个人 vs 岗位"，这些词会造成"学生没提到『问题』"这类噪声，故只在微观过滤。
GENERIC_DEMAND_TOKENS: frozenset[str] = frozenset({
    "问题", "场景", "制定", "内容", "结合", "前沿", "支持", "相关", "进行",
    "识别", "生成", "使用", "具备", "能力", "工作", "方向", "技术", "方法",
})


def personal_supply(profile: PersonalEvidenceProfile) -> dict[str, dict[str, float]]:
    """Aggregate evidence items into per-layer supply strengths (max per item)."""
    supply: dict[str, dict[str, float]] = {layer: {} for layer in LAYERS}
    for layer in LAYERS:
        for item in profile.layer_items(layer):
            name = str(item.get("item") or "").strip()
            if not name:
                continue
            strength = item.get("strength")
            if not isinstance(strength, (int, float)):
                strength = EVIDENCE_TYPE_STRENGTH.get(str(item.get("evidence_type") or ""), 0.5)
            supply[layer][name] = max(supply[layer].get(name, 0.0), float(strength))
    return supply


def classify_demand_layers(demand: Mapping[str, float]) -> dict[str, dict[str, float]]:
    """Split a skill demand vector into knowledge / skill / capability buckets.

    Practice demand cannot be read from a skill list, so it stays empty and is
    reported as insufficient rather than guessed.
    """
    out: dict[str, dict[str, float]] = {layer: {} for layer in LAYERS}
    knowledge_names = set(KNOWLEDGE_LEXICON)
    capability_names = set(CAPABILITY_LEXICON)
    for skill, weight in (demand or {}).items():
        if not isinstance(weight, (int, float)):
            continue
        target = "skill"
        if skill in knowledge_names:
            target = "knowledge"
        else:
            for capability, keywords in CAPABILITY_LEXICON.items():
                if any(k and k in str(skill) for k in keywords):
                    target = "capability"
                    break
        out[target][str(skill)] = float(weight)
    return out


def _layer_gaps(
    demand_layer: Mapping[str, float],
    supply_layer: Mapping[str, float],
) -> dict[str, Any]:
    if not demand_layer:
        return {"status": "insufficient_evidence", "rows": [], "n_gap": 0,
                "reason": "该层没有可核查的需求向量，不输出该层缺口结论"}
    rows = []
    not_evidenced: list[str] = []
    for skill, need in sorted(demand_layer.items(), key=lambda kv: -kv[1]):
        have = _lookup_supply(supply_layer, skill)
        if have is None:
            not_evidenced.append(skill)
            rows.append({"item": skill, "demand": round(float(need), 4), "supply": None,
                         "gap": None, "status": "not_evidenced"})
            continue
        rows.append({"item": skill, "demand": round(float(need), 4),
                     "supply": round(float(have), 4),
                     "gap": round(float(need) - float(have), 4),
                     "status": "gap" if need - have > 0.05 else "covered"})
    gaps = [r for r in rows if r["status"] == "gap"]
    return {"status": "ok", "rows": rows, "n_gap": len(gaps),
            "top_gaps": sorted(gaps, key=lambda r: -(r["gap"] or 0))[:8],
            "not_evidenced": not_evidenced[:12],
            "not_evidenced_note": ("以下项未在个人证据中出现，属于证据不足，"
                                   "不等同于能力为 0，需补充材料确认。")}


def _lookup_supply(supply_layer: Mapping[str, float], skill: str) -> float | None:
    """Exact match first, then a conservative containment match (大模型 ← 大模型原理)."""
    if skill in supply_layer:
        return float(supply_layer[skill])
    matches = [value for item, value in supply_layer.items() if _safe_contains(item, skill)]
    if not matches:
        return None
    return max(float(v) for v in matches)


def _safe_contains(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if (a.isascii() and len(a) <= 3) or (b.isascii() and len(b) <= 3):
        # 短拉丁串（C / C++ / AI）必须精确匹配，避免 "C" ⊂ "C++" 这类误配
        return a == b
    return a in b or b in a


def analyze_micro(
    profile: PersonalEvidenceProfile,
    demand: Mapping[str, float],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    occupation: Mapping[str, Any] | None = None,
    major_baseline: Mapping[str, float] | None = None,
    baseline_note: str = "",
) -> dict[str, Any]:
    """Full micro analysis: supply, fit, three gaps, sparse level, priorities."""
    supply = personal_supply(profile)
    filtered = {k: v for k, v in (demand or {}).items() if k not in GENERIC_DEMAND_TOKENS}
    layers_demand = classify_demand_layers(filtered)

    skill_supply = dict(supply["skill"])
    provenance = "personal_evidence"
    if profile.sparse_level == 0 and major_baseline:
        # L0：只有学校+专业+年级+岗位 → 用专业基准推断，并明确标注
        skill_supply = dict(major_baseline)
        provenance = "major_baseline"

    fit = fit_mod.skill_fit(
        skill_supply, filtered, demand_meta=demand_meta or {},
        supply_provenance=provenance,
        supply_status="ok" if skill_supply else "insufficient_evidence",
        supply_reliability="low" if profile.sparse_level <= 1 else "medium",
        # 个人"没提到"不等于"能力为 0"：未知技能不进分母，只降低覆盖率。
        unlisted_supply_is_zero=False,
    )

    gaps = {
        "knowledge": _layer_gaps(layers_demand["knowledge"], supply["knowledge"]),
        "skill": _layer_gaps(layers_demand["skill"], supply["skill"]),
        "capability": _layer_gaps(layers_demand["capability"], supply["capability"]),
        "practice": _layer_gaps(layers_demand["practice"], supply["practice"]),
    }
    if not gaps["capability"]["rows"]:
        # 能力层没有显式需求时，用个人实践/技能证据反过来给"可推断能力"清单
        gaps["capability"]["inferred_from_evidence"] = sorted(supply["capability"])

    is_baseline = profile.sparse_level == 0
    return {
        "scale": "micro",
        "sparse_level": profile.sparse_level,
        "baseline": is_baseline,
        "baseline_note": baseline_note or (
            "仅学校+专业+年级+目标岗位：以下为**专业基准推断（Major Baseline）**，"
            "不是对真实个人能力的判断。" if is_baseline else ""
        ),
        "supply_provenance": provenance,
        "personal_supply": supply,
        "demand_layers": layers_demand,
        "fit": fit,
        "fit_100": fit.get("fit_100"),
        "gaps": gaps,
        "declared": profile.declared,
        "filtered_generic_tokens": sorted(set(demand or {}) & GENERIC_DEMAND_TOKENS),
        "occupation": dict(occupation or {}),
        "evidence_summary": profile.summary(),
        "method": ("Personal Supply → 同一 Fit 主线；"
                   "Knowledge / Skill / Capability / Practice 四层缺口分别输出，不合成单一数字。"),
    }


def priority_actions(result: Mapping[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    """One deterministic action per top gap - used by the Finding-driven report."""
    actions: list[dict[str, Any]] = []
    for layer in ("skill", "knowledge", "capability", "practice"):
        gap_block = (result.get("gaps") or {}).get(layer) or {}
        for row in (gap_block.get("top_gaps") or [])[:limit]:
            actions.append({
                "layer": layer,
                "item": row["item"],
                "gap": row.get("gap"),
                "action": f"补齐「{row['item']}」：课程/项目/实习三选一，并留下可核查产出",
            })
        for item in (gap_block.get("not_evidenced") or [])[:limit]:
            actions.append({
                "layer": layer,
                "item": item,
                "gap": None,
                "action": f"「{item}」在个人证据中未出现（证据不足，不等于 0）：补一份可核查材料再判断",
            })
    practice_gap = ((result.get("gaps") or {}).get("practice") or {})
    if practice_gap.get("status") != "ok":
        actions.append({
            "layer": "practice",
            "item": "Industry / Project Practice",
            "gap": None,
            "action": "实践证据不足：需要补充项目/实习的可核查记录（当前为证据不足，不是 0 分）",
        })
    return actions[:limit]
