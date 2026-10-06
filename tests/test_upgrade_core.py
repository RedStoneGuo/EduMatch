"""Tests for the multi-scale upgrade core (profiles / capability / conflicts /
TSI tree / scenarios / coverage / semantics).

These are pure-function tests: they never touch the 4.6 GB source archive and
never run the full engine, so they stay fast in CI.
"""

from __future__ import annotations

import pytest

from analysis import capability as capability_mod
from analysis import conflict_resolution as conflict_mod
from analysis import scenario as scenario_mod
from analysis import tsi_tree as tsi_tree_mod
from edumatch import coverage_state, semantics
from edumatch.profiles import (
    Gap,
    PersonalEvidenceProfile,
    SupplyProfile,
    apply_legacy_compat,
    gaps_from_fit,
)


class _FakeVector:
    provenance = "peer"
    status = "ok"
    reason = ""
    n_courses = 5
    n_mapped_courses = 4
    reliability = "medium"
    unavailable_channels = ["objective"]

    def __init__(self, score):
        self.score = score
        self.channels = {}


def test_supply_profile_adapts_vector_and_keeps_missing_none():
    profile = SupplyProfile.from_supply_vector(
        _FakeVector({"Python": 0.8, "Java": None}), scale="major")
    assert profile.scale == "major"
    assert profile.skill_supply["Python"] == 0.8
    assert profile.skill_supply["Java"] is None
    assert profile.coverage["skill"] == 0.5
    assert profile.provenance == "peer"


def test_capability_ignores_missing_components_not_scores_zero():
    supply = {
        "knowledge": {"机器学习": 0.8, "深度学习": None},
        "skill": {"Python": 0.9, "PyTorch": None},
        "practice": {},
    }
    result = capability_mod.infer_capabilities(supply)
    algo = result["cap:algorithm_rd"]
    assert algo["value"] is not None
    assert "knowledge:深度学习" in algo["missing_components"]
    assert algo["coverage"] < 1.0


def test_personal_profile_sparse_levels_and_declared_absence():
    profile = PersonalEvidenceProfile.from_text("我学过 Python 和机器学习，做过 RAG 项目，没有正式实习")
    assert profile.sparse_level >= 2
    assert any(item["item"] == "Python" for item in profile.skill_evidence)
    assert any(item["item"] == "RAG" for item in profile.skill_evidence)
    absences = profile.declared["absences"]
    assert any(a["item"] and a["layer"] == "practice" for a in absences)
    # 声明的缺项没有被写成 practice 证据，也没有被记成 0
    assert not any(item.get("strength") == 0 for item in profile.practice_evidence)


def test_conflict_resolver_recomputes_only_changed_skills():
    supply = {"Python": 0.0, "Java": 0.9}
    demand = {"Python": 0.5, "Java": 0.3}
    evidence = {"Python": {"value": 0.6, "evidence_level": "A",
                           "evidence_id": "ev:bjut:python",
                           "quote": "《Python 程序设计》必修"}}
    result = conflict_mod.resolve_conflicts(supply, demand, evidence, run_id="run:test")
    assert result["status"] == "reconciled"
    assert result["changed_skills"] == ["Python"]
    assert result["reconciled_supply"]["Python"] == 0.6
    assert result["reconciled_supply"]["Java"] == 0.9
    record = result["records"][0]
    for field in ("original_result", "reconciled_result", "evidence_source",
                  "mapping_reason", "changed_skill", "recalculation_scope",
                  "timestamp", "run_id"):
        assert field in record
    assert result["reconciled_result"]["fit_100"] > result["original_result"]["fit_100"]


