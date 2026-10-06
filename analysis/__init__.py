"""EduMatch quantitative analysis engine.

Every module in this package is a pure function library: no LLM calls, no
network access, deterministic inputs and outputs. The LLM layer may only call
these functions and interpret their results.
"""

from . import (
    benchmark,
    confidence,
    demand,
    fit,
    matching,
    mechanism,
    metric_graph,
    occupation_match,
    primary_tsi,
    simulation,
    skill_gap,
    supply,
    trend,
    tsi,
    tsi_v1,
)

__all__ = [
    "benchmark",
    "confidence",
    "demand",
    "fit",
    "matching",
    "mechanism",
    "metric_graph",
    "occupation_match",
    "primary_tsi",
    "simulation",
    "skill_gap",
    "supply",
    "trend",
    "tsi",
    "tsi_v1",
]
