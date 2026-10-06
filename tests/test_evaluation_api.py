"""三尺度 Evaluation API、Micro 分析、Coverage 管线与决策支援的回归测试。"""

from __future__ import annotations

from pathlib import Path

from analysis import decision_support, evaluation
from edumatch.coverage_pipeline import audit_university_coverage, major_matches_path
from edumatch.profiles import PersonalEvidenceProfile

CORE = Path(__file__).resolve().parents[1]

DEMAND = {"Python": 0.47, "机器学习": 0.34, "深度学习": 0.50,
          "模型部署": 0.37, "大模型": 0.60, "RAG": 0.10}


def _primary(value: float = 61.07) -> dict:
    return {
        "primary_tsi": value, "band": "基本适配", "version": "primary-3.0",
        "weighted_coverage": 1.0, "confidence": 0.6, "n_available": 15, "n_total": 16,
        "missing_indicators": ["M3"],
        "dimensions": {"F_供需适配": {"name": "供需适配", "score": 62.2, "weight": 0.4,
                                       "coverage": 1.0, "confidence": 0.6,
                                       "n_available": 4, "n_total": 4, "missing_indicators": []}},
        "metrics": [{"metric_id": "F1", "name": "技能适配度", "value": 62.2, "status": "ok",
                     "evidence_level": "C", "evidence_ids": ["ev:jobs"], "detail": {}}],
        "versions": {"formal": {"role": "primary", "id": "primary_tsi", "score": value}},
    }


def _fit() -> dict:
    return {"fit": 0.5, "fit_100": 50.0, "per_skill": [
        {"skill": "Python", "demand": 0.47, "supply": 0.0, "gap": 0.47,
         "status": "ok", "supply_basis": "absent_in_scope"},
    ]}


def test_evaluate_macro_and_middle_share_one_skeleton():
    macro = evaluation.evaluate_macro(_primary(), fit=_fit(), demand=DEMAND,
                                      occupation={"n_jobs": 16161,
                                                  "occupation": {"name": "AI"},
                                                  "match_scope": "position"})
    middle = evaluation.evaluate_middle(_primary(65.47), fit=_fit(), demand=DEMAND,
                                        occupation_match={"match_100": 55.06})
    for result in (macro, middle):
        assert result["primary_tsi"] is not None
        assert result["tsi_tree"]["root"]["value"] is not None
        assert result["method_note"]
    assert macro["observed_demand"]["label"] == "Observed Job Posting Demand"
    assert middle["sub_indicators"]["structural_fit_100"] == 55.06


def test_evaluate_micro_sparse_levels_and_three_gaps():
    profile = PersonalEvidenceProfile.from_text(
        "我学过 Python、机器学习，做过一个 RAG 项目，没有正式实习")
    result = evaluation.evaluate_micro(profile, DEMAND, occupation={"name": "大模型算法工程师"})
    assert result["scale"] == "micro"
    assert result["sparse_level"] >= 2
    assert result["fit_100"] is not None
    assert result["gaps"]["skill"]["status"] == "ok"
    # 实践层没有需求向量 → 证据不足，不是 0
    assert result["gaps"]["practice"]["status"] == "insufficient_evidence"
    assert result["priority_actions"]


def test_evaluate_micro_level0_uses_major_baseline():
    profile = PersonalEvidenceProfile(declared={"school": "北京工业大学", "major": "人工智能"})
    profile.refresh()
    result = evaluation.evaluate_micro(profile, DEMAND,
                                       major_baseline={"Python": 0.6, "机器学习": 0.5})
    assert result["sparse_level"] == 0
    assert result["baseline"] is True
    assert result["supply_provenance"] == "major_baseline"
    assert "Major Baseline" in result["baseline_note"]


def test_decision_support_quantifies_intervention():
    supply = {"Python": 0.0, "机器学习": 0.5, "深度学习": 0.4, "模型部署": 0.0}
    demand = {"Python": 0.47, "机器学习": 0.34, "深度学习": 0.50, "模型部署": 0.37}
    plan = decision_support.compare_interventions(supply, demand, [
        {"name": "新增大模型应用开发", "supply_delta": {"模型部署": 0.5}},
        {"name": "强化 Python 实践", "supply_delta": {"Python": 0.6}},
    ])
    assert plan["role"] == "decision_support"
    assert plan["best"]
    assert all(r["delta_fit_100"] is not None for r in plan["scenarios"])
    assert len(plan["scenarios"]) == 3  # A + B + 组合


def test_major_matches_path_rejects_other_majors_containing_the_name():
    assert major_matches_path(Path("2024_人工智能.pdf"), "人工智能") is True
    assert major_matches_path(Path("2023_人工智能-工商管理.pdf"), "人工智能") is True
    assert major_matches_path(Path("电子信息类(含人工智能).pdf"), "人工智能") is False
    assert major_matches_path(Path("2023_法学-人工智能.pdf"), "人工智能") is False


def test_university_coverage_state_machine_end_to_end():
    payload = audit_university_coverage(
        CORE, major="人工智能",
        schools=["北京工业大学", "中国地质大学（北京）"])
    per_school = payload["per_school"]
    assert "北京工业大学" in per_school
    bjut = per_school["北京工业大学"]
    # 课程正文可分析；培养目标正文缺段落 → 不能算全材料覆盖
    assert bjut["materials"]["培养方案课程"]["state"] == "READY_FOR_ANALYSIS"
    assert bjut["materials"]["培养目标"]["state"] == "TEXT_EXTRACTED"
    assert bjut["ready"] is False
    assert payload["coverage_rate"] <= 1.0
