"""Metric dependency graph and double-counting audit.

Every indicator in the Core TSI Engine declares which *base variable* it
consumes and how it transforms that variable. Two indicators that consume the
identical base variable with the identical transform are the same measurement
counted twice; the TSI would then weight one fact twice.

Sharing a base variable is allowed when the business definition differs (for
example "加权适配度" and "未覆盖技能比例" both read the supply/demand vectors
but answer different questions); such indicators must declare the shared
primitive explicitly so the audit can tell the two cases apart.

This module also carries the historical map for TSI 2.0, which is how the
legacy double counting (B1 ≡ C4, both equal to the demand-weighted match) is
demonstrated rather than asserted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class MetricNode:
    metric_id: str
    name: str
    dimension: str
    primitives: tuple[str, ...]
    transform: str
    weight: float = 0.0
    derived_from: tuple[str, ...] = ()
    version: str = "primary"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "dimension": self.dimension,
            "primitives": list(self.primitives),
            "transform": self.transform,
            "weight": self.weight,
            "derived_from": list(self.derived_from),
            "version": self.version,
            "note": self.note,
        }


@dataclass
class MetricGraph:
    nodes: list[MetricNode] = field(default_factory=list)

    def add(self, node: MetricNode) -> None:
        self.nodes.append(node)

    def extend(self, nodes: Iterable[MetricNode]) -> None:
        self.nodes.extend(nodes)

    def by_id(self) -> dict[str, MetricNode]:
        return {n.metric_id: n for n in self.nodes}

    def duplicate_groups(self) -> list[dict[str, Any]]:
        buckets: dict[tuple[frozenset[str], str], list[MetricNode]] = {}
        for node in self.nodes:
            key = (frozenset(node.primitives), node.transform)
            buckets.setdefault(key, []).append(node)
        groups = []
        for (primitives, transform), items in buckets.items():
            if len(items) < 2:
                continue
            groups.append({
                "primitives": sorted(primitives),
                "transform": transform,
                "metrics": [n.metric_id for n in items],
                "names": [n.name for n in items],
                "combined_weight": round(sum(n.weight for n in items), 4),
            })
        return sorted(groups, key=lambda g: -g["combined_weight"])

    def double_counting_report(self) -> dict[str, Any]:
        groups = self.duplicate_groups()
        return {
            "n_nodes": len(self.nodes),
            "duplicate_groups": groups,
            "n_duplicate_groups": len(groups),
            "clean": not groups,
            "note": (
                "同一基础变量 + 同一变换重复进入加权即视为 double counting；"
                "共享基础变量但业务定义不同者必须显式声明 primitives。"
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "audit": self.double_counting_report(),
            "primitives": sorted({p for n in self.nodes for p in n.primitives}),
        }


#: TSI 2.0 (analysis/tsi.py) 的底层输入映射。B1 与 C4 都直接等于同一个
#: demand-weighted match，是旧版 double counting 的直接证据。
V2_PRIMITIVES: dict[str, tuple[str, ...]] = {
    "A1": ("semantic.objective_job_alignment",), "A2": ("teaching.senior_title_ratio", "teaching.student_faculty_ratio"),
    "A3": ("teaching.training_base_count",), "A4": ("teaching.funding_per_student",),
    "A5": ("semantic.major_industry_alignment",),
    "B1": ("core.fit",), "B2": ("semantic.curriculum_market_alignment",),
    "B3": ("teaching.curriculum_update_level",), "B4": ("teaching.practice_credit_ratio",),
    "B5": ("teaching.industry_cooperation_level",), "B6": ("core.breadth_recall",),
    "C1": ("employment.placement_rate",), "C2": ("employment.signing_rate",),
    "C3": ("employment.further_study_rate",), "C4": ("core.fit", "core.fit"),
    "C5": ("employment.salary",), "C6": ("employment.employer_rating",),
    "D1": ("market.effective_count",), "D2": ("market.skill_demand_mean",),
    "D3": ("market.emerging_skill_share",), "D4": ("market.skill_trend_growth",),
    "D5": ("market.salary_premium",), "D6": ("market.bachelor_share",),
    "D7": ("market.target_city_share",),
}

#: 声明的 method 只描述打分函数；审计关心的是"同一个数被用了两次"。B1 与 C4
#: 在 analysis/tsi.py 中拿到的都是 ``matching_score_100``（C4 写作
#: ``0.5·m4 + 0.5·m4``，恒等于 m4），因此统一标注为同一变换。
V2_TRANSFORMS: dict[str, str] = {
    "B1": "demand_weighted_fit_scaled_100",
    "C4": "demand_weighted_fit_scaled_100",
}


def v2_graph(specs: Iterable[Any], dimension_weights: dict[str, float]) -> MetricGraph:
    """Build the audit graph for TSI 2.0 from its own spec table."""
    graph = MetricGraph()
    for spec in specs:
        absolute = dimension_weights.get(spec.dimension, 0.0) * spec.weight
        graph.add(MetricNode(
            metric_id=spec.id,
            name=spec.name,
            dimension=spec.dimension,
            primitives=V2_PRIMITIVES.get(spec.id, (f"undefined.{spec.id}",)),
            transform=V2_TRANSFORMS.get(spec.id, spec.method),
            weight=round(absolute, 4),
            version="v2_research_comparison",
        ))
    return graph
