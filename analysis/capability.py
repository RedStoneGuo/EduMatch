"""Capability inference - the third layer of Knowledge→Skill→Capability→Practice.

Capability is **not** a synonym for Skill.  It is the ability to solve a class
of problems, inferred from a documented combination of knowledge, skills and
practice.  The inference here is deterministic and auditable:

    Capability(c) = Σ_r w_r · min(Supply(layer_r, item_r), 1) / Σ_r w_r

over the rule's components that are *available*.  Missing components are
excluded from the denominator and listed in ``missing_components`` - a missing
project never turns a capability into a zero (spec §4, §29).

The rules live in this file so that every inferred capability can be traced to
its exact inputs; no LLM is involved and no number is invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from edumatch.profiles import LAYERS, SupplyProfile


@dataclass(frozen=True)
class CapabilityRule:
    id: str
    name: str
    #: component -> weight; component is "layer:item" (e.g. "skill:Python").
    components: dict[str, float]
    note: str = ""


DEFAULT_RULES: tuple[CapabilityRule, ...] = (
    CapabilityRule(
        "cap:algorithm_rd", "算法研发能力",
        {"knowledge:机器学习": 0.25, "knowledge:深度学习": 0.25,
         "skill:Python": 0.15, "skill:PyTorch": 0.15,
         "practice:Industry Practice": 0.10, "practice:Project Practice": 0.10},
        "以机器学习/深度学习知识为底座，靠 Python+框架落地，实践证据加权。",
    ),
    CapabilityRule(
        "cap:llm_application", "大模型应用能力",
        {"knowledge:大模型原理": 0.30, "knowledge:Transformer": 0.20,
         "skill:RAG": 0.15, "skill:Prompt工程": 0.15,
         "skill:模型微调": 0.10, "practice:Project Practice": 0.10},
        "大模型原理 + RAG/Prompt/微调 + 项目实践的复合能力。",
    ),
    CapabilityRule(
        "cap:ai_engineering", "AI 工程开发能力",
        {"skill:Python": 0.20, "skill:模型部署": 0.25, "skill:数据处理": 0.15,
         "skill:Docker": 0.10, "practice:Industry Practice": 0.30},
        "工程化落地能力，产业实践权重最高。",
    ),
    CapabilityRule(
        "cap:model_training", "模型训练能力",
        {"knowledge:深度学习": 0.30, "skill:PyTorch": 0.25, "skill:数据处理": 0.15,
         "skill:模型微调": 0.15, "practice:Research Practice": 0.15},
        "训练/微调模型的综合能力。",
    ),
    CapabilityRule(
        "cap:evaluation", "模型评测能力",
        {"knowledge:概率统计": 0.30, "knowledge:机器学习": 0.20,
         "skill:数据处理": 0.20, "practice:Project Practice": 0.30},
        "以统计与数据处理为基础的评测能力。",
    ),
    CapabilityRule(
        "cap:data_analysis", "数据分析能力",
        {"knowledge:概率统计": 0.25, "knowledge:数据库": 0.15,
         "skill:SQL": 0.20, "skill:数据处理": 0.20, "skill:数据可视化": 0.10,
         "practice:Industry Practice": 0.10},
        "统计+SQL+数据处理+可视化的分析能力。",
    ),
    CapabilityRule(
        "cap:research", "研究创新能力",
        {"knowledge:机器学习": 0.20, "knowledge:优化": 0.20,
         "skill:Python": 0.15, "practice:Research Practice": 0.45},
        "科研实践是研究创新能力的主要证据。",
    ),
)


def _lookup(layer: str, item: str, vectors: Mapping[str, Mapping[str, float | None]]) -> float | None:
    value = (vectors.get(layer) or {}).get(item)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_capabilities(
    supply: Mapping[str, Mapping[str, float | None]],
    *,
    rules: Sequence[CapabilityRule] = DEFAULT_RULES,
) -> dict[str, dict[str, Any]]:
    """Infer capability strengths from knowledge/skill/practice vectors."""
    result: dict[str, dict[str, Any]] = {}
    for rule in rules:
        num = 0.0
        den = 0.0
        components: list[dict[str, Any]] = []
        missing: list[str] = []
        for component, weight in rule.components.items():
            layer, item = component.split(":", 1)
            value = _lookup(layer, item, supply)
            available = value is not None
            components.append({"component": component, "weight": weight,
                               "value": None if value is None else round(value, 4),
                               "available": available})
            if not available:
                missing.append(component)
                continue
            num += weight * min(max(value, 0.0), 1.0)
            den += weight
        value = round(num / den, 4) if den else None
        result[rule.id] = {
            "id": rule.id,
            "name": rule.name,
            "value": value,
            "status": "ok" if value is not None else "insufficient_evidence",
            "coverage": round(den / sum(rule.components.values()), 4) if rule.components else 0.0,
            "components": components,
            "missing_components": missing,
            "note": rule.note,
            "method": "Σ w·min(Supply,1)/Σ w（仅可用分量，缺失不记 0）",
        }
    return result


def enrich_supply_profile(
    profile: SupplyProfile,
    *,
    rules: Sequence[CapabilityRule] = DEFAULT_RULES,
) -> SupplyProfile:
    """Fill ``capability_supply`` in-place and refresh coverage."""
    vectors = {layer: profile.vector(layer) for layer in LAYERS}
    inferred = infer_capabilities(vectors, rules=rules)
    for cap_id, item in inferred.items():
        profile.capability_supply[item["name"]] = item["value"]
        profile.meta.setdefault("capability_detail", {})[cap_id] = item
    profile.refresh_coverage()
    return profile


def rule_table() -> list[dict[str, Any]]:
    return [
        {"id": r.id, "name": r.name, "components": dict(r.components), "note": r.note}
        for r in DEFAULT_RULES
    ]
