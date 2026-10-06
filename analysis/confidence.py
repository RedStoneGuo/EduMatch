"""Confidence and evidence-level aggregation rules."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

LEVEL_CONFIDENCE = {"A": 1.0, "B": 0.85, "C": 0.7, "D": 0.5, "E": 0.0}
LEVEL_ORDER = ["A", "B", "C", "D", "E"]


def level_from_sources(source_levels: Sequence[str]) -> str:
    """Aggregate evidence level: identical levels collapse, otherwise take C."""
    levels = [lv for lv in source_levels if lv in LEVEL_CONFIDENCE]
    if not levels:
        return "E"
    if len(set(levels)) == 1:
        return levels[0]
    if set(levels) <= {"A", "B"}:
        return "A" if set(levels) == {"A"} else "B"
    return "C"


def combine_confidence(pairs: Iterable[tuple[float, float]]) -> float:
    """Weighted mean confidence from (confidence, weight) pairs."""
    pairs = [(c, w) for c, w in pairs if w > 0]
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.0
    return round(sum(c * w for c, w in pairs) / total, 4)


def coverage_ratio(available_weights: Sequence[float], all_weights: Sequence[float]) -> float:
    total = sum(all_weights)
    if total <= 0:
        return 0.0
    return round(sum(available_weights) / total, 4)


def most_common_level(levels: Sequence[str]) -> str:
    levels = [lv for lv in levels if lv in LEVEL_CONFIDENCE]
    if not levels:
        return "E"
    return Counter(levels).most_common(1)[0][0]


def sample_size_penalty(n: int | None, min_n: int = 5) -> float:
    """Small samples cannot support confident claims."""
    if n is None:
        return 0.5
    if n >= min_n:
        return 1.0
    return max(n / min_n, 0.1)


def confidence_with_sample(base: float, n: int | None, min_n: int = 5) -> float:
    return round(base * sample_size_penalty(n, min_n), 4)
