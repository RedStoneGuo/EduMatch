"""Evidence-first primitives.

Every quantitative claim produced by the analysis engine must be attached to at
least one :class:`EvidenceItem`. Missing information is represented by
``value is None`` plus ``status='insufficient_evidence'`` - never by score 0.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EvidenceLevel = Literal["A", "B", "C", "D", "E"]

LEVEL_LABEL: dict[str, str] = {
    "A": "官方原始数据直接得到",
    "B": "官方数据计算得到",
    "C": "多来源交叉计算",
    "D": "语义抽取或模型判断",
    "E": "证据不足",
}

LEVEL_CONFIDENCE: dict[str, float] = {"A": 1.0, "B": 0.85, "C": 0.7, "D": 0.5, "E": 0.0}

Status = Literal["ok", "insufficient_evidence", "partial"]


@dataclass
class EvidenceItem:
    evidence_id: str
    source_type: str  # document | database | calculation | policy | job_market
    title: str
    locator: str  # relative file path, url, table id, or formula id
    quote: str = ""
    page: int | None = None
    year: int | None = None
    school: str | None = None
    url: str | None = None
    retrieval_time: str | None = None
    evidence_level: EvidenceLevel = "D"
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["level_label"] = LEVEL_LABEL.get(self.evidence_level, "")
        return data


@dataclass
class MetricValue:
    """A single quantitative metric with explicit missing-data semantics."""

    metric_id: str
    name: str
    value: float | None
    unit: str = "score"
    status: Status = "ok"
    confidence: float = 0.0
    evidence_level: EvidenceLevel = "E"
    source_count: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    available: bool = True
    reason: str = ""
    n_observations: int | None = None
    sample_size_note: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def missing(cls, metric_id: str, name: str, reason: str) -> "MetricValue":
        return cls(
            metric_id=metric_id,
            name=name,
            value=None,
            status="insufficient_evidence",
            confidence=0.0,
            evidence_level="E",
            source_count=0,
            available=False,
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["level_label"] = LEVEL_LABEL.get(self.evidence_level, "")
        return data


class EvidenceStore:
    """In-memory registry used by one analysis run, persistable to SQLite/JSON."""

    def __init__(self) -> None:
        self._items: dict[str, EvidenceItem] = {}

    def add(self, item: EvidenceItem) -> str:
        self._items[item.evidence_id] = item
        return item.evidence_id

    def get(self, evidence_id: str) -> EvidenceItem | None:
        return self._items.get(evidence_id)

    def all(self) -> list[EvidenceItem]:
        return list(self._items.values())

    def to_dicts(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._items.values()]

    def __len__(self) -> int:
        return len(self._items)


def weighted_coverage(values: list[MetricValue], weights: list[float]) -> float:
    """Share of weight backed by non-missing metrics (missing != 0)."""
    total = sum(weights)
    if total <= 0:
        return 0.0
    got = sum(w for v, w in zip(values, weights) if v.available and v.value is not None)
    return round(got / total, 6)
