"""Evaluation dimensions 4-6, 9: numerical consistency, repeatability, missing data."""

from __future__ import annotations

import math

from analysis import matching, skill_gap, tsi
from edumatch.evidence import MetricValue


def test_supply_is_capped_and_comparable_with_demand():
    courses = [
        {"name": "机器学习", "credits": 3.5},
        {"name": "深度学习", "credits": 3.5},
        {"name": "程序设计基础（Python）", "credits": 4.0},
    ]
    resolve = lambda name, desc: [name]  # noqa: E731
    matrix = matching.build_course_skill_matrix(courses, resolve, reference_credits=6.0)
    assert math.isclose(matrix.supply["机器学习"], 3.5 / 6.0, rel_tol=1e-9)
    assert 0 <= matrix.supply["程序设计基础（Python）"] <= 1.0
    assert matrix.reference_credits == 6.0


def test_supply_formula_matches_manual_calculation():
    courses = [{"name": "A", "credits": 3.0}, {"name": "B", "credits": 3.0}]
    resolve = lambda name, desc: ["sk"]  # noqa: E731
    matrix = matching.build_course_skill_matrix(courses, resolve, reference_credits=6.0)
    assert math.isclose(matrix.supply["sk"], 1.0, rel_tol=1e-9)
    assert math.isclose(matrix.supply_share["sk"], 1.0, rel_tol=1e-9)
    assert math.isclose(matrix.credits_by_skill["sk"], 6.0, rel_tol=1e-9)


def test_demand_weighted_match_manual():
    supply = {"a": 0.5, "b": 1.0, "c": 0.0}
    demand = {"a": 1.0, "b": 1.0, "c": 1.0}
    result = matching.demand_weighted_match(supply, demand)
    assert math.isclose(result["matching_score"], (0.5 + 1.0 + 0.0) / 3, rel_tol=1e-9)


def test_gap_uses_null_not_zero_when_one_side_missing():
    result = skill_gap.compute_skill_gaps({"Python": 0.6}, {"Java": 0.4})
    rows = {r["skill"]: r for r in result["rows"]}
    assert rows["Python"]["gap"] is None
    assert rows["Python"]["status"] == "insufficient_evidence"
    assert rows["Java"]["gap"] is None
    assert result["skill_gap_index"] is None


def test_gap_index_is_demand_weighted():
    gaps = {"a": 0.5, "b": -0.5}
    supply = {"a": 0.0, "b": 1.0}
    demand = {"a": 1.0, "b": 1.0}
    result = skill_gap.compute_skill_gaps(demand, supply)
    # gap(a)=1.0, gap(b)=0.0, 等权需求 -> 1.0*1.0/2.0 = 0.5
    assert math.isclose(result["skill_gap_index"], 0.5, rel_tol=1e-9)


def test_tsi_excludes_missing_indicators_and_never_zeroes_them():
    metrics = [
        MetricValue("A2", "师资结构达标度", 80.0, confidence=0.8, evidence_level="B", source_count=1),
        MetricValue.missing("A4", "培养条件投入强度", "缺少经费数据"),
    ]
    dims = tsi.dimension_scores(metrics)
    assert dims["A_人才培养基础"]["score"] == 80.0
    assert dims["A_人才培养基础"]["coverage"] < 1.0
    assert "A4" in dims["A_人才培养基础"]["missing_indicators"]


def test_tsi_missing_metric_has_no_value():
    missing = MetricValue.missing("C5", "薪资水平", "no data")
    assert missing.value is None
    assert missing.available is False
    assert missing.confidence == 0.0
    assert missing.evidence_level == "E"


def test_tsi_is_repeatable(run_result, engine):
    again = engine.run("分析人工智能专业与北京AI招聘市场的供需适配与技能缺口", include_template=True)
    assert again["tsi_v2"]["tsi_v2"] == run_result["tsi_v2"]["tsi_v2"]
    assert again["skill_gaps"]["skill_gap_index"] == run_result["skill_gaps"]["skill_gap_index"]
    assert again["matching"]["matching_score"] == run_result["matching"]["matching_score"]


def test_ratio_mapping_is_monotonic():
    low = tsi.map_ratio_to_score(0.5, 1.0)
    mid = tsi.map_ratio_to_score(1.0, 1.0)
    high = tsi.map_ratio_to_score(2.0, 1.0)
    assert low < mid < high
    assert mid == 60.0
    assert high == 100.0