def test_v2_and_match_duplication_is_not_resurrected():
    """Guard: the upgrade must not reintroduce a second formal total score."""
    primary = {
        "primary_tsi": 61.07, "band": "基本适配", "version": "primary-3.0",
        "weighted_coverage": 1.0, "confidence": 0.6, "n_available": 15, "n_total": 16,
        "missing_indicators": ["M3"],
        "dimensions": {"F_供需适配": {"name": "供需适配", "score": 62.2, "weight": 0.4,
                                       "coverage": 1.0, "confidence": 0.6,
                                       "n_available": 4, "n_total": 4,
                                       "missing_indicators": []}},
        "metrics": [
            {"metric_id": "F1", "name": "技能适配度", "value": 62.2, "status": "ok",
             "evidence_level": "C", "evidence_ids": ["ev:jobs", "ev:courses"], "detail": {}},
            {"metric_id": "M3", "name": "岗位需求规模", "value": None,
             "status": "insufficient_evidence", "evidence_level": "E",
             "evidence_ids": [], "detail": {}},
        ],
    }
    fit = {"per_skill": [
        {"skill": "Python", "demand": 0.47, "supply": 0.0, "gap": 0.47,
         "status": "ok", "supply_basis": "absent_in_scope"},
    ]}
    tree = tsi_tree_mod.build_tsi_tree(primary, fit=fit)
    assert tree["root"]["value"] == 61.07
    assert tree["root"]["children"][0]["children"][0]["id"] == "F1"
    flat = tsi_tree_mod.flatten_tree(tree)
    assert any(n["id"] == "skill:Python" for n in flat)


def test_legacy_compat_adds_canonical_alias_but_keeps_old_key():
    payload = {"match": 60.83, "match_100": 60.83, "tsi_score": 61.07}
    out = apply_legacy_compat(payload)
    assert out["match"] == 60.83
    assert out["structural_fit"] == 60.83
    assert out["structural_fit_100"] == 60.83
    assert out["primary_tsi"] == 61.07
    assert out["legacy_fields"]


def test_gaps_from_fit_keeps_layer_and_severity():
    fit = {"per_skill": [
        {"skill": "模型部署", "demand": 0.37, "supply": 0.0, "gap": 0.37, "supply_basis": "absent_in_scope"},
        {"skill": "Python", "demand": 0.47, "supply": 0.4, "gap": 0.07},
        {"skill": "RAG", "demand": 0.2, "supply": None, "gap": None},
    ]}
    gaps = gaps_from_fit(fit, layer="practice", critical_gap=0.25)
    assert [g.skill for g in gaps] == ["模型部署", "Python"]
    assert gaps[0].category == "critical"
    assert gaps[0].layer == "practice"
    assert isinstance(gaps[0], Gap)


def test_scenario_selection_is_goal_driven_and_capped():
    jobs = [
        {"position": "大模型算法工程师", "job_description": "金融风控 微调 RAG",
         "industry": "金融", "experience": "3-5年"},
        {"position": "AI应用开发工程师", "job_description": "模型部署 医疗",
         "industry": "医疗", "experience": "应届"},
    ]
    dims = scenario_mod.select_dimensions("我想进入金融 AI，做大模型算法")
    assert "industry" in dims
    plan = scenario_mod.plan_scenarios("我想进入金融 AI", jobs, max_scenarios=3)
    assert plan["capped"] is True
    assert len(plan["scenarios"]) == 3


def test_coverage_state_machine_counts_only_ready():
    a = coverage_state.CoverageRecord(school="北京工业大学", major="人工智能")
    a.advance("READY_FOR_ANALYSIS")
    b = coverage_state.CoverageRecord(school="北京邮电大学", major="人工智能",
                                      state="DOWNLOAD_ATTEMPTED", reason="WAF 拦截")
    report = coverage_state.coverage_report([a, b],
                                            target_schools=["北京工业大学", "北京邮电大学"])
    assert report["covered_universities"] == ["北京工业大学"]
    assert report["missing_universities"] == ["北京邮电大学"]
    assert report["coverage_rate"] == 0.5
    with pytest.raises(ValueError):
        coverage_state.CoverageRecord(school="X").advance("SOURCE_VERIFIED").advance("DISCOVERED")


def test_observed_demand_is_not_total_demand():
    observed = coverage_state.observed_job_posting_demand(16161, window="2026-10")
    assert observed["label"] == "Observed Job Posting Demand"
    assert "社会岗位总需求" in observed["not_meaning"]


def test_semantics_guard_catches_and_rewrites_forbidden_claims():
    text = "北京市人工智能专业总供给 × AI 岗位总需求，共 16,161 个岗位需求。"
    findings = semantics.find_forbidden_claims(text)
    assert len(findings) >= 3
    cleaned = semantics.canonicalize(text)
    assert "总供给" not in cleaned
    assert "岗位总需求" not in cleaned
    assert "Observed Job Posting Demand" in cleaned
